"""Trusting the privileged helper, and falling back (SDD-171).

A sudoers rule pointing at a file a user can modify is a root shell for that user. These tests are
mostly about refusing.
"""

from __future__ import annotations

import os
import stat

import pytest

from dgxctl import privileged as pv
from dgxctl.collectors.base import CommandError


def fake_helper(tmp_path, mode=0o755):
    helper = tmp_path / "dgxctl-helper"
    helper.write_text("#!/bin/sh\necho ok\n")
    helper.chmod(mode)
    return helper


def ok_runner(argv, timeout=10.0):
    return (
        "ok\n"
        if argv[-1] == "check"
        else 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1,fd=3))\n'
    )


def failing_runner(argv, timeout=10.0):
    raise CommandError("sudo: a password is required")


def root_owned(monkeypatch):
    """Tests cannot chown to root; pretend ownership while keeping the real mode bits."""
    real = os.stat

    def fake_stat(path, *a, **k):
        st = real(path, *a, **k)
        values = list(st)
        values[stat.ST_UID] = 0
        return os.stat_result(values)

    monkeypatch.setattr(pv.os, "stat", fake_stat)


def test_missing_helper_is_not_available(tmp_path):
    status = pv.inspect(tmp_path / "nope", runner=ok_runner)
    assert status.state == pv.NOT_INSTALLED
    assert status.usable is False
    assert "enable.sh" in (status.fix or "")


def test_user_owned_helper_is_refused_as_insecure(tmp_path):
    """The realistic attack: a writable file at a path sudo would run as root."""
    helper = fake_helper(tmp_path)  # owned by whoever runs the tests — not root
    if os.geteuid() == 0:
        pytest.skip("cannot construct a non-root-owned file as root")
    status = pv.inspect(helper, runner=ok_runner)
    assert status.state == pv.INSECURE
    assert status.usable is False


@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777])
def test_group_or_world_writable_helper_is_refused(tmp_path, monkeypatch, mode):
    root_owned(monkeypatch)
    status = pv.inspect(fake_helper(tmp_path, mode), runner=ok_runner)
    assert status.state == pv.INSECURE, oct(mode)


def test_writable_parent_directory_is_refused(tmp_path, monkeypatch):
    """A writable directory lets someone swap the file out from under a correct mode."""
    root_owned(monkeypatch)
    d = tmp_path / "libexec"
    d.mkdir()
    d.chmod(0o777)
    status = pv.inspect(fake_helper(d), runner=ok_runner)
    assert status.state == pv.INSECURE


def test_root_owned_and_permitted_helper_is_enabled(tmp_path, monkeypatch):
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    status = pv.inspect(fake_helper(tmp_path), runner=ok_runner)
    assert status.state == pv.ENABLED and status.usable


def test_installed_but_not_permitted_by_sudo(tmp_path, monkeypatch):
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    status = pv.inspect(fake_helper(tmp_path), runner=failing_runner)
    assert status.state == pv.NOT_PERMITTED
    assert not status.usable and status.fix


def test_config_off_disables_it_even_when_installed(tmp_path, monkeypatch):
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    status = pv.inspect(fake_helper(tmp_path), mode="off", runner=ok_runner)
    assert status.state == pv.DISABLED and not status.usable


# --- the runner ---------------------------------------------------------------


def enabled_runner(tmp_path, monkeypatch, runner=ok_runner):
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    return pv.PrivilegedRunner(helper=fake_helper(tmp_path), runner=runner)


def test_runner_returns_helper_output_when_enabled(tmp_path, monkeypatch):
    r = enabled_runner(tmp_path, monkeypatch)
    assert "sshd" in r.run("sockets")


def test_runner_returns_none_when_not_installed(tmp_path):
    r = pv.PrivilegedRunner(helper=tmp_path / "nope", runner=ok_runner)
    assert r.run("sockets") is None


def test_sudo_failure_falls_back_cleanly(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky(argv, timeout=10.0):
        calls["n"] += 1
        if argv[-1] == "check":
            return "ok"
        raise CommandError("boom")

    r = enabled_runner(tmp_path, monkeypatch, runner=flaky)
    assert r.run("sockets") is None, "a failing helper must degrade, not raise"


def test_helper_argv_is_fixed(tmp_path, monkeypatch):
    """The code path cannot pass anything but a known subcommand to something running as root."""
    seen = []

    def spy(argv, timeout=10.0):
        seen.append(argv)
        return "ok"

    r = enabled_runner(tmp_path, monkeypatch, runner=spy)
    with pytest.raises(ValueError):
        r.run("sockets; id")
    with pytest.raises(ValueError):
        r.run("--anything")
    r.run("sockets")
    for argv in seen:
        assert argv[:2] == ["sudo", "-n"] and len(argv) == 4
        assert argv[3] in pv.SUBCOMMANDS


def test_status_is_cached(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting(argv, timeout=10.0):
        calls["n"] += 1
        return "ok"

    r = enabled_runner(tmp_path, monkeypatch, runner=counting)
    for _ in range(5):
        r.status()
    assert calls["n"] == 1, "inspect should not shell out to sudo on every call"


# --- SDD-175: NoNewPrivileges (live regression) -------------------------------


def test_no_new_privileges_is_reported_specifically(tmp_path, monkeypatch):
    """Live regression: the service unit's NoNewPrivileges=true stops sudo from ever gaining
    root, while the same check from a shell succeeds. The status must name the real cause."""
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    monkeypatch.setattr(pv, "no_new_privileges", lambda pid=None: True)
    status = pv.inspect(fake_helper(tmp_path), runner=ok_runner)
    assert status.state == pv.NOT_PERMITTED
    assert "NoNewPrivileges" in status.detail
    assert "daemon-reload" in (status.fix or "")


def test_no_new_privileges_is_checked_before_calling_sudo(tmp_path, monkeypatch):
    """Calling sudo under NoNewPrivs just produces a confusing error; don't."""
    root_owned(monkeypatch)
    tmp_path.chmod(0o755)
    monkeypatch.setattr(pv, "no_new_privileges", lambda pid=None: True)
    calls = []
    pv.inspect(fake_helper(tmp_path), runner=lambda argv, timeout=10.0: calls.append(argv) or "ok")
    assert calls == []


def test_no_new_privileges_reads_proc_status(tmp_path, monkeypatch):
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nNoNewPrivs:\t1\nSeccomp:\t0\n")
    monkeypatch.setattr(pv, "_proc_status_path", lambda pid: status)
    assert pv.no_new_privileges() is True
    status.write_text("Name:\tpython\nNoNewPrivs:\t0\n")
    assert pv.no_new_privileges() is False


def test_unreadable_proc_status_assumes_no_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "_proc_status_path", lambda pid: tmp_path / "missing")
    assert pv.no_new_privileges() is False


def test_cli_checks_the_running_service_not_just_the_shell(monkeypatch):
    """Live regression: `dgxctl privileged` said "enabled" from a shell while the running
    service could not use the helper at all."""
    from typer.testing import CliRunner

    from dgxctl.cli import app

    monkeypatch.setattr(
        "dgxctl.privileged.inspect",
        lambda helper=None, mode="auto", runner=None: pv.HelperStatus(pv.ENABLED, "enabled"),
    )
    monkeypatch.setattr("dgxctl.privileged.service_pid", lambda: 4242)
    monkeypatch.setattr("dgxctl.privileged.no_new_privileges", lambda pid=None: pid == 4242)
    out = CliRunner().invoke(app, ["privileged"])
    assert "running service cannot use it" in out.output
    assert "daemon-reload" in out.output
