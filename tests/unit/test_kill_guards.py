"""Spec S6: the process-kill refusal matrix. Refusals must state their reason."""

from __future__ import annotations

import os
import sys

import psutil
import pytest

from dgxctl.actions.runner import ActionDenied, ActionRunner


def test_refuses_pid_1():
    with pytest.raises(ActionDenied, match="pid 1"):
        ActionRunner.assert_killable(1)


def test_refuses_pid_zero_and_negative():
    for pid in (0, -1):
        with pytest.raises(ActionDenied):
            ActionRunner.assert_killable(pid)


def test_refuses_nonexistent_pid():
    pid = 999_999
    while psutil.pid_exists(pid):
        pid += 1
    with pytest.raises(ActionDenied, match="does not exist"):
        ActionRunner.assert_killable(pid)


def test_refuses_own_process():
    with pytest.raises(ActionDenied, match="dgxctl itself"):
        ActionRunner.assert_killable(os.getpid())


def test_refuses_an_ancestor():
    parent = psutil.Process(os.getpid()).parent()
    if parent is None:
        pytest.skip("no parent process")
    with pytest.raises(ActionDenied, match="ancestor"):
        ActionRunner.assert_killable(parent.pid)


def test_refuses_another_users_process():
    """Root-owned processes exist on every host; none of them is ours to kill.

    Kernel threads are skipped when picking a subject: on Linux the first other-user
    process is usually pid 2 (kthreadd), which is refused by the earlier kernel-thread
    rule and so would not exercise the ownership rule at all.
    """
    me = psutil.Process().username()
    for proc in psutil.process_iter(["pid", "username"]):
        try:
            if proc.info["username"] in (None, me) or proc.pid <= 1:
                continue
            if not proc.cmdline():  # kernel thread
                continue
            with pytest.raises(ActionDenied, match="owned by|not accessible|cannot verify"):
                ActionRunner.assert_killable(proc.pid)
            return
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    pytest.skip("no other-user userspace process visible")


def test_refuses_kernel_threads_before_checking_ownership():
    """On Linux pid 2 is kthreadd, and every kernel thread descends from it."""
    try:
        if psutil.Process(2).cmdline():
            pytest.skip("pid 2 is not a kernel thread on this platform")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pytest.skip("pid 2 not inspectable")
    with pytest.raises(ActionDenied, match="kernel thread"):
        ActionRunner.assert_killable(2)


def test_refusal_messages_are_specific_enough_for_the_ui():
    """FE-2.3 renders the reason verbatim, so it must not be a bare 'denied'."""
    try:
        ActionRunner.assert_killable(1)
    except ActionDenied as exc:
        assert len(str(exc)) > 25 and "refusing" in str(exc).lower()


def test_allows_a_process_we_own():
    import subprocess

    proc = subprocess.Popen(["sleep", "30"])
    try:
        ActionRunner.assert_killable(proc.pid)  # our own child: allowed
    finally:
        proc.kill()
        proc.wait()


def test_sdd053_process_mid_exec_is_not_mistaken_for_a_kernel_thread():
    """Live regression, found on a DGX Spark.

    `Popen` returns before `execve` completes, so a genuine userspace process has an EMPTY
    cmdline for a moment. Treating "no cmdline" as "kernel thread" refused real processes.
    """
    import subprocess

    from dgxctl.actions.runner import is_kernel_thread

    class MidExec:
        """A real process caught between fork and exec: no cmdline, parent is not pid 2."""

        pid = 4242

        def cmdline(self):
            return []

        def ppid(self):
            return os.getpid()

    assert is_kernel_thread(MidExec()) is False

    # And the loop must still hold for many rapid spawns, which is how this was found.
    for _ in range(25):
        proc = subprocess.Popen(["sleep", "5"])
        try:
            ActionRunner.assert_killable(proc.pid)
        finally:
            proc.kill()
            proc.wait()


def test_kthreadd_and_its_children_are_still_refused():
    if not sys.platform.startswith("linux"):
        pytest.skip("kernel-thread detection is Linux-specific")
    from dgxctl.actions.runner import is_kernel_thread

    try:
        assert is_kernel_thread(psutil.Process(2)) is True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pytest.skip("pid 2 not inspectable")
