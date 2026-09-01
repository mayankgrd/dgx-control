# Fixtures

Captured from a live NVIDIA DGX Spark (GB10, Ubuntu 24.04, driver 580.159.03) on 2026-08-30.
Parsers are tested against these real bytes, never against invented output.

Tailnet peer identities and public keys are scrubbed; bind addresses and structural shapes are
preserved, because those are exactly what the parsers must survive.

| File | Captured from |
|---|---|
| `ss_tulnpH.txt` | `ss -tulnpH` — IPv6, `%zone` suffixes, and PID-less root-owned sockets |
| `tailscale_status.json` | `tailscale status --json` (Tailscale 1.102.2) |
| `cgroup_v2_docker.txt` | `/proc/<gpu_pid>/cgroup` of a containerized vLLM engine |
| `cgroup_v1_docker.txt` | cgroup v1 equivalent |
| `docker_ports.json` | `NetworkSettings.Ports`: a 0.0.0.0 publish, a loopback publish, an empty HostIp |
| `meminfo.txt` | `/proc/meminfo` on a 121 GB unified-memory host |
| `ollama_list.txt` | `ollama list` |
