"""Model inventory: HuggingFace cache, Ollama, and configured scan roots.

Incremental — a cold walk of a ~150 GB cache must not block the event loop, and must
never open credential files that happen to live under a scan root (spec S9).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from dgxctl.collectors.base import Collector, have, run_cmd
from dgxctl.schemas import ModelInfo, ModelSection

WEIGHT_SUFFIXES = {".safetensors", ".gguf", ".bin", ".pt", ".pth", ".onnx"}
# Never read these, even inside a configured scan root (spec S9).
CREDENTIAL_NAMES = {"token", ".env", "credentials", "id_rsa", ".netrc", ".git-credentials"}


def _dir_size(path: Path) -> tuple[int, float]:
    """Bytes and newest mtime, following the symlinks the HF cache uses for blobs."""
    total, newest = 0, 0.0
    for p in path.rglob("*"):
        try:
            if p.name in CREDENTIAL_NAMES:
                continue
            st = p.stat()  # follows symlinks: HF snapshots point into blobs/
            if p.is_file() or p.is_symlink():
                total += st.st_size
                newest = max(newest, st.st_mtime)
        except (OSError, PermissionError):
            continue
    return total, newest


def read_model_config(snapshot: Path) -> dict:
    """Serving-relevant facts. A malformed config must not fail the whole section."""
    cfg_path = snapshot / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        cfg = json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(cfg, dict):
        return {}
    text_cfg = cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else {}
    quant = cfg.get("quantization_config") or {}
    out = {
        "max_position_embeddings": cfg.get("max_position_embeddings")
        or text_cfg.get("max_position_embeddings"),
        "architecture": (cfg.get("architectures") or [None])[0] or cfg.get("model_type"),
        "quantization": (quant.get("quant_method") if isinstance(quant, dict) else None),
    }
    experts = cfg.get("num_experts_per_tok") or text_cfg.get("num_experts_per_tok")
    if experts:
        out["architecture"] = f"{out['architecture']} (MoE, {experts} active experts)"
    return {k: v for k, v in out.items() if v is not None}


class ModelCollector(Collector):
    name = "models"
    interval = 600.0
    timeout = 900.0

    def __init__(self, hf_cache: str, scan_roots: list[str] | None = None) -> None:
        super().__init__()
        self.hf_cache = Path(hf_cache).expanduser()
        self.scan_roots = [Path(r).expanduser() for r in (scan_roots or [])]
        self._cache: dict[str, tuple[float, int, float]] = {}  # key -> (mtime, size, scanned)
        self._scanning = False

    async def collect(self) -> dict:
        self._scanning = True
        try:
            section = await self._collect_async()
        finally:
            self._scanning = False
        return section.model_dump()

    async def _collect_async(self) -> ModelSection:
        section = ModelSection(scanning=False, scanned_at=datetime.now(UTC).isoformat())
        hub = self.hf_cache / "hub"
        if hub.is_dir():
            for entry in sorted(hub.iterdir()):
                if not entry.is_dir() or not entry.name.startswith("models--"):
                    continue
                model = await asyncio.to_thread(self._hf_entry, entry)
                if model:
                    section.models.append(model)
                await asyncio.sleep(0)  # yield: a cold scan must not block the loop

        if have("ollama"):
            try:
                for m in await asyncio.to_thread(self._ollama):
                    section.models.append(m)
            except Exception:  # noqa: BLE001, S110
                pass

        for root in self.scan_roots:
            if root.is_dir():
                for m in await asyncio.to_thread(self._scan_root, root):
                    section.models.append(m)
                await asyncio.sleep(0)

        for m in section.models:
            section.totals_by_source[m.source] = (
                section.totals_by_source.get(m.source, 0) + m.size_bytes
            )
        section.models.sort(key=lambda m: -m.size_bytes)
        return section

    def _hf_entry(self, entry: Path) -> ModelInfo | None:
        repo = entry.name.removeprefix("models--").replace("--", "/")
        snapshots = entry / "snapshots"
        revision, snap_dir = None, None
        if snapshots.is_dir():
            revs = [d for d in snapshots.iterdir() if d.is_dir()]
            if revs:
                snap_dir = max(revs, key=lambda d: d.stat().st_mtime)
                revision = snap_dir.name[:12]
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            return None
        cached = self._cache.get(str(entry))
        if cached and cached[0] == mtime:
            size, newest = cached[1], cached[2]
        else:
            size, newest = _dir_size(entry)
            self._cache[str(entry)] = (mtime, size, newest)
        info = ModelInfo(
            id=repo,
            source="huggingface",
            revision=revision,
            size_bytes=size,
            path=str(entry),
            last_used=datetime.fromtimestamp(newest or mtime, UTC).isoformat(),
        )
        if snap_dir:
            for k, v in read_model_config(snap_dir).items():
                setattr(info, k, v)
        return info

    def _ollama(self) -> list[ModelInfo]:
        out = run_cmd(["ollama", "list"], timeout=15.0)
        models = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            name, size_val, size_unit = parts[0], parts[2], parts[3] if len(parts) > 3 else "B"
            mult = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}.get(
                size_unit.upper(), 1
            )
            try:
                size = int(float(size_val) * mult)
            except ValueError:
                size = 0
            models.append(ModelInfo(id=name, source="ollama", size_bytes=size))
        return models

    def _scan_root(self, root: Path) -> list[ModelInfo]:
        found: list[ModelInfo] = []
        for p in root.rglob("*"):
            try:
                if p.suffix.lower() in WEIGHT_SUFFIXES and p.is_file():
                    st = p.stat()
                    found.append(
                        ModelInfo(
                            id=p.name,
                            source="scan",
                            size_bytes=st.st_size,
                            path=str(p),
                            last_used=datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
                        )
                    )
            except (OSError, PermissionError):
                continue
            if len(found) > 500:
                break
        return found
