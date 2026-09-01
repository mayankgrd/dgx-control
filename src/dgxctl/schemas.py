"""The API contract. Frontend TypeScript types are generated from this via OpenAPI."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Status(StrEnum):
    ok = "ok"
    degraded = "degraded"
    error = "error"
    unavailable = "unavailable"


class Exposure(StrEnum):
    """How reachable a bound socket is. The vocabulary is shared with the UI."""

    loopback = "loopback"
    lan = "lan"
    tailnet = "tailnet"
    all = "all"
    unknown = "unknown"


class Envelope(BaseModel):
    status: Status = Status.ok
    data: Any | None = None
    error: str | None = None
    collected_at: str | None = None
    duration_ms: float | None = None


class NodeInfo(BaseModel):
    id: str
    name: str
    kind: str = "local"  # local | remote
    reachable: bool = True
    error: str | None = None


class Snapshot(BaseModel):
    node: NodeInfo
    version: int
    sections: dict[str, Envelope] = Field(default_factory=dict)


# --- section payloads -------------------------------------------------------


class GpuDevice(BaseModel):
    index: int
    name: str
    utilization_percent: float | None = None
    memory_utilization_percent: float | None = None
    temperature_c: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    sm_clock_mhz: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    memory_source: str = "nvml"  # nvml | system (unified-memory fallback)


class MemoryPool(BaseModel):
    """On unified-memory parts (GB10) CPU and GPU share ONE pool. Never render two."""

    unified: bool
    total_bytes: int
    used_bytes: int
    available_bytes: int
    cached_bytes: int
    gpu_reserved_bytes: int | None = None


class GpuSection(BaseModel):
    devices: list[GpuDevice] = Field(default_factory=list)
    memory: MemoryPool | None = None
    driver_version: str | None = None
    cuda_version: str | None = None


class ProcessInfo(BaseModel):
    pid: int
    name: str
    cmdline: str
    username: str | None = None
    cpu_percent: float | None = None
    rss_bytes: int | None = None
    gpu_memory_bytes: int | None = None
    container_id: str | None = None
    container_name: str | None = None
    started_at: str | None = None


class ProcessSection(BaseModel):
    gpu_processes: list[ProcessInfo] = Field(default_factory=list)
    top_cpu: list[ProcessInfo] = Field(default_factory=list)
    total_processes: int = 0


class PortBinding(BaseModel):
    container_port: int
    protocol: str = "tcp"
    host_ip: str | None = None
    host_port: int | None = None
    exposure: Exposure = Exposure.unknown


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: str
    created_at: str | None = None
    started_at: str | None = None
    restart_policy: str | None = None
    restart_count: int = 0
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None
    net_rx_bytes: int | None = None
    net_tx_bytes: int | None = None
    block_read_bytes: int | None = None
    block_write_bytes: int | None = None
    ports: list[PortBinding] = Field(default_factory=list)
    launched_by_dgxctl: bool = False
    gpu_memory_utilization: float | None = None


class ContainerSection(BaseModel):
    containers: list[ContainerInfo] = Field(default_factory=list)
    running: int = 0
    stopped: int = 0
    stats_available: bool = True


class ImageInfo(BaseModel):
    id: str
    repository: str
    tag: str
    size_bytes: int
    created_at: str | None = None
    in_use: bool = False
    dangling: bool = False


class ImageSection(BaseModel):
    images: list[ImageInfo] = Field(default_factory=list)
    total_bytes: int = 0


class FilesystemInfo(BaseModel):
    mountpoint: str
    device: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float
    over_threshold: bool = False


class SizedRoot(BaseModel):
    path: str
    label: str
    size_bytes: int | None = None
    error: str | None = None


class DockerUsage(BaseModel):
    images_bytes: int = 0
    containers_bytes: int = 0
    volumes_bytes: int = 0
    build_cache_bytes: int = 0
    reclaimable_bytes: int = 0


class DiskSection(BaseModel):
    filesystems: list[FilesystemInfo] = Field(default_factory=list)
    sized_roots: list[SizedRoot] = Field(default_factory=list)
    docker: DockerUsage | None = None


class Listener(BaseModel):
    protocol: str
    bind_ip: str
    port: int
    exposure: Exposure
    pid: int | None = None
    process: str | None = None
    container_name: str | None = None
    is_finding: bool = False


class NetworkSection(BaseModel):
    listeners: list[Listener] = Field(default_factory=list)
    findings: list[Listener] = Field(default_factory=list)
    local_addresses: list[str] = Field(default_factory=list)


class TailscalePeer(BaseModel):
    hostname: str
    dns_name: str | None = None
    os: str | None = None
    ips: list[str] = Field(default_factory=list)
    online: bool = False
    exit_node: bool = False


class TailscaleSection(BaseModel):
    backend_state: str
    version: str | None = None
    self_hostname: str | None = None
    self_dns_name: str | None = None
    self_ips: list[str] = Field(default_factory=list)
    exit_node_active: bool = False
    peers: list[TailscalePeer] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    # Set only for declared services: the id the launch action needs. Deriving it from the
    # display name would break the moment someone renames a service.
    id: str | None = None
    name: str
    kind: str
    port: int
    bind_ip: str
    exposure: Exposure
    pid: int | None = None
    container_name: str | None = None
    health: str = "unprobed"  # ok | unreachable | unprobed
    served_models: list[str] = Field(default_factory=list)
    path: str = "/"
    # False for unclassified ephemeral loopback ports -- internal plumbing of other
    # programs, not services anyone runs on purpose. Kept in the payload, hidden by
    # default in the UI, because dropping them would be lying about what is listening.
    # What this thing IS (spec R15.1). A port with no explanation is noise.
    label: str = ""  # "vLLM"
    summary: str = ""  # "OpenAI-compatible server for a local model."
    category: str = "unknown"  # llm | notebook | agent | tool | infrastructure | unknown
    recognised: bool = False
    is_self: bool = False  # this dashboard

    notable: bool = True
    linkable: bool = True

    # --- how to actually USE this service (spec R11) --------------------
    # The client composes the origin, because only the browser knows how the viewer
    # reached the dashboard. The server supplies everything after it.
    auth_query: str | None = None  # e.g. "?token=..." — treat as a credential
    auth_hint: str | None = None  # what to do when no credential can be read
    base_url: str | None = None  # OpenAI-compatible base_url for model servers
    declared: bool = False  # from [[service]] in config rather than discovered
    online: bool = True
    launchable: bool = False  # a declared launch command exists


class HostAddressInfo(BaseModel):
    """Where this machine can be reached, so a URL can be built for the viewer's position."""

    hostname: str = ""
    loopback: str = "127.0.0.1"
    lan: list[str] = Field(default_factory=list)
    tailnet_ip: str | None = None
    tailnet_name: str | None = None


class ServiceSection(BaseModel):
    services: list[ServiceInfo] = Field(default_factory=list)
    host: HostAddressInfo = Field(default_factory=HostAddressInfo)


class ModelInfo(BaseModel):
    id: str
    source: str  # huggingface | ollama | scan
    revision: str | None = None
    size_bytes: int = 0
    last_used: str | None = None
    path: str | None = None
    served_by: list[str] = Field(default_factory=list)
    max_position_embeddings: int | None = None
    architecture: str | None = None
    quantization: str | None = None
    num_parameters: int | None = None
    active_parameters: int | None = None


class ModelSection(BaseModel):
    models: list[ModelInfo] = Field(default_factory=list)
    totals_by_source: dict[str, int] = Field(default_factory=dict)
    scanning: bool = False
    scanned_at: str | None = None


class PyEnvInfo(BaseModel):
    path: str
    kind: str  # venv | conda
    python_version: str | None = None
    torch_version: str | None = None
    gpu_capable: bool = False
    note: str | None = None


class PyEnvSection(BaseModel):
    envs: list[PyEnvInfo] = Field(default_factory=list)


# --- actions ---------------------------------------------------------------


class CatalogParam(BaseModel):
    name: str
    kind: str = "string"
    required: bool = False
    default: str | None = None
    description: str | None = None


class RunningInstance(BaseModel):
    """An instance of a catalog entry that is already up."""

    pid: int | None = None
    container: str | None = None
    port: int | None = None
    started_at: str | None = None
    origin: str = "dgxctl"  # dgxctl | external
    log_path: str | None = None


class CatalogEntry(BaseModel):
    id: str
    name: str
    kind: str = "container"  # container | process
    description: str | None = None
    image: str | None = None
    port: int | None = None
    bind: str = "127.0.0.1"
    gpu_memory_utilization: float | None = None
    params: list[CatalogParam] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    running: RunningInstance | None = None


class CatalogSection(BaseModel):
    entries: list[CatalogEntry] = Field(default_factory=list)


class ActionResult(BaseModel):
    ok: bool
    action: str
    target: str
    message: str
    detail: dict[str, Any] | None = None


class ActionLogEntry(BaseModel):
    ts: str
    identity: str
    action: str
    target: str
    ok: bool
    message: str


class HealthResponse(BaseModel):
    """Deliberately contains NO host data (spec S1)."""

    status: str = "ok"
    version: str
    uptime_seconds: float


class DoctorCheck(BaseModel):
    name: str
    status: Status
    detail: str
    fix: str | None = None


class DoctorReport(BaseModel):
    checks: list[DoctorCheck] = Field(default_factory=list)
    ok: bool = True


class SectionPayloads(BaseModel):
    """Documentation-only model.

    `Envelope.data` is deliberately `Any` so a collector can degrade without breaking the
    response shape. That would leave every section payload out of the OpenAPI document,
    and therefore out of the frontend's generated types. This model pins them into the
    schema; `GET /api/schema/sections` returns an empty instance so the generator sees it.
    """

    gpu: GpuSection | None = None
    processes: ProcessSection | None = None
    containers: ContainerSection | None = None
    images: ImageSection | None = None
    disk: DiskSection | None = None
    network: NetworkSection | None = None
    tailscale: TailscaleSection | None = None
    services: ServiceSection | None = None
    models: ModelSection | None = None
    pyenvs: PyEnvSection | None = None
