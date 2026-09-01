"""Python environments and their GPU capability.

torch is detected from on-disk distribution metadata. Importing it would allocate a CUDA
context inside the monitoring process — the exact perturbation spec N1 forbids.
"""

from __future__ import annotations

import asyncio
import configparser
import re
from pathlib import Path

from dgxctl.collectors.base import Collector
from dgxctl.schemas import PyEnvInfo, PyEnvSection

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".cache", "sandboxes", ".venv-cache"}


# torch/version.py really looks like:  cuda: Optional[str] = '13.0'
# A naive `cuda\s*[:=]` never matches, because of the type annotation in between.
_CUDA_RE = re.compile(r"^\s*cuda\s*(?::[^=]*)?=\s*['\"]([^'\"]+)['\"]", re.M)


def torch_from_site_packages(site: Path) -> tuple[str | None, bool]:
    """Returns (version, gpu_capable) WITHOUT importing torch.

    Importing it inside the monitoring process would allocate a CUDA context — the exact
    perturbation spec N1 forbids — so both facts are read off disk.
    """
    for dist in sorted(site.glob("torch-*.dist-info")):
        # "torch-2.9.0+cu130.dist-info" -> "2.9.0+cu130": strip the suffix BEFORE splitting,
        # or the version keeps a trailing ".dist".
        stem = dist.name.removesuffix(".dist-info")
        version = stem.split("-", 1)[1] if "-" in stem else None

        # A local-version tag like "+cu130" is conclusive on its own.
        gpu = bool(re.search(r"\+cu\d+", version or ""))
        version_py = site / "torch" / "version.py"
        if not gpu and version_py.exists():
            try:
                m = _CUDA_RE.search(version_py.read_text())
                gpu = bool(m and m.group(1) and m.group(1) != "None")
            except OSError:
                pass
        return version, gpu
    return None, False


class PyEnvCollector(Collector):
    name = "pyenvs"
    interval = 300.0
    timeout = 120.0

    def __init__(self, roots: list[str] | None = None, max_depth: int = 4) -> None:
        super().__init__()
        self.roots = [Path(r).expanduser() for r in (roots or [])]
        self.max_depth = max_depth

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    def _walk(self, root: Path, depth: int, out: list[Path]) -> None:
        if depth > self.max_depth or len(out) > 200:
            return
        try:
            entries = list(root.iterdir())
        except (OSError, PermissionError):
            return
        for e in entries:
            # is_dir()/exists() stat the path and raise PermissionError on directories the
            # service user cannot read -- common under $HOME. One unreadable directory must
            # not fail the whole collector.
            try:
                if not e.is_dir() or e.is_symlink() or e.name in SKIP_DIRS:
                    continue
                is_env = (e / "pyvenv.cfg").exists() or (e / "conda-meta").is_dir()
            except (OSError, PermissionError):
                continue
            if is_env:
                out.append(e)
                continue
            self._walk(e, depth + 1, out)

    def _collect_sync(self) -> PyEnvSection:
        section = PyEnvSection()
        found: list[Path] = []
        for root in self.roots:
            if root.is_dir():
                self._walk(root, 0, found)

        for env in sorted(set(found)):
            kind = "conda" if (env / "conda-meta").is_dir() else "venv"
            info = PyEnvInfo(path=str(env), kind=kind)
            cfg = env / "pyvenv.cfg"
            if cfg.exists():
                parser = configparser.ConfigParser()
                try:
                    parser.read_string("[v]\n" + cfg.read_text())
                    info.python_version = parser["v"].get("version") or parser["v"].get(
                        "version_info"
                    )
                except (OSError, configparser.Error):
                    pass
            sites = list(env.glob("lib/python*/site-packages"))
            if sites:
                if info.python_version is None:
                    m = re.search(r"python(\d+\.\d+)", str(sites[0]))
                    info.python_version = m.group(1) if m else None
                info.torch_version, info.gpu_capable = torch_from_site_packages(sites[0])
            if info.torch_version is None:
                info.note = "no torch installed"
            section.envs.append(info)
        section.envs.sort(key=lambda e: (not e.gpu_capable, e.path))
        return section
