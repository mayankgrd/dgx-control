"""Configuration loading. Env (DGXCTL_*) > config file > defaults."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def config_dir() -> Path:
    return Path(os.environ.get("DGXCTL_CONFIG_DIR", Path.home() / ".config" / "dgxctl"))


def state_dir() -> Path:
    return Path(os.environ.get("DGXCTL_STATE_DIR", Path.home() / ".local" / "share" / "dgxctl"))


class RemoteNode(BaseModel):
    """A peer dgxctl instance on another DGX. See architecture.md section 13."""

    model_config = {"extra": "forbid"}

    id: str
    name: str | None = None
    url: str
    token: str | None = None
    token_file: str | None = None
    verify_tls: bool = True

    def resolve_token(self) -> str | None:
        if self.token:
            return self.token
        if self.token_file:
            p = Path(self.token_file).expanduser()
            if p.exists():
                return p.read_text().strip()
        return None


class DeclaredService(BaseModel):
    """A service dgxctl cannot discover on its own (spec R12)."""

    model_config = {"extra": "forbid"}

    id: str
    name: str | None = None
    port: int
    path: str = "/"
    kind: str = "http"
    # argv, never a shell string (spec S8)
    launch: list[str] = Field(default_factory=list)
    note: str | None = None


class Intervals(BaseModel):
    model_config = {"extra": "forbid"}

    gpu: float = 2.0
    processes: float = 5.0
    containers: float = 5.0
    images: float = 60.0
    disk: float = 60.0
    network: float = 15.0
    tailscale: float = 15.0
    services: float = 60.0
    models: float = 600.0
    pyenvs: float = 300.0
    remote: float = 10.0


class Settings(BaseModel):
    """Effective configuration. Nothing here is host-specific by default."""

    model_config = {"extra": "forbid"}

    host: str = "127.0.0.1"
    port: int = 8770

    node_id: str = "local"
    node_name: str | None = None

    control_enabled: bool = False
    tailscale_allowlist: list[str] = Field(default_factory=list)

    disk_warn_percent: float = 85.0
    history_window_minutes: int = 60
    history_max_bytes: int = 64 * 1024 * 1024

    # Addresses to prefer when building links and port-forward commands. Set this when you
    # reach the machine by a name rather than a raw IP (a DNS entry, a /etc/hosts alias, a
    # MagicDNS name). Detected addresses are still offered, just after these.
    advertise_addresses: list[str] = Field(default_factory=list)

    hf_cache: str = "~/.cache/huggingface"
    model_scan_roots: list[str] = Field(default_factory=list)
    pyenv_roots: list[str] = Field(default_factory=lambda: ["~", "~/projects"])
    sized_roots: list[str] = Field(default_factory=lambda: ["~/.cache/huggingface"])

    nodes: list[RemoteNode] = Field(default_factory=list)
    services: list[DeclaredService] = Field(default_factory=list)
    intervals: Intervals = Field(default_factory=Intervals)

    @field_validator("port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be 1..65535")
        return v

    @property
    def is_loopback(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    @property
    def token_path(self) -> Path:
        return config_dir() / "token"

    def expand(self, p: str) -> Path:
        return Path(p).expanduser()


_ENV_PREFIX = "DGXCTL_"
_SCALARS = {
    "host": str,
    "port": int,
    "node_id": str,
    "node_name": str,
    "control_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
    "disk_warn_percent": float,
    "history_window_minutes": int,
    "history_max_bytes": int,
    "hf_cache": str,
}


def load_settings(path: Path | None = None) -> Settings:
    """Layer env over file over defaults. Unknown keys are an error, not a silent no-op."""
    path = path or (config_dir() / "config.toml")
    data: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        # [[node]] is friendlier TOML than nodes = [...]
        if "node" in data:
            data["nodes"] = data.pop("node")
        if "service" in data:
            data["services"] = data.pop("service")

    for key, caster in _SCALARS.items():
        env = os.environ.get(_ENV_PREFIX + key.upper())
        if env is not None:
            data[key] = caster(env)

    try:
        return Settings(**data)
    except ValidationError as exc:
        raise ValueError(f"invalid configuration in {path}: {exc}") from exc
