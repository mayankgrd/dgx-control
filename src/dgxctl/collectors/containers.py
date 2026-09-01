"""Docker containers with resource usage and — critically — honest port exposure."""

from __future__ import annotations

import asyncio

from dgxctl.collectors.base import Collector
from dgxctl.collectors.util import classify_exposure
from dgxctl.docker_client import get_client, get_error
from dgxctl.schemas import ContainerInfo, ContainerSection, PortBinding

DGXCTL_LABEL = "dgxctl.entry"
DGXCTL_GPU_UTIL_LABEL = "dgxctl.gpu_memory_utilization"


def parse_ports(ports: dict | None, tailnet_ips: set[str] | None = None) -> list[PortBinding]:
    """Parse NetworkSettings.Ports.

    The load-bearing case: Docker reports a wildcard publish as HostIp "0.0.0.0" and an
    empty HostIp ALSO means all interfaces. Reading empty as loopback would invert the
    entire safety signal this tool exists to provide.
    """
    out: list[PortBinding] = []
    for key, bindings in (ports or {}).items():
        port_s, _, proto = key.partition("/")
        try:
            cport = int(port_s)
        except ValueError:
            continue
        if not bindings:  # exposed by the image but not published to the host
            out.append(
                PortBinding(container_port=cport, protocol=proto or "tcp", exposure="unknown")
            )
            continue
        for b in bindings:
            host_ip = b.get("HostIp")
            if host_ip is None or host_ip == "":
                host_ip = "0.0.0.0"  # noqa: S104 — empty means ALL, not unknown
            try:
                hport = int(b.get("HostPort") or 0) or None
            except (TypeError, ValueError):
                hport = None
            out.append(
                PortBinding(
                    container_port=cport,
                    protocol=proto or "tcp",
                    host_ip=host_ip,
                    host_port=hport,
                    exposure=classify_exposure(host_ip, tailnet_ips),
                )
            )
    return out


def compute_cpu_percent(stats: dict) -> float | None:
    try:
        cpu, pre = stats["cpu_stats"], stats["precpu_stats"]
        delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        if sys_delta <= 0 or delta < 0:
            return None
        ncpu = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or []) or 1
        return round((delta / sys_delta) * ncpu * 100.0, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _blkio_totals(stats: dict) -> tuple[int, int]:
    read = write = 0
    for e in (stats.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []:
        op = (e.get("op") or "").lower()
        if op == "read":
            read += e.get("value", 0)
        elif op == "write":
            write += e.get("value", 0)
    return read, write


def safe_image(container):
    """`container.image` performs a registry lookup that raises ImageNotFound when the
    image has been removed out from under a running container. `getattr(c, "image", None)`
    does not help: the default only applies to AttributeError, not to a raising property."""
    try:
        return container.image
    except Exception:  # noqa: BLE001 -- a missing image is normal, not a collector failure
        return None


def _image_name(container, cfg: dict) -> str:
    image = safe_image(container)
    if image is not None and getattr(image, "tags", None):
        return image.tags[0]
    return cfg.get("Image") or (image.id if image is not None else "?")


class ContainerCollector(Collector):
    name = "containers"
    interval = 5.0
    timeout = 25.0

    def __init__(self, tailnet_ips: set[str] | None = None) -> None:
        super().__init__()
        self.tailnet_ips = tailnet_ips or set()

    async def available(self) -> bool:
        client = await asyncio.to_thread(get_client)
        if client is None:
            self.mark_unavailable(f"Docker not reachable ({get_error()})")
            return False
        return True

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    def _collect_sync(self) -> ContainerSection:
        client = get_client()
        section = ContainerSection()
        containers = client.containers.list(all=True)
        for c in containers:
            attrs = c.attrs
            state = attrs.get("State", {}) or {}
            cfg = attrs.get("Config", {}) or {}
            labels = cfg.get("Labels") or {}
            info = ContainerInfo(
                id=c.id,
                name=c.name,
                image=_image_name(c, cfg),
                status=c.status,
                state=state.get("Status", c.status),
                created_at=attrs.get("Created"),
                started_at=state.get("StartedAt"),
                restart_policy=((attrs.get("HostConfig") or {}).get("RestartPolicy") or {}).get(
                    "Name"
                ),
                restart_count=attrs.get("RestartCount", 0) or 0,
                ports=parse_ports(
                    (attrs.get("NetworkSettings") or {}).get("Ports"), self.tailnet_ips
                ),
                launched_by_dgxctl=DGXCTL_LABEL in labels,
            )
            if DGXCTL_GPU_UTIL_LABEL in labels:
                try:
                    info.gpu_memory_utilization = float(labels[DGXCTL_GPU_UTIL_LABEL])
                except ValueError:
                    pass
            if c.status == "running":
                section.running += 1
                try:
                    stats = c.stats(stream=False)
                    info.cpu_percent = compute_cpu_percent(stats)
                    mem = stats.get("memory_stats") or {}
                    info.memory_bytes = mem.get("usage")
                    info.memory_limit_bytes = mem.get("limit")
                    nets = stats.get("networks") or {}
                    if nets:
                        info.net_rx_bytes = sum(n.get("rx_bytes", 0) for n in nets.values())
                        info.net_tx_bytes = sum(n.get("tx_bytes", 0) for n in nets.values())
                    info.block_read_bytes, info.block_write_bytes = _blkio_totals(stats)
                except Exception:  # noqa: BLE001
                    section.stats_available = False
            else:
                section.stopped += 1
            section.containers.append(info)
        section.containers.sort(key=lambda x: (x.state != "running", x.name))
        return section
