# spec.md — DGX Control

Product Requirements. Owner-editable. All work aligns with this document.

**Status:** v1 implemented · **Target hardware:** NVIDIA DGX Spark (GB10, aarch64, Ubuntu 24.04)

---

## 1. Goal

DGX Spark is an excellent local compute box that people usually reach over SSH. Existing tooling
(NVIDIA Sync's DGX Dashboard) gives a basic view — RAM, GPU utilization — and stops there.

**DGX Control** is a utility that runs *on* the DGX and exposes a web interface providing far more
granular observability **and safe control** of the machine. It registers into NVIDIA Sync as a
custom tool so it is reachable from the same place people already look.

### Non-goals (v1)

- Fleet *management*. Several Sparks can be **observed** from one instance (R9), but control
  actions stay local to each box.
- Anything requiring `sudo`. Sudo on this box is password-protected with no passwordless entry;
  the service runs unprivileged as `nvidia` and must degrade gracefully where root is needed.
- Replacing Prometheus/Grafana. Retention is short and local; this is an operator console.
- Editing host configuration (Tailscale ACLs, firewall rules, driver/package installs).

---

## 2. Users & primary scenarios

Single operator (the box owner), occasionally a collaborator on the tailnet.

| Scenario | What they need |
|---|---|
| "Why is the GPU pinned?" | Utilization *and* the process/container responsible |
| "What's eating my 121 GB?" | Per-container and per-process memory, and the unified-memory budget |
| "Can I start another model server?" | Free unified memory vs. what running vLLM servers reserve |
| "What's running and on which port?" | Agent/service inventory with ports, bind address, and links |
| "Do I already have that model?" | Model inventory across HF cache and other sources, with sizes |
| "Is anything exposed to the tailnet?" | Listening sockets with bind address, flagged when not loopback |
| "Stop that runaway container" | Reversible lifecycle control without opening an SSH session |

---

## 3. Functional requirements

Each requirement is referenced by id from `architecture.md`, `SDD.md`, and commit messages.

### R1 — GPU observability

- **R1.1** Report GPU utilization, memory used/total, temperature, power draw, and clocks, sampled
  at a configurable interval (default 2 s).
- **R1.2** Attribute GPU memory and compute to the owning process: PID, command, user, start time.
- **R1.3** Rank processes by GPU consumption so the top consumer is identifiable at a glance.
- **R1.4** Map each GPU process to its owning Docker container where one exists.
- **R1.5** Present unified memory honestly: on GB10 the 121 GB pool is shared by CPU and GPU. Show
  the single pool with its breakdown, never as two independent budgets.
- **R1.6** Show short-horizon history (default 60 min) for utilization and memory.

### R2 — Docker observability and control

- **R2.1** List running and stopped containers: name, image, status, uptime, restart policy.
- **R2.2** Per-container resource usage: CPU %, memory usage and limit, network and block I/O.
- **R2.3** Show each container's published port mappings **including the host bind address**, so a
  `0.0.0.0` publish is visibly distinct from `127.0.0.1`.
- **R2.4** List locally available images: repository, tag, size, created, and whether in use.
- **R2.5** Tail container logs from the web UI (bounded, streaming).
- **R2.6** Lifecycle control: start, stop, restart a container. Reversible actions only.
- **R2.7** Launch a container from a **curated catalog** of known-good configurations (see R2.8),
  never from free-form user-supplied `docker run` arguments.
- **R2.8** The catalog is a declarative, version-controlled file of launchable entries (image, args,
  port, memory budget). It ships with the known-good `vllm-spark:local` serving template and a
  Jupyter entry.
- **R2.9** Every launch published port defaults to a loopback bind; exposing a launched container
  beyond loopback requires an explicit per-entry opt-in in the catalog file.

### R3 — Storage

- **R3.1** Per-filesystem usage: mount point, device, size, used, free, percentage.
- **R3.2** Highlight the large consumers that matter on this box: Docker data root, the HuggingFace
  cache (`~/.cache/huggingface`), and `~/projects`.
- **R3.3** Report Docker's own reclaimable space (images, containers, volumes, build cache).
- **R3.4** Warn when a filesystem crosses a configurable threshold (default 85%).

### R4 — AI agent / service inventory

- **R4.1** Discover services running on the box and present them as an inventory: name, PID or
  container, listening port, bind address, uptime.
- **R4.2** Classify known kinds where identifiable — vLLM / OpenAI-compatible server, Jupyter,
  Ollama, Hermes (`hermes serve`, `hermes gateway`), generic HTTP.
- **R4.3** For OpenAI-compatible endpoints, probe `/v1/models` and show the served model names.
- **R4.4** Provide a reachable link for each service, correct for how the user is reaching the
  dashboard (loopback vs. tailnet address).
- **R4.5** Health status per service: reachable, unreachable, or unprobed.

### R5 — Model inventory

- **R5.1** Enumerate models in the HuggingFace cache: repo id, revision, on-disk size, last used.
- **R5.2** Enumerate other local sources: Ollama models, loose GGUF/safetensors under configured
  scan roots.
- **R5.3** Show total size per source and per model, and which models are currently *served* by a
  running service (join with R4).
- **R5.4** Surface per-model config facts that drive serving decisions on this box:
  `max_position_embeddings`, parameter count, quantization, and MoE active-parameter count where
  the config exposes it.
- **R5.5** Model scanning is incremental and cached; a cold scan of a ~150 GB cache must not block
  the API.

### R6 — Network and exposure

- **R6.1** List listening TCP/UDP sockets: port, protocol, bind address, owning process/container.
- **R6.2** **Flag every non-loopback bind as a finding**, with the owning process named.
- **R6.3** Report Tailscale state: this node's tailnet IP and name, backend state, exit-node status,
  and the peer list with online status.
- **R6.4** Distinguish "listening on loopback", "listening on the tailnet", and "listening on the
  LAN" as three separate exposure levels in the UI.
- **R6.5** Read-only for v1. No Tailscale or firewall mutation.

### R7 — NVIDIA Sync integration

- **R7.1** Register as an NVIDIA Sync custom tool via its *Add Custom* dialog, which accepts:
  **Name**, **Port**, an optional *auto-open in browser at a URL path*, a **bash launch script**,
  and a *launch in terminal* toggle.
- **R7.2** Ship the launch script (`deploy/nvidia-sync-launch.sh`) that starts the service on the
  configured port and exits cleanly when run in Sync's background (non-terminal) mode.
- **R7.3** Serve the entire UI and API from **one port** — no second process, no separate frontend
  server — because the dialog accepts exactly one port.
- **R7.4** Be idempotent: if the service is already running on the port, the launch script must
  succeed without starting a duplicate.
- **R7.5** Document the exact field values to enter in the dialog in `README.md`.

### R10 — Launchable host processes

Not everything worth launching is a container. NVIDIA Sync's own DGX Dashboard runs JupyterLab
from a **host virtualenv**, because that is what gives a notebook direct GPU access without
container plumbing.

- **R10.1** Catalog entries declare `kind = "container"` or `kind = "process"`. Process entries
  launch a declared argv on the host, never a free-form command from the browser.
- **R10.2** A launched process is detached (its own session), survives the request, and records
  its pid, entry id, start time and log path so it can be listed and stopped later.
- **R10.3** stdout/stderr are captured to a per-entry log file readable from the UI.
- **R10.4** If an instance of an entry is **already running** — including one started outside
  dgxctl — it is adopted and shown rather than duplicated. Launching is refused with the
  existing instance named.
- **R10.5** Stopping a launched process obeys the same refusal rules as any process kill (S6).
- **R10.8** **dgxctl owns what it launched.** Stopping or restarting the service stops the host
  processes it started — they share its cgroup deliberately, so that a restart cannot bypass the
  Stop button and leave workloads running that dgxctl believes it manages. Processes started
  outside dgxctl are in a different cgroup and are never affected.
- **R10.6** A JupyterLab entry ships by default, targeting a virtualenv chosen from the
  environments R8.1 already discovers, defaulting to the conventional `~/jupyterlab/.venv`.
- **R10.7** Process entries bind loopback by default, exactly as container entries do (R2.9).

### R15 — Service inventory that explains itself

The Services page is the answer to "what is running and how do I use it". A list of ports is not
that. Ports the operator did not start and cannot act on are noise, and noise is what stops the
page being read at all.

- **R15.1** Every service shown carries a **name, a one-line explanation of what it is, and a
  category**. If dgxctl cannot say what something is, it does not belong in the default view.
- **R15.2** Services are grouped by category: **model servers**, **notebooks**, **agents**,
  **tools**. Infrastructure and unrecognised listeners are collapsed out of the way, reachable
  behind one toggle, never silently dropped from the payload.
- **R15.3** Recognition uses the listener's **command line**, not just its port or process name —
  eight ZMQ ports belonging to one Jupyter kernel are one notebook's plumbing, not eight services.
- **R15.4** Known infrastructure is classified as such by name: SSH, DNS, mDNS, CUPS, Tailscale's
  own listeners, Docker's proxies, and an agent runtime's internal proxy.
- **R15.5** Model servers state the **OpenAI base URL and the model name** a client needs.
- **R15.6** Services with their own credential (Jupyter) show it, per R11.3.
- **R15.7** Agents (Hermes, OpenClaw, and declared ones) are listed as agents, with how to connect
  — which for some is a desktop app or CLI, not a browser.

### R16 — Reachability, told correctly

A URL is only correct relative to **where the viewer is** and **what the service is bound to**.
Getting this wrong sends people to a link that silently resolves on their own laptop.

- **R16.1** dgxctl reports the machine's own addresses — loopback, every LAN address, and the
  Tailscale address and MagicDNS name — so a URL can be composed for the viewer's position.
- **R16.2** For a viewer reached over the **LAN**: a service bound to all interfaces is linked at
  the DGX's LAN address; a loopback-bound service gets a port-forward command instead.
- **R16.3** For a viewer reached over the **tailnet**: the same, using the tailnet name.
- **R16.4** For a viewer at **127.0.0.1** — which is what NVIDIA Sync and SSH tunnels produce —
  the page cannot tell "browser on the DGX" from "browser forwarded to it". It states both: the
  direct link that works on the box, and the forward needed otherwise.
- **R16.5** A port-forward command names an address the **viewer** can actually reach, not
  `<host>`.
- **R16.6** A service bound to a Docker bridge address is reachable only from the host, and is
  treated like loopback for any remote viewer.
- **R16.7** Where a service simply cannot be reached from the viewer's position, the page says so
  and gives the command that fixes it, rather than offering a link that will fail.

### R11 — Access endpoints

The point is not to know a service exists; it is to be one click from using it, without going
somewhere else to find out how.

- **R11.1** Every discovered or declared service exposes an **access endpoint**: a URL that is
  correct for the machine the viewer is on.
- **R11.2** Where a service publishes its own credential locally — JupyterLab writes a token to
  its runtime file — that credential is read and folded into a working link.
- **R11.3** Credential-bearing links are **masked until revealed or copied**. The dashboard is
  already authenticated, so the reader is trusted; a shoulder or a screenshot is not.
- **R11.4** For a loopback-bound service viewed remotely, a ready-to-copy SSH tunnel command is
  offered instead of a link that would resolve on the wrong machine.
- **R11.5** Services that speak an OpenAI-compatible API additionally surface the `base_url` and
  model name a client needs.
- **R11.6** Where a credential cannot be read, the UI says how to obtain it rather than showing a
  link that will fail.

### R12 — Declarable services

- **R12.1** Services that cannot be auto-detected are declarable in config: id, name, port, path,
  and an optional launch argv.
- **R12.2** A declared service that is not listening is shown as **offline**, not hidden, so its
  link and launch control are still reachable.
- **R12.3** A declared launch command is subject to the same control gate and action log as any
  other action.

### R13 — NVIDIA Sync registration

- **R13.1** `dgxctl sync register` writes an entry into NVIDIA Sync's custom-tool config so a
  service appears in Sync's own UI, removing the hand-typed dialog step (R7.5).
- **R13.2** Registration is **explicit**: dgxctl never rewrites Sync's config on start.
- **R13.3** The existing config is backed up before any write, and existing entries are preserved.
- **R13.4** `sync list` and `sync unregister` complete the loop.
- **R13.5** If Sync is not installed, the command says so and changes nothing.

### R14 — Onboarding a new machine

Anyone with a DGX should be able to install this without reading the architecture first, and
without knowing in advance which of its data sources their machine has.

- **R14.1** A single unprivileged install path: clone, run one script, answer a few questions.
  No `sudo` at any point.
- **R14.2** Onboarding **detects** what the machine offers — GPU/NVML, Docker, `ss`, Tailscale
  (installed, logged in, already serving), NVIDIA Sync, `systemd --user`, lingering — and adapts
  the questions to it. A machine with no Tailscale is never offered a tailnet option.
- **R14.3** The exposure decision is presented as an explicit choice with its consequences
  stated: what each option reaches, and which need root. The default is the safest one.
- **R14.4** Choosing an exposure beyond loopback generates a token in the same step; it is never
  possible to complete onboarding in a state the service will refuse to start in (S3).
- **R14.5** Control actions are a separate, explicit opt-in, defaulting to off (S5).
- **R14.6** NVIDIA Sync registration is offered when Sync is present, and skipped silently when
  it is not (R13.5).
- **R14.7** Onboarding is **idempotent and re-runnable**: it shows current values as defaults and
  backs up any config it replaces.
- **R14.8** Every question has a flag, so the whole thing can run unattended
  (`--yes` plus explicit choices) for scripted or fleet installs.
- **R14.10** Installation makes `dgxctl` runnable **by name**, not only by full path: a symlink
  into `~/.local/bin`, and — only if that directory is not already on PATH — a guarded line in the
  shell files that exist. Login and interactive shells must both work.
- **R14.11** A re-run **preserves everything onboarding does not manage** — declared services,
  peer nodes, intervals, scan roots. Onboarding owns `host`, `port`, `node_name`,
  `control_enabled` and `tailscale_allowlist`, and nothing else.
- **R14.9** It finishes by verifying the service actually answers, and printing the URL(s) to use
  and how to get the token.

### R9 — Multiple DGX systems

- **R9.1** One instance may aggregate peer instances so several DGX systems appear in one
  browser tab, selected by a node switcher.
- **R9.2** A peer is just another dgxctl instance reached over its own authenticated API.
  There is no separate agent, protocol, or privileged channel.
- **R9.3** Each node's data is stored and served separately; a peer's readings can never be
  presented as the local machine's.
- **R9.4** An unreachable peer is reported as unreachable with its error, and never degrades
  the local node's data.
- **R9.5** A peer's token is never served to a browser.
- **R9.6** Control actions are local-only in v1. Operate a peer through its own UI.
- **R9.7** The local node's id and display name are configurable, so a fleet does not present
  every machine as "local".

### R8 — Day-to-day operability

- **R8.1** Inventory Python environments (venv, conda, uv) under configured roots, reporting for
  each whether `torch.cuda.is_available()`-class GPU access is present, torch version, and Python
  version. Detection must be cached and must not import torch in the service process.
- **R8.2** One-click Jupyter: launch the catalog's Jupyter entry and surface its URL and token.
- **R8.3** A `doctor` preflight command that checks every data source (NVML, Docker socket,
  Tailscale CLI, `ss`, HF cache path) and reports which collectors will degrade.

---

## 4. Security requirements

The Tailscale network this box sits on **includes machines belonging to other people**. Tailscale is
not a trust boundary here. The owner has chosen tailnet exposure; these requirements are the price
of that choice and are not optional.

- **S1** Every API route, static asset, and the SSE stream requires authentication. There is no
  unauthenticated route except `GET /api/health`, which returns liveness only and no host data.
- **S2** Authentication is a bearer token generated on first run, stored `0600` at
  `~/.config/dgxctl/token`, never logged, never echoed in an error body.
- **S3** Startup **fails closed**: if the configured bind address is not loopback and no token file
  exists, the service refuses to start with an explanatory message.
- **S4** Optional Tailscale identity allowlist: when enabled, the peer IP is resolved via
  `tailscale whois` and the request rejected unless the identity is on the allowlist. Allowlist
  misses are logged with the identity.
- **S5** Control actions (R2.6, R2.7, R8.2, process kill) are separately gated: they require the
  token *and* `control_enabled = true` in config, which defaults to **false**.
- **S6** Process kill is restricted to processes owned by the service user and refuses PID 1 and
  below, kernel threads (no cmdline), the service's own process, and any **ancestor** of it.
  Children are not refused: a child of the service is by definition a short-lived helper it
  spawned, so refusing them adds no safety while causing false refusals.
- **S7** Every control action is written to an append-only action log with timestamp, identity,
  action, target, and result.
- **S8** No shell string interpolation of user input anywhere. Subprocess calls take argument lists.
- **S9** The service never reads, and never returns, the contents of credential files — `.env`,
  `~/.cache/huggingface/token`, SSH keys — even when they fall inside a configured scan root.

---

## 5. Non-functional requirements

- **N1** Idle CPU cost under 2% of one core; the dashboard must not perturb what it measures.
- **N2** `GET /api/snapshot` responds in under 200 ms warm, served from cache — never by executing
  collectors inline on the request path.
- **N3** A failing collector degrades to a per-section error in the payload; it never fails the
  whole response or crashes the poller.
- **N4** Runs unprivileged. Every capability that would need root is detected and reported as
  unavailable rather than attempted.
- **N5** aarch64-native. No dependency that lacks an `aarch64` wheel or builds from source at
  install time.
- **N6** Survives logout via `systemctl --user` (lingering is already enabled on this box).
- **N8** The repository is publishable. No host-specific value — a machine's hostname, a real
  tailnet or LAN address, a personal home path, a credential — appears in tracked files, including
  in fixtures captured from real machines. This is enforced by a test, not by review.
- **N7** History retention is bounded and self-pruning; the SQLite file has a hard size ceiling.

---

## 6. Out of scope for v1

Alerting and notification delivery · multi-user accounts and RBAC · long-term metric retention ·
remote model download management · Tailscale/firewall mutation · anything requiring `sudo`.

---

## Appendix A — Original brief

The verbatim brief this PRD expands, preserved for reference:

> DGX spark is an amazing local compute that usually people access over SSH. There are tools such as
> NVidia Sync that has features such as DGX Dashboard that provides basic view of the DGX spark such
> as RAM usage and GPU utilization, etc. We want to create a new utility that can run on DGX and
> expose a web interface to provide more granular observability and control of the DGX.
>
> Specifically, these are some key things:
> 1. GPU utilization and which process is utilizing the GPU most
> 2. What Docker container are running on the system and each one's resource usage. What docker image is available for launch, etc.
> 3. Disk usage and free space available
> 4. What AI agents are running on the DGX Spark, their ports, interface etc.
> 5. What AI models are already present in the DGX spark, e.g. through huggingface cache or other sources
> 6. What network and ports are accessible from outside, etc. including configurations related to tailscale
> 7. The utility should be able to added as a custom tool with interface option as detailed in Interface_NVidia_sync.png
>
> There could be more general day-to-day observability, e.g. Python environment available for GPU
> access, standard docker image, Jupyter notebook for quick experimentation, etc.

Mapping: 1→R1, 2→R2, 3→R3, 4→R4, 5→R5, 6→R6, 7→R7, general→R8. R9 (multiple DGX systems)
was added later at the owner's request.
