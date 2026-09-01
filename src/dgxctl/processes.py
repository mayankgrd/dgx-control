"""Launching and tracking host processes (spec R10).

Not everything worth launching is a container: NVIDIA Sync's own dashboard runs JupyterLab
from a host virtualenv, because that is what gives a notebook direct GPU access without
container plumbing. Commands come only from the catalog — never from the browser.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from dgxctl.config import state_dir
from dgxctl.schemas import RunningInstance


def registry_path() -> Path:
    return state_dir() / "processes.json"


def log_dir() -> Path:
    d = state_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load() -> dict[str, dict]:
    p = registry_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


def _alive(pid: int, started_at: float | None = None) -> bool:
    """PIDs are reused. Match the recorded start time so we never adopt a stranger."""
    try:
        proc = psutil.Process(pid)
        if started_at is not None and abs(proc.create_time() - started_at) > 2.0:
            return False
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def record(entry_id: str, pid: int, port: int | None, log_path: Path) -> None:
    data = _load()
    try:
        create_time = psutil.Process(pid).create_time()
    except psutil.Error:
        create_time = time.time()
    data[entry_id] = {
        "pid": pid,
        "port": port,
        "log": str(log_path),
        "started_at": datetime.now(UTC).isoformat(),
        "create_time": create_time,
    }
    _save(data)


def forget(entry_id: str) -> None:
    data = _load()
    if data.pop(entry_id, None) is not None:
        _save(data)


def prune() -> dict[str, dict]:
    """Drop entries whose process is gone. Returns what remains."""
    data = _load()
    live = {k: v for k, v in data.items() if _alive(v.get("pid", -1), v.get("create_time"))}
    if live != data:
        _save(live)
    return live


def tracked(entry_id: str) -> RunningInstance | None:
    rec = prune().get(entry_id)
    if rec is None:
        return None
    return RunningInstance(
        pid=rec.get("pid"),
        port=rec.get("port"),
        started_at=rec.get("started_at"),
        origin="dgxctl",
        log_path=rec.get("log"),
    )


# argv[0] values that identify nothing on their own. A catalog entry whose command starts
# with one of these cannot be recognised by its executable — every other script on the box
# shares it.
BARE_INTERPRETERS = {
    "python",
    "python3",
    "python3.10",
    "python3.11",
    "python3.12",
    "python3.13",
    "sh",
    "bash",
    "zsh",
    "node",
    "ruby",
    "perl",
    "java",
    "uv",
    "uvx",
    "env",
}


def cmdline_of(pid: int) -> list[str]:
    try:
        return psutil.Process(pid).cmdline() or []
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def find_external(executable: str, port: int | None = None) -> RunningInstance | None:
    """Find an instance started outside dgxctl.

    This is the common case, not an edge case: NVIDIA Sync's dashboard and a plain terminal
    both start JupyterLab this way, and duplicating it would be worse than useless.

    A service's real identity is its PORT. The executable is only a secondary hint, and it
    is useless when the command starts with a shared interpreter -- matching on
    `/usr/bin/python3` adopts the first unrelated Python process on the box.
    """
    target = str(Path(executable).expanduser())

    if port:
        pid = port_listener(port)
        if pid is not None:
            # Something holds the entry's port. It is our entry only if it is actually
            # running our executable; otherwise the caller must report a port conflict.
            if target in cmdline_of(pid):
                proc_start = None
                try:
                    proc_start = datetime.fromtimestamp(
                        psutil.Process(pid).create_time(), UTC
                    ).isoformat()
                except psutil.Error:
                    pass
                return RunningInstance(pid=pid, port=port, started_at=proc_start, origin="external")
            return None
        if _port_bound(port):
            # In use, but the owner is another user's process we cannot inspect.
            return RunningInstance(pid=None, port=port, origin="external")

    if Path(target).name in BARE_INTERPRETERS:
        return None
    return _find_by_executable(target, port)


def _port_bound(port: int) -> bool:
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                return True
    except (psutil.AccessDenied, OSError):
        return False
    return False


def _find_by_executable(executable: str, port: int | None = None) -> RunningInstance | None:
    target = str(Path(executable).expanduser())
    own = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            if proc.info["pid"] == own:
                continue
            cmdline = proc.info.get("cmdline") or []
            if not cmdline:
                continue
            # Match argv elements EXACTLY. A substring search over the whole command line
            # matches any shell, editor or grep that merely mentions the path, and a false
            # positive here blocks a legitimate launch by claiming it is already running.
            # An interpreted launch puts the script in argv[1], so check every element.
            if target in cmdline:
                found_port = port
                if found_port is None:
                    for i, part in enumerate(cmdline):
                        if part == "--port" and i + 1 < len(cmdline):
                            candidate = cmdline[i + 1]
                            found_port = int(candidate) if candidate.isdigit() else None
                return RunningInstance(
                    pid=proc.info["pid"],
                    port=found_port,
                    started_at=datetime.fromtimestamp(
                        proc.info.get("create_time") or time.time(), UTC
                    ).isoformat(),
                    origin="external",
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    return None


def port_listener(port: int) -> int | None:
    """PID listening on a port, if we can see it."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                return conn.pid
    except (psutil.AccessDenied, OSError):
        return None
    return None


def launch(
    entry_id: str,
    argv: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    port: int | None = None,
) -> RunningInstance:
    """Spawn detached, so the process outlives the request that started it."""
    if isinstance(argv, str):
        raise TypeError("launch requires an argument list, not a shell string (spec S8)")
    log_path = log_dir() / f"{entry_id}.log"
    handle = log_path.open("ab")
    handle.write(
        f"\n=== dgxctl launch {datetime.now(UTC).isoformat()}: {' '.join(argv)} ===\n".encode()
    )
    handle.flush()
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.Popen(  # noqa: S603
        argv,
        cwd=cwd,
        env=full_env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach: not killed when dgxctl restarts
        shell=False,
    )
    record(entry_id, proc.pid, port, log_path)
    return RunningInstance(
        pid=proc.pid,
        port=port,
        started_at=datetime.now(UTC).isoformat(),
        origin="dgxctl",
        log_path=str(log_path),
    )


def read_log(entry_id: str, tail: int = 200) -> str:
    path = log_dir() / f"{entry_id}.log"
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-tail:])
