# architecture.md — DGX Control

Architecture and implementation detail. **Long document — load only the sections relevant to your
task.** Keep consistent with [spec.md](spec.md) forever after.

## Section index

| § | Section | Load when |
|---|---|---|
| 1 | System overview & runtime shape | Always, first session |
| 2 | Repository layout | Adding any file |
| 3 | Collector framework | Writing/changing a collector |
| 4 | Per-collector data sources | Working on a specific collector |
| 5 | Snapshot store & history | Touching state or SQLite |
| 6 | API contract & streaming | Any API or frontend work |
| 7 | Auth & exposure model | Any auth, bind, or security work |
| 8 | Control actions & the catalog | Any mutating endpoint |
| 9 | Frontend architecture | Any UI work |
| 10 | Deployment & NVIDIA Sync | Deploy, systemd, Sync integration |
| 11 | Known seams | Before writing tests for anything crossing a boundary |
| 12 | Testing strategy | Writing tests |
| 13 | Multi-DGX federation | Fleet or peer work |
| 14 | Service identity & reachability | Anything on the Services page |
| 15 | Launchables & process lifecycle | Launching or stopping workloads |
| 16 | Onboarding & installation | Install, setup, or uninstall |

---

## 1. System overview & runtime shape

One Python process on the DGX, serving one port. Inside it:

```
                      ┌──────────────────────── dgxctl process ────────────────────────┐
  browser ──HTTP/SSE──▶ FastAPI (uvicorn)                                              │
   (tailnet)          │   ├─ auth middleware ──▶ token + tailscale whois               │
                      │   ├─ /api/*  ──reads──▶ SnapshotStore (in-memory, last-known)  │
                      │   ├─ /api/stream (SSE) ◀─subscribes─ SnapshotStore             │
                      │   ├─ /api/actions/* ──▶ ActionRunner ──▶ Docker / signals      │
                      │   └─ /  (static SPA from web/dist)                             │
                      │                                                                │
                      │   Poller (asyncio) ──schedules──▶ Collectors ──writes──▶ Store │
                      │                                     │                          │
                      │                            HistoryStore (SQLite, WAL)          │
                      └────────────────┬───────────────────────────────────────────────┘
                                       │  NVML · /proc via psutil · Docker socket
                                       │  `ss` · `tailscale` CLI · HF cache filesystem
```

**The load-bearing decision: collectors never run on the request path.** The poller runs them on
independent intervals and writes results into the store; requests read the store. This is what buys
N2 (200 ms warm reads) and N3 (a hung `docker stats` cannot hang the API).

**Concurrency model.** One asyncio event loop. Blocking work — NVML calls, the Docker SDK,
subprocess invocations, filesystem walks — runs in a bounded thread pool via `asyncio.to_thread`,
never inline on the loop. The model-scan collector (R5.5) additionally chunks its work so a cold
150 GB scan yields between directories.

**Degradation is first-class.** Every collector result is `CollectorResult{status, data, error,
collected_at, duration_ms}`. `status ∈ {ok, degraded, error, unavailable}`. `unavailable` means the
data source does not exist on this host (no Tailscale installed, no Docker socket) and is a
permanent, non-alarming state — distinct from `error`, which is a transient failure worth surfacing.

## 2. Repository layout

```
dgx-control/
├── README.md  CLAUDE.md  LICENSE  config.example.toml  pyproject.toml  openapi.json
├── docs/                           # spec, architecture, SDD, audit, prior art, screenshot
├── src/dgxctl/
│   ├── main.py                     # app factory, lifespan, static mount, shutdown signal
│   ├── cli.py                      # serve | onboard | expose | doctor | token | sync | schema
│   ├── config.py                   # Settings; ~/.config/dgxctl/config.toml
│   ├── auth.py                     # bearer token, tailscale identity, bind guard
│   ├── schemas.py                  # ALL response models — the API contract
│   ├── store.py  history.py  poller.py
│   ├── onboarding.py               # §16 detection, bind options, PATH wiring
│   ├── nvidia_sync.py              # §16 Sync custom-tool registration
│   ├── services_catalog.py         # §14 what each service kind IS
│   ├── reachability.py             # §14 where a service can be reached from
│   ├── endpoints.py                # §14 credentials + host address inventory
│   ├── processes.py                # §15 launching and tracking host processes
│   ├── catalog.py                  # §8, §15 container and process entries
│   ├── doctor.py  docker_client.py
│   ├── collectors/                 # gpu processes containers images disk
│   │   └── network tailscale services models pyenvs   (+ base.py, util.py)
│   ├── actions/runner.py           # the only mutation path
│   └── api/routes.py
├── catalog/default.toml            # launchable entries (vllm-spark, jupyterlab)
├── web/                            # React + Vite + TS; src/reachability.ts mirrors §14
├── deploy/                         # dgxctl.service, install.sh, uninstall.sh, sync launch
├── scripts/live_verify.py          # SDD-053 live checks against real hardware
└── tests/                          # unit/ integration/ fixtures/ (captured real output)
```

## 3. Collector framework

```python
class Collector(ABC):
    name: str  # stable key in the snapshot payload
    interval: float  # seconds; per-collector, see table below
    timeout: float  # hard cap; exceeded → status=error, last good data retained

    async def collect(self) -> Any: ...  # returns the section payload, or raises
    async def available(self) -> bool: ...  # False → status=unavailable, never scheduled again
```

Rules, all of them load-bearing:

- **A collector never raises to the poller.** `base.py` wraps `collect()` in try/except/timeout and
  converts everything to a `CollectorResult`. A bug in one collector cannot stop the others.
- **On error, the previous good `data` is retained** in the store with the new error attached, so the
  UI shows stale-but-labelled data rather than an empty panel.
- **No shell strings.** Subprocess calls use argument lists (S8). There is a single
  `run_cmd(argv, timeout)` helper; nothing else spawns processes.
- **Collectors are pure readers.** Mutation lives in `actions/` exclusively.

Intervals — deliberately tiered, because N1 caps us at 2% of a core:

| Collector | Interval | Why |
|---|---|---|
| gpu | 2 s | The headline number; cheap (NVML) |
| processes | 5 s | `/proc` walk is the most expensive frequent collector |
| containers | 5 s | `docker stats` is expensive — see §11 seam |
| network, tailscale | 15 s | Exposure changes are rare but must not be stale for long |
| images, disk, services, pyenvs | 60 s | Slow-moving |
| models | 600 s + on-demand | Filesystem walk of ~150 GB; incremental with mtime cache |

## 4. Per-collector data sources

Concrete commands and libraries. Capture real output from a live DGX Spark into `tests/fixtures/` for
each of these — parsers get tested against real bytes, never invented ones.

- **gpu** — `pynvml`. `nvmlDeviceGetUtilizationRates`, `GetMemoryInfo`, `GetTemperature`,
  `GetPowerUsage`, `GetClockInfo`. **GB10 caveat:** memory is unified; `nvmlDeviceGetMemoryInfo`
  reports against the shared 121 GB pool. Cross-check against `psutil.virtual_memory()` and present
  one pool (R1.5) — never sum them as if they were separate.
- **processes** — `psutil` for PID/cmdline/user/RSS/CPU; `nvmlDeviceGetComputeRunningProcesses`
  for GPU memory per PID. Container attribution reads `/proc/<pid>/cgroup` and matches the
  container id substring against the container list.
- **containers/images** — `docker` Python SDK over `/var/run/docker.sock`. Port bindings come from
  `attrs["NetworkSettings"]["Ports"]`, whose `HostIp` is the field that distinguishes a loopback
  publish from an exposed one (R2.3).
- **disk** — `psutil.disk_partitions` / `disk_usage`; sized roots via cached `du -sb` on the Docker
  data root, `~/.cache/huggingface`, `~/projects`; `docker.df()` for reclaimable (R3.3).
- **network** — `ss -tulnpH`. Parse into `(proto, bind_ip, port, pid, process)`. Classify bind:
  `127.0.0.0/8 → loopback`, the tailnet address → `tailnet`, LAN address → `lan`, `0.0.0.0`/`::` →
  `all` (the finding case, R6.2).
- **tailscale** — `tailscale status --json`. Never parse the human-readable form.
- **services** — join network's listeners with processes and containers, classify by cmdline
  pattern, then probe `GET /v1/models` (R4.3) with a 2 s timeout on loopback only.
- **models** — HF cache: walk `~/.cache/huggingface/hub/models--*/snapshots/*`, read `config.json`
  for R5.4 facts. Ollama: `ollama list` if the binary exists. Scan roots from config for
  `*.gguf`/`*.safetensors`. Cache by `(path, mtime, size)`; only rescan changed entries.
- **pyenvs** — find `pyvenv.cfg` and conda envs under configured roots. GPU capability is
  determined by **inspecting the env's installed torch distribution metadata on disk**, not by
  importing torch (N1, and importing torch in-process would allocate CUDA context).

## 5. Snapshot store & history

`SnapshotStore` holds `dict[str, CollectorResult]` plus a monotonic version counter, guarded by an
`asyncio.Lock`. Writers are poller tasks; readers are request handlers. Subscribers are
`asyncio.Queue`s with `maxsize=1` and **drop-oldest** semantics — a slow browser must never apply
backpressure to the poller.

`HistoryStore` is SQLite at `~/.local/share/dgxctl/history.db`, one table of
`(ts, metric, value)` for a small fixed metric set (GPU util, GPU mem, CPU, unified mem, per-mount
disk %). Mandatory pragmas on **every** connection: `journal_mode=WAL`, `busy_timeout=5000`,
`synchronous=NORMAL`. A prune task deletes rows older than the retention window and runs
`incremental_vacuum` to honour N7's size ceiling. Tests use a unique temp file per test — never
`:memory:?cache=shared`, which is one process-wide database.

## 6. API contract & streaming

Single origin. Everything under `/api/*`; anything else serves the SPA.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | none | Liveness only — version and uptime. **No host data** (S1) |
| GET | `/api/snapshot` | token | Full current snapshot, all sections |
| GET | `/api/section/{name}` | token | One section (cheaper polls) |
| GET | `/api/stream` | token | SSE; `snapshot` events on change, `ping` every 15 s |
| GET | `/api/history?metric=&window=` | token | Time series for charts |
| GET | `/api/containers/{id}/logs` | token | Bounded streaming log tail (R2.5) |
| GET | `/api/catalog` | token | Launchable entries (R2.8) |
| POST | `/api/actions/container/{id}/{start\|stop\|restart}` | token + control | R2.6 |
| POST | `/api/actions/launch/{entry}` | token + control | R2.7 |
| POST | `/api/actions/process/{pid}/kill` | token + control | S6 |
| GET | `/api/actions/log` | token | The action audit log (S7) |

**Envelope** — every section response, uniformly:

```json
{ "status": "ok|degraded|error|unavailable", "data": {...}|null,
  "error": null|"message", "collected_at": "2026-08-30T12:00:00Z", "duration_ms": 12 }
```

The frontend renders `error`/`unavailable` per panel. There is no global error state.

**SSE auth note (a real seam).** `EventSource` cannot set an `Authorization` header. The stream
therefore accepts the token via a short-lived, single-use ticket obtained from
`POST /api/stream-ticket` and passed as a query parameter — *not* the long-lived token in the URL,
which would leak into logs and browser history. Tickets expire in 30 s and are consumed on connect.

Schema ownership: `schemas.py` is the contract; the frontend's TypeScript types are **generated**
from the OpenAPI schema, never hand-maintained (§11 seam).

## 7. Auth & exposure model

Implements S1–S9. The chain, in order, on every request:

1. `/api/health` → allow, unconditionally, returning no host data.
2. Bearer token compared with `hmac.compare_digest`. Missing/wrong → 401, generic body.
3. If `tailscale_allowlist` is non-empty: resolve the peer IP via `tailscale whois --json <ip>`,
   reject unless the identity matches. Results cached 60 s. Misses logged with the identity (S4).
4. For `/api/actions/*`: require `control_enabled` and log to the action log.

**Startup bind guard (S3)** — in `main.py`'s lifespan, before uvicorn binds: if `host` is not in
`{127.0.0.1, ::1, localhost}` and no token file exists at `~/.config/dgxctl/token`, raise and exit
with a message naming `dgxctl token --init`. This is a hard fail, not a warning. It is the single
control standing between this service and the shared tailnet, so it gets its own test (§12).

Token: 32 bytes from `secrets.token_urlsafe`, file mode `0600`, verified on read — a token file with
looser permissions is refused. Never logged, never in an error body, never in a URL.

## 8. Control actions & the catalog

`ActionRunner.run(action, actor, target)` is the only mutation path. It checks the gate, executes,
appends to the action log (JSONL at `~/.local/share/dgxctl/actions.jsonl`), and returns a result
envelope. No action is silent.

**Catalog** (`catalog/default.toml`, overridable at `~/.config/dgxctl/catalog.toml`):

```toml
[[entry]]
id = "vllm-server"
name = "vLLM model server"
image = "vllm-spark:local"          # NOT nvcr.io/nvidia/vllm:26.07-py3 — see below
port = 8010
bind = "127.0.0.1"                  # exposing beyond loopback requires editing this (R2.9)
env = { VLLM_USE_DEEP_GEMM = "0" }  # sm_121 requires DeepGEMM off
volumes = ["~/.cache/huggingface:/root/.cache/huggingface"]
runtime = "nvidia"
gpu_memory_utilization = 0.50       # budgeted; see the guard below
args = ["vllm","serve","{model}","--host","0.0.0.0","--port","{port}",
        "--kv-cache-dtype","fp8","--max-num-batched-tokens","8192","--enable-prefix-caching"]
params = [{ name = "model", kind = "model_ref", required = true }]
```

Three host-specific rules the catalog loader **enforces**, because getting them wrong costs hours:

1. **Image pin.** vLLM images from `26.07-py3` onward require driver 610.43+; this box runs
   580.159.03 and dies with a misleading `UnicodeDecodeError` out of torch's op registry. Only
   `vllm-spark:local` is known-good. The loader warns on any un-pinned vLLM image.
2. **Unified-memory budget guard.** Before launching an entry with `gpu_memory_utilization`, sum it
   with the values of already-running catalog-launched servers. If the total exceeds `0.70`, refuse
   with a message naming the running servers. Unified memory means an over-reservation starves
   Docker, Hermes, and the OS page cache — not just the GPU.
3. **Bind default.** Port publishing always uses `-p {bind}:{port}:{port}` with `bind` defaulting to
   `127.0.0.1`. A bare `-p {port}:{port}` binds `0.0.0.0` and is a bug, not a shortcut.

Process kill (S6) refuses: PID 1, kernel threads (no cmdline), any PID not owned by the service
user, and any PID in the service's own process tree.

## 9. Frontend architecture

React 19 + TypeScript + Vite + Tailwind. Builds to `web/dist`, served by FastAPI (R7.3). See
[spec_frontend.md](spec_frontend.md) for the numbered `FE-N` requirements.

- **One data source.** A single `SSEProvider` owns the stream and exposes sections via context.
  Components never fetch the same data independently; the stream is the only live path.
- **Reconnect with backoff** and an explicit connection indicator. Every panel renders from
  last-known data with a staleness badge, never a spinner-forever.
- **Section-level error boundaries.** A section with `status: error` renders its own error card; the
  rest of the page stays live.
- **Types are generated** from OpenAPI into `web/src/api/types.gen.ts`. Regenerating is a build
  step; hand-editing that file is prohibited.
- **The exposure signal is visual and consistent**: loopback / lan / tailnet / **all** rendered with
  the same colour vocabulary in every panel that shows a bind (containers, network, services). A
  `0.0.0.0` bind must be impossible to overlook.
- Dev runs Vite on its own port proxying `/api` — remember this masks production single-origin
  routing bugs (§11). The production serving path is tested separately.

## 10. Deployment & NVIDIA Sync

`systemctl --user` unit at `~/.config/systemd/user/dgxctl.service`; lingering is already enabled on
this box so it survives logout (N6). No system unit, because that needs `sudo`.

**NVIDIA Sync registration (R7).** Sync's *Add Custom* dialog takes **Name**, **Port**, optional
*auto-open in browser at a URL path*, a **bash launch script**, and a *launch in terminal* toggle.
Values to enter are in `README.md`; the script is `deploy/nvidia-sync-launch.sh`, and it must:

- start the service on the configured port and **exit 0 without duplicating** if already listening
  (R7.4) — check with `ss -tln` on the port before acting;
- work in background mode (terminal toggle off), so it must not require a TTY and must not block;
- print the URL including the token-bearing path so the auto-open lands authenticated.

Deploy = promote `develop` → `main`, then on the box `git pull && ./deploy/install.sh &&
systemctl --user restart dgxctl`, then run the live verification checklist (SDD-053).

## 11. Known seams

Production bugs live at seams. Each of these gets at least one test exercising the **real** other
side, because mocks on both sides can share the same wrong assumption.

| Seam | The wrong assumption that will bite | Test that catches it |
|---|---|---|
| NVML PID ↔ psutil PID | NVML reports the PID in the **host** namespace; a containerized process's in-container PID differs. Matching the wrong one silently attributes GPU memory to nothing. | Fixture from a real containerized vLLM server; assert attribution resolves to the container |
| `/proc/<pid>/cgroup` ↔ Docker container id | cgroup v2 paths differ from v1; the id is a substring, not the whole field | Real cgroup file fixtures, both versions |
| `ss` output ↔ parser | Column layout shifts with flags; IPv6 `[::]:8010` and `*:8010` are both "all" | Captured real `ss -tulnpH` output, incl. IPv6 |
| `tailscale status --json` ↔ schema | Fields move between versions; human output is not stable | Real JSON fixture; parse defensively, tolerate missing keys |
| Docker port bindings ↔ exposure | `HostIp: ""` means **0.0.0.0**, not "unknown". Treating empty as loopback inverts the safety signal. | Explicit test: empty `HostIp` classifies as `all` |
| Unified memory ↔ two-pool assumption | Summing GPU memory and system memory double-counts the same 121 GB | Assert reported total ≤ physical total |
| OpenAPI schema ↔ TS types | Hand-edited types drift from the server | CI check: regenerate and assert no diff |
| SSE auth ↔ `EventSource` | Header auth is impossible in `EventSource`; a naive fix puts the real token in the URL | Test that the long-lived token is rejected as a query param |
| Vite dev proxy ↔ production single-origin | Dev proxy hides prod-only route/base-path bugs | One test that hits the built SPA through FastAPI, not Vite |
| Config bind ↔ actual socket | The guard checks config while uvicorn binds something else | Bind-guard test asserting the **listening socket**, not the setting |

## 12. Testing strategy

- **Unit** — parsers against captured real fixtures; collector error paths; the memory-budget guard;
  the kill-refusal matrix; classifier bind logic.
- **Integration** — FastAPI `TestClient`: auth on every route (a parametrized test enumerating the
  route table asserts each requires a token, so a new unauthenticated route fails CI), envelope
  shape, SSE ticket lifecycle, control gate off by default.
- **Live** — against real hardware via `scripts/live_verify.py` (SDD-053). The suite cannot see
  driver quirks, real cgroup layouts,
  or a genuinely exposed socket. The first live run is expected to find things.
- Tests **never bind a real port** (a deployed service may hold it) and never read the wall clock in
  assertions.

---

## 13. Multi-DGX federation

**Status: implemented for read; the UI switches nodes. Control actions are local-only.**

One instance can aggregate peers so several Sparks appear in one browser tab. The design
rule is that **a peer is just another dgxctl instance** — there is no separate agent, no
second protocol, and no privileged channel. Federation reuses the same authenticated REST
API a browser uses.

```
  browser ──SSE──▶ dgxctl @ spark-1  ──HTTPS + peer token──▶ dgxctl @ spark-2 /api/snapshot
   (aggregator)         │                                  ──HTTPS + peer token──▶ spark-3
                        └── SnapshotStore keyed by node_id
```

Configuration on the aggregator:

```toml
node_id   = "spark-1"          # this machine's id in the UI
node_name = "Lab Spark"

[[node]]
id         = "spark-2"
name       = "Spark by the window"
url        = "http://spark-2.tailnet.ts.net:8770"
token_file = "~/.config/dgxctl/peers/spark-2.token"   # or token = "..."
```

Design decisions and why:

- **Store is keyed by node id.** `SnapshotStore` holds `{node_id: {section: Envelope}}`, so
  a peer's data can never bleed into the local node's. `GET /api/snapshot?node=spark-2`.
- **Peers are polled, not streamed.** The aggregator holds one SSE stream to the browser and
  polls peers over REST on `intervals.remote` (default 10 s). Streaming peer-to-peer would
  multiply long-lived connections for data that is already interval-sampled.
- **An unreachable peer is a `NodeInfo` with `reachable: false` and an error string** — never
  an exception, and never a gap in the local node's data. This is the same degradation
  contract collectors follow.
- **Peer tokens are stripped from `GET /api/config`.** A browser must never receive a
  credential for another machine.
- **Control actions are deliberately local-only.** Acting on a remote host through an
  aggregator doubles the blast radius of a compromised token and makes the action log
  ambiguous about who did what. Operate a peer through its own UI, which is one click away
  in the node switcher.
- **The local node id is configurable** so a fleet does not present three machines all
  called "local".

Not yet built (each is a separate SDD when wanted): peer discovery via Tailscale, fan-out
control actions, cross-node history, and a fleet overview page aggregating all nodes.


---

## 14. Service identity & reachability

Two questions the Services page exists to answer, kept deliberately separate.

### What is this thing?

`services_catalog.py` is the only place that knows. Each `Kind` carries a display label, a
one-line summary of what it is, a category (`llm` | `notebook` | `agent` | `tool` |
`infrastructure`), the browsable path, an OpenAI API path where one exists, and whether a browser
is the right client at all. Anything absent from the catalog is `unknown`.

**Classification order is command line → process name → port.** That order is the whole point:

- A port cannot tell eight ZMQ ports of one notebook kernel from eight services. The command line
  can — they all say `ipykernel_launcher`.
- A port gets the interesting case backwards: a vLLM server on 8888 is a model server, not a
  notebook.
- The port is still needed as a last resort, because an unprivileged `ss` shows no pid for another
  user's socket, leaving the port as the only evidence.

One heuristic sits outside the catalog: an unidentified listener bound to the node's **own tailnet
address** is the Tailscale daemon, because nothing else binds there.

Category decides visibility. `infrastructure` and `unknown` are hidden by default but **always
present in the payload** — dropping them would make the exposure audit (R6.2) a lie.

### Where can it be reached from?

`reachability.py` is a **pure function** of (service bind, port, viewer origin, host addresses).
It is mirrored in `web/src/reachability.ts` with a matching test suite, because the server cannot
compose the URL — only the browser knows how the viewer arrived — and the logic is too easy to get
subtly wrong to leave un-mirrored.

The matrix, which replaced a single boolean ("is the viewer local?") that was wrong in both
directions:

| Service bind | Viewer on loopback | Viewer on LAN | Viewer on tailnet |
|---|---|---|---|
| `0.0.0.0` | direct, **plus** LAN and tailnet URLs | LAN address(es) | MagicDNS name |
| loopback | direct **if on the box**, else forward | port-forward, naming the LAN address | port-forward, naming the tailnet name |
| Docker bridge | same as loopback — reachable only from the host | port-forward | port-forward |
| tailnet address | unreachable, explained | unreachable, explained | direct |

The load-bearing case is the first column. **A viewer at `127.0.0.1` is ambiguous and the server
cannot resolve it**: NVIDIA Sync's port forward and a browser running on the DGX produce an
identical origin. The page states both possibilities rather than guessing, because guessing is
wrong half the time.

A forward command always names an address the viewer can actually reach — never a `<host>`
placeholder — and `endpoints.host_addresses()` supplies the candidates: loopback, every routable
LAN address (Docker bridges and the tailnet excluded, since nobody sits there), and the Tailscale
address and MagicDNS name.

### Credentials

Where a service publishes its own credential locally, it is folded into a working link:
JupyterLab's token comes from `~/.local/share/jupyter/runtime/jpserver-<pid>.json`, matched
against a live pid — Jupyter leaves that file behind when it dies, and a stale one would produce a
confident link to nothing. The token reaches an already-authenticated browser but renders masked
(FE-C11): the mask protects against a shoulder or a screenshot, not against the reader.

## 15. Launchables & process lifecycle

Catalog entries declare `kind = "container"` or `kind = "process"`. Process entries exist because
NVIDIA Sync's own dashboard runs JupyterLab from a host virtualenv — containerising it would add
plumbing and remove the direct GPU access that makes it useful.

Commands come only from the catalog; only declared params are substitutable, and substitution
produces argv, never a shell string.

**Identity is the port, not the executable.** Matching a running instance by executable adopted an
unrelated `python3` process and refused a valid launch. Matching the full argv would be worse: a
JupyterLab started by Sync uses different flags than the entry declares, which would break the
adoption that matters most. So: the port decides; the executable is a secondary hint, ignored
entirely for shared interpreters (`python`, `sh`, `node`, …); a port held by something else is
reported as a **conflict**, which is a different failure from "already running" and sends the
operator somewhere different.

**dgxctl owns what it launched.** Launched processes share the service's cgroup, so stopping or
restarting dgxctl stops them. This is deliberate: `KillMode=process` would let a restart bypass the
Stop button, leaving dgxctl believing it manages workloads it no longer controls. Processes started
outside dgxctl are in a different cgroup and are never affected — which is exactly the distinction
the adoption logic already draws.

## 16. Onboarding & installation

`deploy/install.sh` is unprivileged end to end — no `sudo` anywhere, because on many DGX systems
sudo is password-protected and nothing here needs root. It creates a virtualenv, installs the
package, builds the UI when Node is present (warns and continues when it is not), ships the systemd
unit inside the package, and hands over to `dgxctl onboard`.

`onboarding.py` splits detection and decision from prompting, so the interesting part is testable
without a TTY:

- `detect()` returns an `Environment` describing what the machine offers. It is **read-only** — it
  runs before the user has agreed to anything, and there is a test asserting it creates nothing.
- `bind_options(env)` is a pure function returning the exposure choices to present. A machine with
  no Tailscale is never offered a tailnet option; installed-but-logged-out is reported distinctly
  from absent, because those are three states, not two.
- Choosing a non-loopback bind generates the token **in the same step**, so onboarding can never
  finish in a state the S3 bind guard would refuse to start.
- A re-run preserves everything onboarding does not manage. It owns exactly `host`, `port`,
  `node_name`, `control_enabled` and `tailscale_allowlist`; declared services, peer nodes,
  intervals and scan roots are carried across verbatim.

`ensure_on_path()` makes `dgxctl` runnable by name: a symlink into `~/.local/bin`, which most
distributions already have on PATH, and only when it does not does it append a guarded line to the
shell files that exist. Two facts shaped it — bash reads `.profile` at login but `.bashrc` only for
interactive non-login shells, so `.profile` is created when nothing a login shell reads exists; and
`export PATH="~/.local/bin:$PATH"` is broken because a tilde inside double quotes does not expand.
It refuses to link into a build sandbox, having once pointed a real install at a `uv` build venv
that was later reclaimed.

`deploy/uninstall.sh` is the counterpart: `--dry-run` to preview, config and history kept unless
`--purge`, and it refuses to remove a `~/.local/bin/dgxctl` it did not create.
