from __future__ import annotations

import asyncio
import time
from pathlib import Path

import psutil

from dgxctl.collectors.base import Collector, run_cmd
from dgxctl.docker_client import get_client
from dgxctl.schemas import DiskSection, DockerUsage, FilesystemInfo, SizedRoot

PSEUDO_FS = {
    "tmpfs",
    "devtmpfs",
    "squashfs",
    "overlay",
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "devpts",
    "autofs",
    "efivarfs",
    "ramfs",
    "fuse.snapfuse",
    "fuse.gvfsd-fuse",
    "nsfs",
}


class DiskCollector(Collector):
    name = "disk"
    interval = 60.0
    timeout = 120.0

    def __init__(self, roots: list[str] | None = None, warn_percent: float = 85.0) -> None:
        super().__init__()
        self.roots = roots or []
        self.warn_percent = warn_percent
        self._du_cache: dict[str, tuple[float, int]] = {}
        self._du_ttl = 900.0  # `du` over a 150 GB cache is expensive; cache hard.

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    def _du(self, path: Path) -> int:
        key = str(path)
        now = time.time()
        hit = self._du_cache.get(key)
        if hit and now - hit[0] < self._du_ttl:
            return hit[1]
        out = run_cmd(["du", "-sb", str(path)], timeout=110.0)
        size = int(out.split()[0])
        self._du_cache[key] = (now, size)
        return size

    def _collect_sync(self) -> DiskSection:
        section = DiskSection()
        seen: set[str] = set()
        for part in psutil.disk_partitions(all=False):
            if part.fstype in PSEUDO_FS or not part.fstype:
                continue
            if part.device in seen:  # same device mounted twice
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            seen.add(part.device)
            section.filesystems.append(
                FilesystemInfo(
                    mountpoint=part.mountpoint,
                    device=part.device,
                    fstype=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=usage.percent,
                    over_threshold=usage.percent >= self.warn_percent,
                )
            )
        section.filesystems.sort(key=lambda f: -f.total_bytes)

        roots = list(self.roots)
        client = get_client()
        if client is not None:
            try:
                root = client.info().get("DockerRootDir")
                if root and root not in roots:
                    roots.append(root)
            except Exception:  # noqa: BLE001, S110
                pass

        for r in roots:
            p = Path(r).expanduser()
            entry = SizedRoot(path=str(p), label=p.name or str(p))
            if not p.exists():
                entry.error = "does not exist"
            else:
                try:
                    entry.size_bytes = self._du(p)
                except Exception as exc:  # noqa: BLE001 -- one bad root cannot fail the section
                    entry.error = str(exc)[:120]
            section.sized_roots.append(entry)
        section.sized_roots.sort(key=lambda s: -(s.size_bytes or 0))

        if client is not None:
            try:
                df = client.df()
                usage = DockerUsage()
                imgs = df.get("Images") or []
                usage.images_bytes = sum(i.get("Size", 0) or 0 for i in imgs)
                usage.containers_bytes = sum(
                    c.get("SizeRw", 0) or 0 for c in (df.get("Containers") or [])
                )
                usage.volumes_bytes = sum(
                    (v.get("UsageData") or {}).get("Size", 0) or 0
                    for v in (df.get("Volumes") or [])
                )
                usage.build_cache_bytes = sum(
                    b.get("Size", 0) or 0 for b in (df.get("BuildCache") or [])
                )
                unused = sum(
                    i.get("Size", 0) or 0 for i in imgs if not (i.get("Containers", 0) or 0) > 0
                )
                usage.reclaimable_bytes = unused + usage.build_cache_bytes
                section.docker = usage
            except Exception:  # noqa: BLE001, S110
                pass
        return section
