/**
 * Hand-maintained narrowing over the generated OpenAPI types.
 *
 * `src/api/types.gen.ts` is GENERATED (`npm run gen:types`) and must never be edited by
 * hand; this file re-exports the section payloads under friendlier names and adds the
 * couple of shapes the SSE stream introduces on top of the REST contract.
 */

export type Status = "ok" | "degraded" | "error" | "unavailable";
export type Exposure = "loopback" | "lan" | "tailnet" | "all" | "unknown";

export interface Envelope<T = unknown> {
  status: Status;
  data: T | null;
  error: string | null;
  collected_at: string | null;
  duration_ms: number | null;
}

export interface NodeInfo {
  id: string;
  name: string;
  kind: "local" | "remote";
  reachable: boolean;
  error: string | null;
}

export interface Snapshot {
  node: NodeInfo;
  version: number;
  sections: Record<string, Envelope>;
}

export interface GpuDevice {
  index: number;
  name: string;
  utilization_percent: number | null;
  memory_utilization_percent: number | null;
  temperature_c: number | null;
  power_w: number | null;
  power_limit_w: number | null;
  sm_clock_mhz: number | null;
  memory_total_bytes: number | null;
  memory_used_bytes: number | null;
  memory_source: "nvml" | "system";
}

export interface MemoryPool {
  unified: boolean;
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  cached_bytes: number;
  gpu_reserved_bytes: number | null;
}

export interface GpuSection {
  devices: GpuDevice[];
  memory: MemoryPool | null;
  driver_version: string | null;
  cuda_version: string | null;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  cmdline: string;
  username: string | null;
  cpu_percent: number | null;
  rss_bytes: number | null;
  gpu_memory_bytes: number | null;
  container_id: string | null;
  container_name: string | null;
  started_at: string | null;
}

export interface ProcessSection {
  gpu_processes: ProcessInfo[];
  top_cpu: ProcessInfo[];
  total_processes: number;
}

export interface PortBinding {
  container_port: number;
  protocol: string;
  host_ip: string | null;
  host_port: number | null;
  exposure: Exposure;
}

export interface ContainerInfo {
  id: string;
  name: string;
  image: string;
  status: string;
  state: string;
  created_at: string | null;
  started_at: string | null;
  restart_policy: string | null;
  restart_count: number;
  cpu_percent: number | null;
  memory_bytes: number | null;
  memory_limit_bytes: number | null;
  net_rx_bytes: number | null;
  net_tx_bytes: number | null;
  block_read_bytes: number | null;
  block_write_bytes: number | null;
  ports: PortBinding[];
  launched_by_dgxctl: boolean;
  gpu_memory_utilization: number | null;
}

export interface ContainerSection {
  containers: ContainerInfo[];
  running: number;
  stopped: number;
  stats_available: boolean;
}

export interface ImageInfo {
  id: string;
  repository: string;
  tag: string;
  size_bytes: number;
  created_at: string | null;
  in_use: boolean;
  dangling: boolean;
}
export interface ImageSection { images: ImageInfo[]; total_bytes: number }

export interface FilesystemInfo {
  mountpoint: string; device: string; fstype: string;
  total_bytes: number; used_bytes: number; free_bytes: number;
  percent: number; over_threshold: boolean;
}
export interface SizedRoot { path: string; label: string; size_bytes: number | null; error: string | null }
export interface DockerUsage {
  images_bytes: number; containers_bytes: number; volumes_bytes: number;
  build_cache_bytes: number; reclaimable_bytes: number;
}
export interface DiskSection {
  filesystems: FilesystemInfo[]; sized_roots: SizedRoot[]; docker: DockerUsage | null;
}

export interface Listener {
  protocol: string; bind_ip: string; port: number; exposure: Exposure;
  pid: number | null; process: string | null; container_name: string | null; is_finding: boolean;
}
export interface NetworkSection {
  listeners: Listener[]; findings: Listener[]; local_addresses: string[];
}

export interface TailscalePeer {
  hostname: string; dns_name: string | null; os: string | null;
  ips: string[]; online: boolean; exit_node: boolean;
}
export interface TailscaleSection {
  backend_state: string; version: string | null; self_hostname: string | null;
  self_dns_name: string | null; self_ips: string[]; exit_node_active: boolean;
  peers: TailscalePeer[];
}

export interface ServiceInfo {
  id: string | null;
  name: string; kind: string; port: number; bind_ip: string; exposure: Exposure;
  pid: number | null; container_name: string | null;
  health: "ok" | "unreachable" | "unprobed"; served_models: string[]; path: string;
  /** What this thing IS (spec R15.1). */
  label: string; summary: string; category: ServiceCategory;
  recognised: boolean; is_self: boolean;
  notable: boolean; linkable: boolean;
  /** Everything after the origin needed to actually use the service (spec R11). */
  auth_query: string | null;   // e.g. "?token=..." — treat as a credential
  auth_hint: string | null;
  base_url: string | null;
  declared: boolean;
  online: boolean;
  launchable: boolean;
}
export type ServiceCategory =
  | "llm" | "notebook" | "agent" | "tool" | "infrastructure" | "unknown";

export interface HostAddressInfo {
  hostname: string;
  loopback: string;
  lan: string[];
  tailnet_ip: string | null;
  tailnet_name: string | null;
}

export interface ServiceSection {
  services: ServiceInfo[];
  host: HostAddressInfo;
}

export interface ModelInfo {
  id: string; source: string; revision: string | null; size_bytes: number;
  last_used: string | null; path: string | null; served_by: string[];
  max_position_embeddings: number | null; architecture: string | null;
  quantization: string | null; num_parameters: number | null; active_parameters: number | null;
}
export interface ModelSection {
  models: ModelInfo[]; totals_by_source: Record<string, number>;
  scanning: boolean; scanned_at: string | null;
}

export interface PyEnvInfo {
  path: string; kind: string; python_version: string | null;
  torch_version: string | null; gpu_capable: boolean; note: string | null;
}
export interface PyEnvSection { envs: PyEnvInfo[] }

export interface CatalogParam {
  name: string; kind: string; required: boolean; default: string | null; description: string | null;
}
export interface RunningInstance {
  pid: number | null; container: string | null; port: number | null;
  started_at: string | null; origin: "dgxctl" | "external"; log_path: string | null;
}

export interface CatalogEntry {
  id: string; name: string; kind: "container" | "process";
  description: string | null; image: string | null;
  port: number | null; bind: string; gpu_memory_utilization: number | null;
  params: CatalogParam[]; warnings: string[];
  running: RunningInstance | null;
}

export interface ActionResult {
  ok: boolean; action: string; target: string; message: string;
  detail: Record<string, unknown> | null;
}
export interface ActionLogEntry {
  ts: string; identity: string; action: string; target: string; ok: boolean; message: string;
}
export interface DoctorCheck { name: string; status: Status; detail: string; fix: string | null }
export interface DoctorReport { checks: DoctorCheck[]; ok: boolean }
