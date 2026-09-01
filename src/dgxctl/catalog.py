"""Declarative launch catalog with the host-specific guards that prevent expensive mistakes."""

from __future__ import annotations

import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dgxctl.config import config_dir
from dgxctl.schemas import CatalogEntry, CatalogParam

# vLLM images from 26.07-py3 onward require driver 610.43+. On an older driver they load,
# then die with a UnicodeDecodeError out of torch's op registry -- an error that looks like
# data corruption and mentions nothing about drivers.
VLLM_DRIVER_MIN = "610.43"
KNOWN_GOOD_VLLM_IMAGE = "vllm-spark:local"
MAX_TOTAL_GPU_UTILIZATION = 0.70


class CatalogError(ValueError):
    pass


@dataclass
class Entry:
    id: str
    name: str
    kind: str = "container"  # container | process
    image: str | None = None
    # container entries use `args` (the command inside the image); process entries use
    # `command` (an argv executed on the host). Both are argv, never shell strings.
    args: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    cwd: str | None = None
    description: str | None = None
    port: int | None = None
    bind: str = "127.0.0.1"
    env: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    runtime: str | None = None
    ipc: str | None = None
    restart: str | None = None
    gpu_memory_utilization: float | None = None
    params: list[CatalogParam] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def executable(self) -> str:
        return self.command[0] if self.command else ""

    def resolved_executable(self, values: dict[str, str] | None = None) -> str:
        """The command template filled in with defaults, as an absolute path.

        `command[0]` is a template like "{venv}/bin/jupyter-lab"; searching the process
        table for that literal string finds nothing.
        """
        if not self.command:
            return ""
        text = self.command[0]
        for param in self.params:
            supplied = (values or {}).get(param.name)
            text = text.replace("{" + param.name + "}", supplied or param.default or "")
        return str(Path(text).expanduser())

    def to_schema(self) -> CatalogEntry:
        return CatalogEntry(
            id=self.id,
            name=self.name,
            kind=self.kind,
            description=self.description,
            image=self.image,
            port=self.port,
            bind=self.bind,
            gpu_memory_utilization=self.gpu_memory_utilization,
            params=self.params,
            warnings=self.warnings,
        )


def _default_catalog_path() -> Path:
    user = config_dir() / "catalog.toml"
    if user.exists():
        return user
    packaged = Path(__file__).parent / "_data" / "catalog_default.toml"
    if packaged.exists():
        return packaged
    return Path(__file__).parent.parent.parent / "catalog" / "default.toml"


def load_catalog(path: Path | None = None) -> list[Entry]:
    path = path or _default_catalog_path()
    if not path.exists():
        return []
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    entries: list[Entry] = []
    for item in raw.get("entry", []):
        item = dict(item)
        params = [CatalogParam(**p) for p in item.pop("params", [])]
        entry = Entry(params=params, **item)
        if not entry.id:
            raise CatalogError(f"catalog entry missing id: {item}")
        if entry.kind == "container" and not entry.image:
            raise CatalogError(f"container entry {entry.id!r} has no image")
        if entry.kind == "process" and not entry.command:
            raise CatalogError(f"process entry {entry.id!r} has no command")
        if entry.kind not in ("container", "process"):
            raise CatalogError(f"entry {entry.id!r} has unknown kind {entry.kind!r}")
        _apply_guards(entry)
        entries.append(entry)
    return entries


def _apply_guards(entry: Entry) -> None:
    """Guard 1 (image pin) and guard 3 (loopback bind default)."""
    is_vllm = "vllm" in (entry.image or "").lower() or "vllm" in " ".join(entry.args).lower()
    if is_vllm:
        if entry.image != KNOWN_GOOD_VLLM_IMAGE:
            entry.warnings.append(
                f"Image {entry.image!r} is not the pinned {KNOWN_GOOD_VLLM_IMAGE!r}. "
                f"vLLM images built for driver {VLLM_DRIVER_MIN}+ fail on older drivers with a "
                f"misleading UnicodeDecodeError from torch. Verify your driver first."
            )
        if entry.env.get("VLLM_USE_DEEP_GEMM") != "0":
            entry.env["VLLM_USE_DEEP_GEMM"] = "0"
            entry.warnings.append("Set VLLM_USE_DEEP_GEMM=0 (required on sm_121).")
    if entry.bind in ("0.0.0.0", "::", "*", ""):  # noqa: S104
        entry.warnings.append(
            f"Entry {entry.id!r} publishes to ALL interfaces. Anyone who can route to this "
            f'host can reach it. Set bind = "127.0.0.1" unless that is intended.'
        )


def find_running(entry: Entry):
    """Is an instance of this entry already up? (spec R10.4)

    Checks, in order: a process dgxctl launched, a matching process started elsewhere, and a
    container from this entry. External instances are the common case, not an edge case --
    NVIDIA Sync's dashboard and a plain terminal both start JupyterLab outside dgxctl.
    """
    from dgxctl import processes as procreg

    if entry.kind == "process":
        tracked = procreg.tracked(entry.id)
        if tracked is not None:
            return tracked
        # The entry's command is a TEMPLATE ("{venv}/bin/jupyter-lab"). Searching for the
        # literal template finds nothing, so resolve it with the declared defaults first.
        executable = entry.resolved_executable()
        if executable:
            return procreg.find_external(executable, entry.port)
        return None

    from dgxctl.docker_client import get_client

    client = get_client()
    if client is None:
        return None
    from dgxctl.schemas import RunningInstance

    for c in client.containers.list():
        labels = (c.attrs.get("Config") or {}).get("Labels") or {}
        if labels.get("dgxctl.entry") == entry.id:
            return RunningInstance(container=c.name, port=entry.port, origin="dgxctl")
    return None


def check_memory_budget(
    entry: Entry, running: list[float], maximum: float = MAX_TOTAL_GPU_UTILIZATION
) -> tuple[bool, str]:
    """Guard 2. On unified memory an over-reservation starves Docker, agents and the OS."""
    requested = entry.gpu_memory_utilization or 0.0
    if requested <= 0:
        return True, ""
    current = sum(running)
    total = current + requested
    if total > maximum + 1e-9:
        return False, (
            f"Refusing launch: requested --gpu-memory-utilization {requested:.2f} plus "
            f"{current:.2f} already reserved by running servers would total {total:.2f}, "
            f"over the {maximum:.2f} ceiling. On unified memory that starves Docker, "
            f"running agents and the OS page cache. Stop a server first, or lower the request."
        )
    return True, ""


def resolve_params(entry: Entry, values: dict[str, str]) -> dict[str, str]:
    """Only declared params are substitutable. Unknown keys are rejected, not ignored."""
    declared = {p.name: p for p in entry.params}
    unknown = set(values) - set(declared)
    if unknown:
        raise CatalogError(f"unknown parameter(s) for {entry.id}: {sorted(unknown)}")
    resolved: dict[str, str] = {}
    for name, param in declared.items():
        raw = values.get(name)
        if raw is None or raw == "":
            if param.required:
                raise CatalogError(f"missing required parameter {name!r} for {entry.id}")
            raw = param.default or ""
        if name == "token" and raw == "auto":
            raw = secrets.token_urlsafe(16)
        resolved[name] = str(raw)
    resolved.setdefault("port", str(entry.port or 0))
    if entry.gpu_memory_utilization is not None:
        resolved.setdefault("gpu_memory_utilization", f"{entry.gpu_memory_utilization}")
    return resolved


def build_process_spec(entry: Entry, values: dict[str, str]) -> dict:
    """Produce the argv for a host process entry. Argv only — never a shell string."""
    if entry.kind != "process":
        raise CatalogError(f"{entry.id!r} is not a process entry")
    resolved = resolve_params(entry, values)

    def sub(text: str) -> str:
        out = text
        for k, v in resolved.items():
            out = out.replace("{" + k + "}", v)
        return str(Path(out).expanduser()) if out.startswith("~") else out

    argv = [sub(part) for part in entry.command]
    executable = Path(argv[0]).expanduser()
    if not executable.exists():
        raise CatalogError(
            f"{executable} does not exist. "
            f"Set the entry's parameters to point at an environment that has it."
        )
    argv[0] = str(executable)
    port = int(resolved.get("port") or entry.port or 0)
    return {
        "argv": argv,
        "cwd": sub(entry.cwd) if entry.cwd else None,
        "env": {k: sub(v) for k, v in entry.env.items()},
        "port": port,
        "bind": entry.bind,
        "resolved": resolved,
    }


def build_run_spec(entry: Entry, values: dict[str, str]) -> dict:
    """Produce the docker-run kwargs. Ports ALWAYS carry an explicit bind address."""
    if entry.kind != "container":
        raise CatalogError(f"{entry.id!r} is not a container entry")
    resolved = resolve_params(entry, values)

    def sub(text: str) -> str:
        out = text
        for k, v in resolved.items():
            out = out.replace("{" + k + "}", v)
        return out

    port = int(resolved.get("port") or entry.port or 0)
    ports = {}
    if port:
        # (bind, port) tuple -- never a bare port, which would publish on 0.0.0.0.
        ports[f"{port}/tcp"] = (entry.bind, port)

    volumes = {}
    for v in entry.volumes:
        host, _, container = v.partition(":")
        volumes[str(Path(host).expanduser())] = {"bind": container, "mode": "rw"}

    spec = {
        "image": entry.image,
        "command": [sub(a) for a in entry.args] or None,
        "detach": True,
        "environment": {k: sub(v) for k, v in entry.env.items()},
        "ports": ports,
        "volumes": volumes,
        "labels": {
            "dgxctl.entry": entry.id,
            **(
                {"dgxctl.gpu_memory_utilization": str(entry.gpu_memory_utilization)}
                if entry.gpu_memory_utilization
                else {}
            ),
        },
    }
    if entry.runtime:
        spec["runtime"] = entry.runtime
    if entry.ipc:
        spec["ipc_mode"] = entry.ipc
    if entry.restart:
        spec["restart_policy"] = {"Name": entry.restart}
    return {"spec": spec, "resolved": resolved, "port": port, "bind": entry.bind}
