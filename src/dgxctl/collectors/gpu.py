"""GPU telemetry via NVML, with the unified-memory reality of GB10 handled explicitly."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import psutil

from dgxctl.collectors.base import Collector
from dgxctl.schemas import GpuDevice, GpuSection, MemoryPool

try:  # nvidia-ml-py exposes the module as `pynvml`
    import pynvml
except ImportError:  # pragma: no cover
    pynvml = None


def read_meminfo(path: str = "/proc/meminfo") -> dict[str, int]:
    """Bytes keyed by MemTotal / MemAvailable / MemFree / Cached."""
    out: dict[str, int] = {}
    text = Path(path).read_text()
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
        if m:
            out[m.group(1)] = int(m.group(2)) * 1024
    return out


def _decode(v) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


class GpuCollector(Collector):
    name = "gpu"
    interval = 2.0
    timeout = 10.0

    def __init__(self) -> None:
        super().__init__()
        self._inited = False

    async def available(self) -> bool:
        if pynvml is None:
            self.mark_unavailable("nvidia-ml-py not installed")
            return False
        try:
            await asyncio.to_thread(pynvml.nvmlInit)
            self._inited = True
            return True
        except Exception as exc:  # noqa: BLE001
            self.mark_unavailable(f"NVML unavailable: {exc}")
            return False

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    @staticmethod
    def _fill_metrics(dev: GpuDevice, handle) -> None:
        """Each query is independently optional: GB10 supports some and not others."""

        def attempt(attr: str, fn) -> None:
            try:
                setattr(dev, attr, float(fn(handle)))
            except Exception:  # noqa: BLE001 -- an unsupported query is not an error
                return

        attempt("utilization_percent", lambda h: pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        attempt(
            "memory_utilization_percent",
            lambda h: pynvml.nvmlDeviceGetUtilizationRates(h).memory,
        )
        attempt("temperature_c", lambda h: pynvml.nvmlDeviceGetTemperature(h, 0))
        attempt("power_w", lambda h: pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0)
        attempt("power_limit_w", lambda h: pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0)
        attempt("sm_clock_mhz", lambda h: pynvml.nvmlDeviceGetClockInfo(h, 0))

    def _collect_sync(self) -> GpuSection:
        section = GpuSection()
        try:
            section.driver_version = _decode(pynvml.nvmlSystemGetDriverVersion())
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            raw = pynvml.nvmlSystemGetCudaDriverVersion()
            section.cuda_version = f"{raw // 1000}.{(raw % 1000) // 10}"
        except Exception:  # noqa: BLE001, S110
            pass

        mem = read_meminfo()
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        cached = mem.get("Cached", 0)

        count = pynvml.nvmlDeviceGetCount()
        gpu_reserved = 0
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            dev = GpuDevice(index=i, name=_decode(pynvml.nvmlDeviceGetName(h)))
            self._fill_metrics(dev, h)

            # GB10 raises NVMLError_NotSupported here: memory is unified, so there is no
            # separate GPU pool to report. Fall back to the system pool rather than zeroing.
            try:
                info = pynvml.nvmlDeviceGetMemoryInfo(h)
                if info.total:
                    dev.memory_total_bytes = int(info.total)
                    dev.memory_used_bytes = int(info.used)
                    dev.memory_source = "nvml"
            except Exception:  # noqa: BLE001
                dev.memory_total_bytes = total
                dev.memory_used_bytes = max(total - available, 0)
                dev.memory_source = "system"

            try:
                for p in pynvml.nvmlDeviceGetComputeRunningProcesses(h):
                    if p.usedGpuMemory:
                        gpu_reserved += int(p.usedGpuMemory)
            except Exception:  # noqa: BLE001, S110
                pass
            section.devices.append(dev)

        unified = any(d.memory_source == "system" for d in section.devices)
        vm = psutil.virtual_memory()
        section.memory = MemoryPool(
            unified=unified,
            total_bytes=total or vm.total,
            used_bytes=(total - available) if total else vm.used,
            available_bytes=available or vm.available,
            cached_bytes=cached,
            gpu_reserved_bytes=gpu_reserved or None,
        )
        return section
