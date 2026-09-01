"""Schedules collectors on independent intervals and federates remote nodes."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

from dgxctl.collectors.base import Collector
from dgxctl.config import RemoteNode, Settings
from dgxctl.history import HistoryStore
from dgxctl.schemas import Envelope, NodeInfo, Status
from dgxctl.store import SnapshotStore

log = logging.getLogger(__name__)

HISTORY_METRICS = (
    "gpu.utilization",
    "gpu.memory_percent",
    "memory.used_percent",
    "containers.running",
)


class Poller:
    """One task per collector. A slow collector never delays a fast one."""

    def __init__(
        self,
        collectors: list[Collector],
        store: SnapshotStore,
        history: HistoryStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.collectors = collectors
        self.store = store
        self.history = history
        self.settings = settings
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self._stopping.clear()
        for c in self.collectors:
            self._tasks.append(asyncio.create_task(self._loop(c), name=f"collector:{c.name}"))
        if self.history is not None:
            self._tasks.append(asyncio.create_task(self._prune_loop(), name="history-prune"))
        for node in self.settings.nodes if self.settings else []:
            self._tasks.append(
                asyncio.create_task(self._remote_loop(node), name=f"remote:{node.id}")
            )

    async def stop(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()

    async def run_once(self) -> None:
        """Run every collector once. Used by tests and by `dgxctl doctor`."""
        for c in self.collectors:
            env = await c.run()
            await self.store.put(c.name, env)
            self._record(env, c.name)

    async def _await_dependencies(self, collector: Collector, limit: float = 60.0) -> None:
        """Hold a dependent collector's first run until its sources have reported once."""
        waited = 0.0
        step = 0.25
        while waited < limit and not self._stopping.is_set():
            if all(self.store.section(dep) is not None for dep in collector.depends_on):
                return
            await asyncio.sleep(step)
            waited += step
        if waited >= limit:
            log.warning(
                "%s starting without %s; those sections never reported",
                collector.name,
                ", ".join(d for d in collector.depends_on if self.store.section(d) is None),
            )

    async def _loop(self, collector: Collector) -> None:
        if collector.depends_on:
            await self._await_dependencies(collector)
        while not self._stopping.is_set():
            try:
                env = await collector.run()
                await self.store.put(collector.name, env)
                self._record(env, collector.name)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — the poller outlives any collector bug
                log.exception("poller loop error in %s", collector.name)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=collector.interval)
            except TimeoutError:
                pass

    async def _prune_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=300)
                return
            except TimeoutError:
                pass
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.history.prune)

    def _record(self, env: Envelope, name: str) -> None:
        if self.history is None or env.status != Status.ok or not isinstance(env.data, dict):
            return
        metrics: dict[str, float] = {}
        data = env.data
        if name == "gpu":
            devices = data.get("devices") or []
            if devices:
                if devices[0].get("utilization_percent") is not None:
                    metrics["gpu.utilization"] = devices[0]["utilization_percent"]
            mem = data.get("memory") or {}
            if mem.get("total_bytes"):
                metrics["memory.used_percent"] = 100.0 * mem["used_bytes"] / mem["total_bytes"]
                if mem.get("gpu_reserved_bytes"):
                    metrics["gpu.memory_percent"] = (
                        100.0 * mem["gpu_reserved_bytes"] / mem["total_bytes"]
                    )
        elif name == "containers":
            metrics["containers.running"] = float(data.get("running", 0))
        if metrics:
            with contextlib.suppress(Exception):
                self.history.record_many(metrics, node=self.store.local_id)

    # --- multi-node federation (architecture.md section 13) -----------------

    async def _remote_loop(self, node: RemoteNode) -> None:
        interval = self.settings.intervals.remote if self.settings else 10.0
        while not self._stopping.is_set():
            await self._poll_remote(node)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def _poll_remote(self, node: RemoteNode) -> None:
        info = NodeInfo(id=node.id, name=node.name or node.id, kind="remote")
        headers = {}
        token = node.resolve_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=node.verify_tls) as client:
                resp = await client.get(f"{node.url.rstrip('/')}/api/snapshot", headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            info.reachable = False
            info.error = f"{type(exc).__name__}: {exc}"[:200]
            await self.store.put_node(info)
            return
        sections = {k: Envelope(**v) for k, v in (payload.get("sections") or {}).items()}
        await self.store.put_node(info)
        await self.store.put_many(sections, node_id=node.id)
