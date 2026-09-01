"""Registering tools with NVIDIA Sync (spec R13).

Sync keeps its custom tools in a plain JSON array:

    ~/.config/NVIDIA/Sync/config/custom.json
    [{"id","port","name","scriptContent","autoOpen","url","interactive","shown"}]

This module writes that file, so it is deliberately conservative: it never creates the file
where Sync is not installed, never writes over something it could not parse, always backs up
first, and always preserves entries it did not create.
"""

from __future__ import annotations

import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

SYNC_CONFIG = "~/.config/NVIDIA/Sync/config/custom.json"


class SyncError(RuntimeError):
    pass


def config_path() -> Path:
    return Path(SYNC_CONFIG).expanduser()


def _new_id() -> str:
    """Sync's ids are long opaque hex strings; shape ours the same way."""
    return secrets.token_hex(17)


def read_entries(path: Path | None = None) -> list[dict]:
    path = path or config_path()
    if not path.exists():
        raise SyncError(
            f"NVIDIA Sync config not found at {path}.\n"
            f"Either Sync is not installed on this machine, or it has never been run. "
            f"dgxctl will not create the file."
        )
    try:
        data = json.loads(path.read_text() or "[]")
    except ValueError as exc:
        raise SyncError(
            f"{path} is not valid JSON ({exc}). Refusing to modify it — "
            f"fix or remove the file and try again."
        ) from exc
    if not isinstance(data, list):
        raise SyncError(f"{path} does not contain a JSON array; refusing to modify it.")
    return data


def _backup(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest = path.with_suffix(f".json.bak-{stamp}")
    shutil.copy2(path, dest)
    return dest


def _write(entries: list[dict], path: Path) -> Path:
    backup = _backup(path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, separators=(",", ":")))
    tmp.replace(path)
    return backup


def register(
    name: str,
    port: int,
    url_path: str = "/",
    auto_open: bool = True,
    script: str = "",
    interactive: bool = False,
    path: Path | None = None,
) -> tuple[dict, Path]:
    """Add or update one entry by name. Every other entry is preserved untouched."""
    path = path or config_path()
    entries = read_entries(path)
    url = f"http://localhost:{port}{url_path if url_path.startswith('/') else '/' + url_path}"
    existing = next((e for e in entries if e.get("name") == name), None)
    entry = {
        "id": (existing or {}).get("id") or _new_id(),
        "port": str(port),
        "name": name,
        "scriptContent": script,
        "autoOpen": auto_open,
        "url": url,
        "interactive": interactive,
        "shown": True,
    }
    if existing is not None:
        entries[entries.index(existing)] = entry
    else:
        entries.append(entry)
    backup = _write(entries, path)
    return entry, backup


def unregister(name: str, path: Path | None = None) -> tuple[bool, Path | None]:
    path = path or config_path()
    entries = read_entries(path)
    remaining = [e for e in entries if e.get("name") != name]
    if len(remaining) == len(entries):
        return False, None
    backup = _write(remaining, path)
    return True, backup
