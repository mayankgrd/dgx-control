"""Processes, GPU attribution, and the PID-namespace seam.

NVML reports HOST-namespace PIDs, and the GPU process is often a CHILD of the container's
main process (on a live DGX Spark: container State.Pid 725512, GPU pid 726116). So
attribution goes through /proc/<gpu_pid>/cgroup, never by matching the container's own PID.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import psutil

from dgxctl.collectors.base import Collector
from dgxctl.collectors.util import container_id_from_cgroup
from dgxctl.schemas import ProcessInfo, ProcessSection

try:
    import pynvml
except ImportError:  # pragma: no cover
    pynvml = None


def container_for_pid(pid: int, proc_root: str = "/proc") -> str | None:
    try:
        return container_id_from_cgroup(Path(f"{proc_root}/{pid}/cgroup").read_text())
    except (OSError, PermissionError):
        return None


def gpu_processes_from_nvml() -> dict[int, int]:
    """{pid: bytes}. Works on GB10 even though nvmlDeviceGetMemoryInfo does not."""
    out: dict[int, int] = {}
    if pynvml is None:
        return out
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            for fn in (
                pynvml.nvmlDeviceGetComputeRunningProcesses,
                getattr(pynvml, "nvmlDeviceGetGraphicsRunningProcesses", None),
            ):
                if fn is None:
                    continue
                try:
                    for p in fn(h):
                        if p.usedGpuMemory:
                            out[p.pid] = max(out.get(p.pid, 0), int(p.usedGpuMemory))
                        else:
                            out.setdefault(p.pid, 0)
                except Exception:  # noqa: BLE001, S110
                    pass
    except Exception:  # noqa: BLE001, S110
        pass
    return out


class ProcessCollector(Collector):
    name = "processes"
    interval = 5.0
    timeout = 20.0
    depends_on = ("containers",)

    def __init__(self, container_lookup=None, proc_root: str = "/proc") -> None:
        super().__init__()
        self._container_lookup = container_lookup or (lambda _cid: None)
        self._proc_root = proc_root

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    def _build(self, proc: psutil.Process, gpu_mem: int | None) -> ProcessInfo | None:
        try:
            with proc.oneshot():
                info = ProcessInfo(
                    pid=proc.pid,
                    name=proc.name(),
                    cmdline=" ".join(proc.cmdline())[:512],
                    username=proc.username(),
                    cpu_percent=proc.cpu_percent(None),
                    rss_bytes=proc.memory_info().rss,
                    gpu_memory_bytes=gpu_mem,
                    started_at=datetime.fromtimestamp(proc.create_time(), UTC).isoformat(),
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
        cid = container_for_pid(proc.pid, self._proc_root)
        if cid:
            info.container_id = cid[:12]
            info.container_name = self._container_lookup(cid)
        return info

    def _collect_sync(self) -> ProcessSection:
        gpu_map = gpu_processes_from_nvml()
        section = ProcessSection()
        cpu_candidates: list[ProcessInfo] = []
        count = 0
        for proc in psutil.process_iter(["pid"]):
            count += 1
            if proc.pid in gpu_map:
                continue
            try:
                cpu = proc.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if cpu and cpu > 1.0:
                built = self._build(proc, None)
                if built:
                    cpu_candidates.append(built)
        section.total_processes = count

        for pid, mem in gpu_map.items():
            try:
                built = self._build(psutil.Process(pid), mem)
            except psutil.NoSuchProcess:  # exited between NVML and /proc — normal
                continue
            if built:
                section.gpu_processes.append(built)

        section.gpu_processes.sort(key=lambda p: -(p.gpu_memory_bytes or 0))
        cpu_candidates.sort(key=lambda p: -(p.cpu_percent or 0))
        section.top_cpu = cpu_candidates[:15]
        return section
