"""The only mutation path. Gated, and never silent (spec S5, S7)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

import psutil

from dgxctl import processes as procreg
from dgxctl.catalog import (
    CatalogError,
    build_process_spec,
    build_run_spec,
    check_memory_budget,
    find_running,
    load_catalog,
)
from dgxctl.config import Settings, state_dir
from dgxctl.docker_client import get_client
from dgxctl.schemas import ActionLogEntry, ActionResult

KILL_GRACE_SECONDS = 5.0


class ActionDenied(PermissionError):
    pass


def is_kernel_thread(proc: psutil.Process) -> bool:
    """An empty cmdline is NOT sufficient evidence of a kernel thread.

    A userspace process caught between fork and execve has an empty cmdline too, and so
    does a zombie. Refusing on that alone produces false refusals against perfectly real
    processes — observed on a DGX Spark, where the window is wide enough to hit routinely.
    On Linux every kernel thread descends from kthreadd (pid 2); that is the real signal.
    """
    try:
        if proc.cmdline():
            return False
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    if not sys.platform.startswith("linux"):
        # Kernel threads are a Linux concept. Elsewhere an empty cmdline means "we could
        # not read it", and the ownership check is what protects system processes.
        return False
    try:
        return proc.pid == 2 or proc.ppid() == 2
    except psutil.Error:
        return True


class ActionRunner:
    def __init__(self, settings: Settings, log_path: Path | None = None) -> None:
        self.settings = settings
        self.log_path = log_path or (state_dir() / "actions.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Records who asked for what. Not world-readable.
        self.log_path.touch(exist_ok=True)
        self.log_path.chmod(0o600)

    def _require_control(self) -> None:
        if not self.settings.control_enabled:
            raise ActionDenied(
                "Control actions are disabled. Set control_enabled = true in "
                f"{Path.home() / '.config/dgxctl/config.toml'} and restart."
            )

    def _log(self, identity: str, action: str, target: str, ok: bool, message: str) -> None:
        entry = ActionLogEntry(
            ts=datetime.now(UTC).isoformat(),
            identity=identity,
            action=action,
            target=target,
            ok=ok,
            message=message[:500],
        )
        with self.log_path.open("a") as fh:  # append-only
            fh.write(entry.model_dump_json() + "\n")

    def read_log(self, limit: int = 200) -> list[ActionLogEntry]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text().splitlines()[-limit:]
        out = []
        for line in reversed(lines):
            try:
                out.append(ActionLogEntry(**json.loads(line)))
            except (ValueError, TypeError):
                continue
        return out

    async def run(self, action: str, target: str, identity: str, **kwargs) -> ActionResult:
        self._require_control()
        try:
            result = await getattr(self, f"_do_{action}")(target, **kwargs)
        except ActionDenied:
            raise
        except Exception as exc:  # noqa: BLE001 — failures are logged, never swallowed
            self._log(identity, action, target, False, f"{type(exc).__name__}: {exc}")
            return ActionResult(
                ok=False, action=action, target=target, message=f"{type(exc).__name__}: {exc}"
            )
        self._log(identity, action, target, result.ok, result.message)
        return result

    # --- container lifecycle (reversible only) -----------------------------

    async def _container(self, name: str):
        client = get_client()
        if client is None:
            raise RuntimeError("Docker is not reachable")
        return await asyncio.to_thread(client.containers.get, name)

    async def _do_start(self, target: str) -> ActionResult:
        c = await self._container(target)
        await asyncio.to_thread(c.start)
        return ActionResult(ok=True, action="start", target=target, message=f"started {c.name}")

    async def _do_stop(self, target: str, timeout: int = 15) -> ActionResult:
        c = await self._container(target)
        await asyncio.to_thread(c.stop, timeout=timeout)
        return ActionResult(ok=True, action="stop", target=target, message=f"stopped {c.name}")

    async def _do_restart(self, target: str, timeout: int = 15) -> ActionResult:
        c = await self._container(target)
        await asyncio.to_thread(c.restart, timeout=timeout)
        return ActionResult(ok=True, action="restart", target=target, message=f"restarted {c.name}")

    # --- catalog launch ----------------------------------------------------

    async def _do_launch(self, target: str, params: dict | None = None) -> ActionResult:
        entries = {e.id: e for e in load_catalog()}
        entry = entries.get(target)
        if entry is None:
            raise CatalogError(f"unknown catalog entry {target!r}")

        existing = await asyncio.to_thread(find_running, entry)
        if existing is not None:
            where = f"pid {existing.pid}" if existing.pid else f"container {existing.container}"
            origin = "already running" if existing.origin == "dgxctl" else "started outside dgxctl"
            return ActionResult(
                ok=False,
                action="launch",
                target=target,
                message=(
                    f"{entry.name} is {origin} ({where}"
                    f"{f' on port {existing.port}' if existing.port else ''}). "
                    f"Stop it first, or use the running instance."
                ),
                detail={"running": existing.model_dump()},
            )

        if entry.kind == "process":
            conflict = await asyncio.to_thread(self._port_conflict, entry, params or {})
            if conflict is not None:
                return conflict
            return await self._launch_process(entry, params or {})

        running = await asyncio.to_thread(self._running_gpu_reservations)
        ok, why = check_memory_budget(entry, [v for _, v in running])
        if not ok:
            detail = {"running": [{"name": n, "gpu_memory_utilization": v} for n, v in running]}
            return ActionResult(
                ok=False, action="launch", target=target, message=why, detail=detail
            )

        built = build_run_spec(entry, params or {})
        client = get_client()
        if client is None:
            raise RuntimeError("Docker is not reachable")
        spec = dict(built["spec"])
        name = f"dgxctl-{entry.id}-{built['port']}"
        spec["name"] = name
        container = await asyncio.to_thread(client.containers.run, **spec)
        url = f"http://{built['bind']}:{built['port']}" if built["port"] else None
        return ActionResult(
            ok=True,
            action="launch",
            target=target,
            message=f"launched {name} on {built['bind']}:{built['port']}",
            detail={"container": container.name, "url": url, "resolved": built["resolved"]},
        )

    @staticmethod
    def _port_conflict(entry, params: dict) -> ActionResult | None:
        """Someone else on the entry's port is a different failure from "already running",
        and saying the wrong one sends you looking in the wrong place."""
        port = int(params.get("port") or entry.port or 0)
        if not port:
            return None
        pid = procreg.port_listener(port)
        if pid is None:
            return None
        name = " ".join(procreg.cmdline_of(pid))[:120] or f"pid {pid}"
        return ActionResult(
            ok=False,
            action="launch",
            target=entry.id,
            message=(
                f"Port {port} is already in use by pid {pid} ({name}), which is not "
                f"{entry.name}. Choose another port, or stop that process first."
            ),
            detail={"port": port, "pid": pid},
        )

    async def _launch_process(self, entry, params: dict) -> ActionResult:
        built = await asyncio.to_thread(build_process_spec, entry, params)
        instance = await asyncio.to_thread(
            procreg.launch, entry.id, built["argv"], built["cwd"], built["env"], built["port"]
        )
        # Give it a moment to fail loudly rather than reporting a success that already died.
        await asyncio.sleep(1.5)
        if not psutil.pid_exists(instance.pid):
            tail = procreg.read_log(entry.id, 15)
            procreg.forget(entry.id)
            return ActionResult(
                ok=False,
                action="launch",
                target=entry.id,
                message=f"{entry.name} exited immediately. Last log lines:\n{tail}",
            )
        return ActionResult(
            ok=True,
            action="launch",
            target=entry.id,
            message=f"launched {entry.name} (pid {instance.pid}) on "
            f"{built['bind']}:{built['port']}",
            detail={"instance": instance.model_dump(), "resolved": built["resolved"]},
        )

    async def _do_launch_service(self, target: str) -> ActionResult:
        """Launch a service declared in config (spec R12.3)."""
        decl = next((d for d in self.settings.services if d.id == target), None)
        if decl is None:
            raise CatalogError(f"no declared service {target!r}")
        if not decl.launch:
            raise CatalogError(f"declared service {target!r} has no launch command")
        instance = await asyncio.to_thread(
            procreg.launch, f"service:{decl.id}", list(decl.launch), None, None, decl.port
        )
        await asyncio.sleep(1.5)
        if not psutil.pid_exists(instance.pid):
            tail = procreg.read_log(f"service:{decl.id}", 15)
            procreg.forget(f"service:{decl.id}")
            return ActionResult(
                ok=False,
                action="launch_service",
                target=target,
                message=f"{decl.name or decl.id} exited immediately. Last log lines:\n{tail}",
            )
        return ActionResult(
            ok=True,
            action="launch_service",
            target=target,
            message=f"launched {decl.name or decl.id} (pid {instance.pid}); "
            f"it may take a moment to listen on port {decl.port}",
            detail={"instance": instance.model_dump()},
        )

    async def _do_stop_process(self, target: str) -> ActionResult:
        instance = procreg.tracked(target)
        if instance is None or not instance.pid:
            raise CatalogError(f"no dgxctl-launched process for entry {target!r}")
        self.assert_killable(instance.pid)
        proc = psutil.Process(instance.pid)
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, KILL_GRACE_SECONDS)
        except psutil.TimeoutExpired:
            os.kill(instance.pid, signal.SIGKILL)
        procreg.forget(target)
        return ActionResult(
            ok=True,
            action="stop_process",
            target=target,
            message=f"stopped {target} (pid {instance.pid})",
        )

    def _running_gpu_reservations(self) -> list[tuple[str, float]]:
        client = get_client()
        if client is None:
            return []
        out = []
        for c in client.containers.list():
            labels = (c.attrs.get("Config") or {}).get("Labels") or {}
            val = labels.get("dgxctl.gpu_memory_utilization")
            if val:
                try:
                    out.append((c.name, float(val)))
                    continue
                except ValueError:
                    pass
            cmd = " ".join((c.attrs.get("Config") or {}).get("Cmd") or [])
            if "--gpu-memory-utilization" in cmd:
                parts = cmd.split()
                try:
                    out.append((c.name, float(parts[parts.index("--gpu-memory-utilization") + 1])))
                except (ValueError, IndexError):
                    pass
        return out

    # --- process kill (spec S6) --------------------------------------------

    async def _do_kill(self, target: str) -> ActionResult:
        pid = int(target)
        self.assert_killable(pid)
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, KILL_GRACE_SECONDS)
            return ActionResult(
                ok=True, action="kill", target=target, message=f"pid {pid} terminated"
            )
        except psutil.TimeoutExpired:
            os.kill(pid, signal.SIGKILL)
            return ActionResult(
                ok=True,
                action="kill",
                target=target,
                message=f"pid {pid} did not exit; sent SIGKILL",
            )

    @staticmethod
    def assert_killable(pid: int, own_pid: int | None = None) -> None:
        """Refusals state their reason — the UI surfaces it verbatim (FE-2.3)."""
        own_pid = own_pid if own_pid is not None else os.getpid()
        if pid <= 1:
            raise ActionDenied(f"refusing to kill pid {pid}: pid 1 and below are never killable")
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess as exc:
            raise ActionDenied(f"pid {pid} does not exist") from exc
        try:
            proc.cmdline()
        except psutil.AccessDenied as exc:
            raise ActionDenied(f"refusing to kill pid {pid}: not accessible to this user") from exc
        if is_kernel_thread(proc):
            raise ActionDenied(f"refusing to kill pid {pid}: kernel thread")
        try:
            if proc.username() != psutil.Process(own_pid).username():
                raise ActionDenied(
                    f"refusing to kill pid {pid}: owned by {proc.username()!r}, not by this service"
                )
        except psutil.AccessDenied as exc:
            raise ActionDenied(f"refusing to kill pid {pid}: cannot verify ownership") from exc
        if pid == own_pid:
            raise ActionDenied("refusing to kill dgxctl itself")
        # Ancestors only. A CHILD of dgxctl is by definition a short-lived helper we
        # spawned (`ss`, `du`); refusing those adds no safety and causes false refusals.
        try:
            for parent in psutil.Process(own_pid).parents():
                if parent.pid == pid:
                    raise ActionDenied(
                        f"refusing to kill pid {pid}: it is an ancestor of dgxctl "
                        f"({parent.name()}); killing it would take dgxctl down with it"
                    )
        except psutil.NoSuchProcess:
            pass
