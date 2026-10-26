"""The privileged helper and its installer (SDD-170).

These are the only files in the project that ever run as root, so every property that keeps them
safe is asserted rather than trusted to review.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

PRIV = Path(__file__).parent.parent.parent / "deploy" / "privileged"
HELPER = PRIV / "dgxctl-helper"
ENABLE = PRIV / "enable.sh"
INSTALLED = "/usr/local/libexec/dgxctl/dgxctl-helper"


def run_helper(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(HELPER), *args], capture_output=True, text=True)


# --- the helper ---------------------------------------------------------------


def test_helper_check_reports_ok():
    out = run_helper("check")
    assert out.returncode == 0 and out.stdout.strip() == "ok"


@pytest.mark.parametrize("arg", ["", "kill", "sockets;id", "../../bin/sh", "--help", "SOCKETS"])
def test_helper_rejects_unknown_subcommands(arg):
    out = run_helper(arg) if arg else run_helper()
    assert out.returncode == 2, f"{arg!r} was accepted"


def test_helper_rejects_extra_arguments():
    """sudo only permits the exact argv in the rule, but the helper must not rely on that."""
    assert run_helper("check", "extra").returncode == 2
    assert run_helper("sockets", "-a").returncode == 2


def test_helper_sets_its_own_path():
    """Never trust the caller's PATH in something that runs as root."""
    text = HELPER.read_text()
    assert re.search(r"^PATH=/usr/sbin:/usr/bin:/sbin:/bin$", text, re.M)
    assert "export PATH" in text
    env = {"PATH": "/nonexistent"}
    out = subprocess.run(["/bin/sh", str(HELPER), "check"], capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "ok"


def test_helper_cannot_write_or_kill():
    """Read-only by construction: nothing that changes state, and no dynamic evaluation."""
    code = "\n".join(
        ln
        for ln in HELPER.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )
    for forbidden in ("kill", "rm ", "eval", "$(", "`", "sudo", "chmod", "chown", "tee", "dd "):
        assert forbidden not in code, f"helper contains {forbidden!r}"
    # Output redirection to a file. `>&2` (to stderr) is the only redirect allowed.
    assert not re.search(r">(?!&2)", code), "helper writes to a file"


def test_helper_runs_exactly_one_command_per_subcommand():
    code = HELPER.read_text()
    assert "exec ss -tulnpH" in code
    assert code.count("exec ") == 1, "only the sockets subcommand should exec anything"


# --- the sudoers rule --------------------------------------------------------


def sudoers_for(user: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(ENABLE), "--print-sudoers", user], capture_output=True, text=True
    )


def test_sudoers_rule_names_exact_argv():
    out = sudoers_for("alice")
    assert out.returncode == 0, out.stderr
    rules = [ln for ln in out.stdout.splitlines() if ln and not ln.startswith("#")]
    grant = [ln for ln in rules if "NOPASSWD" in ln]
    assert len(grant) == 1
    line = grant[0]
    assert line.startswith("alice ALL=(root) NOPASSWD: ")
    commands = [c.strip() for c in line.split("NOPASSWD:", 1)[1].split(",")]
    assert commands == [f"{INSTALLED} check", f"{INSTALLED} sockets"]
    assert "*" not in line, "a wildcard would let any argument through"
    assert not re.search(r"NOPASSWD:\s*ALL", line)


def test_sudoers_suppresses_logging_only_for_the_helper():
    """~4 calls a minute would otherwise write ~17k lines a day to auth.log and drown real
    events. Scoped to this one command; denied attempts still log (log_denied stays on)."""
    out = sudoers_for("alice").stdout
    defaults = [ln for ln in out.splitlines() if ln.startswith("Defaults")]
    assert defaults == [f"Defaults!{INSTALLED} !log_allowed, !pam_session"]
    assert "log_denied" not in out


@pytest.mark.parametrize("bad", ["bob,ALL", "bob ALL=(ALL)", "root", "", "a b", "x\nALL"])
def test_sudoers_rejects_hostile_or_invalid_user_names(bad):
    out = sudoers_for(bad)
    assert out.returncode != 0, f"{bad!r} produced a rule"


# --- the installer ------------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="must be run as a non-root user")
def test_enable_refuses_to_run_without_root():
    out = subprocess.run(["bash", str(ENABLE)], capture_output=True, text=True)
    assert out.returncode != 0
    assert "must run as root" in out.stderr


def test_enable_refuses_root_as_the_target_user():
    """`sudo su; ./enable.sh` would grant root to root — pointless, and a sign of a mistake."""
    text = ENABLE.read_text()
    assert "SUDO_USER" in text
    assert re.search(r'= "root"', text)


def test_enable_validates_sudoers_before_installing():
    """A malformed file in /etc/sudoers.d can break sudo for the whole machine."""
    text = ENABLE.read_text()
    validate = text.find("visudo -cf")
    install = text.find('"$SUDOERS"', text.find("install -o root"))
    assert validate != -1 and install != -1 and validate < install


def test_enable_installs_root_owned_and_not_writable():
    text = ENABLE.read_text()
    assert 'install -o root -g root -m 0755 "$HERE/dgxctl-helper" "$HELPER"' in text
    assert re.search(r'install -o root -g root -m 0440 "\$tmp" "\$SUDOERS"', text)
    assert 'install -d -o root -g root -m 0755 "$DEST_DIR"' in text


def test_enable_has_a_remove_path():
    assert "--remove" in ENABLE.read_text()


def test_scripts_are_strict_and_parse():
    assert "set -euo pipefail" in ENABLE.read_text()
    assert "set -eu" in HELPER.read_text()
    for script in (ENABLE, HELPER):
        shell = "bash" if script == ENABLE else "sh"
        assert subprocess.run([shell, "-n", str(script)]).returncode == 0


def test_the_ordinary_installer_still_never_uses_sudo():
    """R14.1: enabling privilege is a separate, deliberate step, never part of install."""
    install = (PRIV.parent / "install.sh").read_text()
    assert not re.search(r"^\s*sudo\b", install, re.M)
    assert "enable.sh" not in install or "#" in install.split("enable.sh")[0].splitlines()[-1]


# --- SDD-175: the opt-in also relaxes NoNewPrivileges, for that install only ---


def test_unit_keeps_no_new_privileges_by_default():
    """Hardening stays on for everyone who never opts in."""
    unit = (PRIV.parent / "dgxctl.service").read_text()
    directives = [ln.strip() for ln in unit.splitlines() if ln.strip() and not ln.startswith("#")]
    assert "NoNewPrivileges=true" in directives


def test_enable_writes_a_drop_in_that_relaxes_it():
    text = ENABLE.read_text()
    assert "dgxctl.service.d" in text
    assert "NoNewPrivileges=false" in text


def test_enable_writes_the_drop_in_as_the_user_not_as_root():
    """Root writing into a user-controlled directory invites a symlink attack; do it as them."""
    text = ENABLE.read_text()
    assert 'runuser -u "$USER_NAME"' in text
    dropin_writes = [ln for ln in text.splitlines() if "privileged.conf" in ln and ">" in ln]
    for ln in dropin_writes:
        assert "runuser" in ln, f"drop-in written as root: {ln.strip()}"


def test_remove_deletes_the_drop_in_too():
    text = ENABLE.read_text()
    start = text.index('= "--remove" ]')
    remove_block = text[start : text.index("exit 0", start)]
    assert "privileged.conf" in remove_block
