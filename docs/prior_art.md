# prior_art.md — What already exists

Surveyed 2026-08-30. Answers "is someone already doing this better than vanilla NVIDIA?"

## The landscape

| Project | Covers | Gaps vs. our spec |
|---|---|---|
| **NVIDIA DGX Dashboard** (in NVIDIA Sync) — [build.nvidia.com](https://build.nvidia.com/spark/dgx-dashboard) | Basic GPU util, RAM | Everything else. This is the baseline we are beating. |
| **[sparkDash](https://github.com/MiaAI-Lab/sparkDash)** (MiaAI-Lab) — closest prior art | Multi-unit GPU/CPU/unified-mem/storage/network, **GPU processes by VRAM**, ComfyUI queue + its model inventory, Hermes version, **Tailscale connectivity status**, WoL + graceful shutdown. React 19 + Express + WebSocket, ARM64, docker-compose. | **No Docker container/image observability or control. No HF cache inventory. No listening-port / exposure auditing. No process→container attribution. Explicitly unauthenticated** — "run only on a trusted network." That last point is disqualifying for our tailnet-exposed deployment. |
| **[spark-dashboard](https://github.com/niklasfrick/spark-dashboard)** (niklasfrick) | Rust backend, GPU/CPU/mem/disk/net **+ vLLM engine stats**, WebSocket → React. | Single-host telemetry only; no container control, no model inventory, no exposure audit. |
| **[dgx-spark-status](https://github.com/thx0701/dgx-spark-status)** (thx0701) | SvelteKit + SSE, GPU/CPU/mem, some inference-engine status incl. vLLM container serving. | Narrower; no storage/model/network depth, no control surface. |
| **[dgxsparkmonitor](https://github.com/chronosolidus/dgxsparkmonitor)** | Live telemetry over **SSH** to cluster nodes, RDMA/Ethernet throughput, thermals. | Agentless-over-SSH design; no containers, models, or exposure. |
| **[NVIDIA-DGX-Spark-Dashboard](https://github.com/paul-aviles/NVIDIA-DGX-Spark-Dashboard)** | Two Sparks over passwordless SSH, sparklines for CPU/mem/GPU/disk/net. | Telemetry only. |
| **[DGX-Model-Manager](https://github.com/calico88x/DGX-Model-Manager)** | **The model/serving control we want**: pull Ollama models, browse + download from HuggingFace, LiteLLM routing, start/stop SGLang, vLLM, llama.cpp, LocalAI, ComfyUI. Single-file web UI. | No system observability — no GPU attribution, disk, ports, Tailscale. It is the complement of the monitors, not a superset. |

## Conclusion

The ecosystem splits cleanly into **telemetry dashboards** and **model/serving managers**, and nothing
spans both. Specifically, no existing tool does all of:

1. GPU process attribution **joined to the owning Docker container** (R1.4)
2. Docker container **and image** inventory with per-container resource usage and lifecycle control (R2)
3. HuggingFace-cache model inventory joined to what is actually being served (R5.3)
4. **Listening-socket exposure auditing** that flags non-loopback binds by owner (R6.2) — the single
   most valuable thing on a tailnet shared with other people, and absent from every project above
5. **Authenticated** operation (S1–S4) — sparkDash, the closest competitor, ships with none
6. **NVIDIA Sync custom-tool registration** on a single port (R7)

Items 4 and 5 are the sharpest differentiators, and they are exactly what our deployment choice
(tailnet-exposed) demands.

## Things worth stealing

- **SSE or WebSocket streaming over polling** — every serious project here streams. Confirms our
  `/api/stream` design (SDD-005).
- **sparkDash's per-unit optional collectors** — collectors that degrade to "not configured" rather
  than erroring. Already our N3.
- **spark-dashboard's vLLM engine stats** — scraping a vLLM server's `/metrics` gives queue depth and
  throughput far richer than `/v1/models`. Filed as **SDD-060** (deferred, post-v1).
- **DGX-Model-Manager's engine control** — if our R2.8 catalog proves too rigid, its per-engine
  launch UX is the reference design.

## Build-vs-adopt

Adopting sparkDash and adding to it was considered. Rejected: it is a multi-host Node/Express
telemetry app with no auth and no container layer, so items 1–6 would each be a fork-level change to
someone else's architecture, and the auth gap sits at its foundation. We build, and treat its GPU
panel and Tailscale integration as reference implementations.
