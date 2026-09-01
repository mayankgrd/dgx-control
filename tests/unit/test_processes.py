"""Host-process launching and adoption (SDD-100, SDD-101)."""

from __future__ import annotations

import os
import subprocess
import time

import psutil
import pytest

from dgxctl import processes as procreg


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    for entry in list(procreg.prune()):
        procreg.forget(entry)


def _spawn(script: str = "import time; time.sleep(30)") -> subprocess.Popen:
    return subprocess.Popen(["python3", "-c", script])


def test_launch_records_pid_port_and_log(tmp_path):
    inst = procreg.launch(
        "demo", ["python3", "-c", "print('hello'); import time; time.sleep(5)"], port=1234
    )
    try:
        assert inst.pid > 0
        assert inst.port == 1234
        assert inst.origin == "dgxctl"
        assert procreg.tracked("demo").pid == inst.pid
        time.sleep(0.6)
        assert "hello" in procreg.read_log("demo")
    finally:
        psutil.Process(inst.pid).kill()


def test_launch_rejects_a_shell_string():
    """Spec S8 applies to host processes exactly as it does to containers."""
    with pytest.raises(TypeError):
        procreg.launch("demo", "python3 -c 'print(1)'")  # type: ignore[arg-type]


def test_launched_process_is_detached_from_this_one():
    """It must outlive the request that started it, and dgxctl restarting."""
    inst = procreg.launch("demo", ["python3", "-c", "import time; time.sleep(20)"])
    try:
        assert os.getsid(inst.pid) != os.getsid(os.getpid()), "process shares our session"
    finally:
        psutil.Process(inst.pid).kill()


def test_registry_prunes_dead_pids():
    proc = _spawn("pass")
    procreg.record("gone", proc.pid, None, procreg.log_dir() / "gone.log")
    proc.wait()
    time.sleep(0.2)
    assert procreg.tracked("gone") is None
    assert "gone" not in procreg.prune()


def test_registry_will_not_adopt_a_recycled_pid():
    """PIDs are reused. Matching only on the number would adopt a stranger."""
    proc = _spawn("pass")
    pid = proc.pid
    proc.wait()
    # Record it as if it were ours, but with a start time that cannot match anything.
    procreg._save({"demo": {"pid": pid, "port": None, "log": "x", "create_time": 1.0}})
    assert procreg.tracked("demo") is None


def test_registry_survives_a_restart(tmp_path):
    inst = procreg.launch("demo", ["python3", "-c", "import time; time.sleep(20)"], port=99)
    try:
        # Simulate a fresh process reading the on-disk registry.
        assert procreg._load()["demo"]["pid"] == inst.pid
        again = procreg.tracked("demo")
        assert again is not None and again.port == 99
    finally:
        psutil.Process(inst.pid).kill()


def test_finds_an_externally_started_process(tmp_path):
    """The common case: NVIDIA Sync's dashboard or a terminal started it, not us.

    JupyterLab really runs as `<venv>/bin/python3 <venv>/bin/jupyter-lab --port N`, so the
    executable we look for is in argv[1], not argv[0].
    """
    fake = tmp_path / "jupyter-lab"
    fake.write_text("import time; time.sleep(20)\n")
    proc = subprocess.Popen(["python3", str(fake), "--port", "11002"])
    try:
        time.sleep(0.5)
        found = procreg.find_external(str(fake), None)
        assert found is not None
        assert found.origin == "external"
        assert found.port == 11002, "the port should be read from the running command line"
    finally:
        proc.kill()
        proc.wait()


def test_find_external_returns_none_when_absent():
    assert procreg.find_external("/definitely/not/a/real/binary-xyz") is None


def test_find_external_ignores_a_process_that_merely_mentions_the_path(tmp_path):
    """Regression: a substring match over the whole command line matched any shell, editor
    or grep referencing the binary — and a false positive BLOCKS a legitimate launch."""
    fake = tmp_path / "jupyter-lab"
    fake.write_text("x\n")
    # A process that talks *about* the path without being it.
    proc = subprocess.Popen(
        ["python3", "-c", f"import time; _ = '{fake} --port 1'; time.sleep(20)"]
    )
    try:
        time.sleep(0.4)
        assert procreg.find_external(str(fake)) is None
    finally:
        proc.kill()
        proc.wait()


def test_corrupt_registry_is_ignored_not_fatal():
    procreg.registry_path().parent.mkdir(parents=True, exist_ok=True)
    procreg.registry_path().write_text("{ not json")
    assert procreg.prune() == {}
    assert procreg.tracked("anything") is None


# --- identity: port first, executable only as a secondary hint (SDD-101) -----


def test_a_bare_interpreter_is_never_matched_by_executable():
    """Live regression: an entry whose command is `/usr/bin/python3 -m http.server` matched
    an unrelated Python process from two weeks earlier, and refused to launch."""
    proc = _spawn("import time; time.sleep(20)")
    try:
        time.sleep(0.4)
        assert procreg.find_external("/usr/bin/python3", None) is None
        assert procreg.find_external("python3", None) is None
    finally:
        proc.kill()
        proc.wait()


def test_a_specific_executable_is_still_matched(tmp_path):
    """The narrowing must not break adoption of a uniquely-named program."""
    fake = tmp_path / "jupyter-lab"
    fake.write_text("import time; time.sleep(20)\n")
    proc = subprocess.Popen(["python3", str(fake)])
    try:
        time.sleep(0.5)
        assert procreg.find_external(str(fake), None) is not None
    finally:
        proc.kill()
        proc.wait()


def test_a_process_holding_the_port_but_not_ours_is_not_adopted(tmp_path):
    """It is a port conflict, not our service — reporting "already running" would send the
    operator looking in the wrong place."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        fake = tmp_path / "jupyter-lab"
        fake.write_text("x\n")
        assert procreg.find_external(str(fake), port) is None
    finally:
        sock.close()


def test_our_process_holding_the_port_is_adopted(tmp_path):
    marker = tmp_path / "myserver"
    marker.write_text(
        "import socket, sys, time\n"
        "s = socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(1)\n"
        "time.sleep(20)\n"
    )
    import socket as _socket

    probe = _socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    proc = subprocess.Popen(["python3", str(marker), str(port)])
    try:
        time.sleep(0.8)
        found = procreg.find_external(str(marker), port)
        assert found is not None, "a process on our port running our executable is ours"
        assert found.pid == proc.pid
        assert found.port == port
    finally:
        proc.kill()
        proc.wait()
