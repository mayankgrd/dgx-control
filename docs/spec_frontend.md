# spec_frontend.md — DGX Control UI

Numbered `FE-N` requirements. **Every UI change starts from an FE id.** Cross-cutting rules first —
they are BINDING on every page.

## Cross-cutting rules

- **FE-C1 · One shell.** A single app shell owns the nav, the connection indicator, and the page
  frame. Pages never render their own nav.
- **FE-C2 · Panels own their state.** Each panel renders from its section's envelope and handles
  `ok | degraded | error | unavailable` itself. `unavailable` is a calm, muted "not available on
  this host" — not an error. A failing panel never blanks the page.
- **FE-C3 · Staleness is visible, spinners are not.** After first paint, updated data replaces old
  data in place. If a section's `collected_at` is older than 3× its interval, show a staleness badge
  on that panel. Never replace live data with a loading spinner on refresh.
- **FE-C4 · The exposure vocabulary is fixed and global.** `loopback` (neutral) · `lan` (caution) ·
  `tailnet` (caution) · `all / 0.0.0.0` (**alert**). Same colours, same labels, same icon, in every
  panel that shows a bind. This vocabulary is defined once in the design tokens.
- **FE-C5 · Destructive-looking actions confirm.** Stop, restart, kill, and launch each require an
  explicit confirm naming the target. Confirms state what will happen, not "are you sure?".
- **FE-C6 · Control-disabled is explained, not hidden.** When `control_enabled` is false, action
  buttons render disabled with a tooltip naming the config key to change. Hiding them would make
  the product look broken.
- **FE-C7 · Numbers are honest.** Bytes rendered with binary units and a fixed precision; percentages
  never exceed 100; unified memory is shown as **one** pool with a breakdown, never as two bars that
  imply separate budgets.
- **FE-C8 · Mobile-safe.** Usable at 390 px wide — the owner will check the box from a phone. Tables
  degrade to cards; no horizontal page scroll.
- **FE-C9 · Dark-first.** The box's own tooling (NVIDIA Sync) is dark; this opens inside it. Light
  theme is a follow-on, not v1.
- **FE-C10 · Keyboard reachable.** Every action is tab-reachable with a visible focus ring.
- **FE-C11 · Credentials are masked until asked for.** A link that carries a token renders
  masked, with reveal and copy beside it. The link itself still works in one click — the mask
  protects against a shoulder or a screenshot, not against the reader, who is already
  authenticated.

## Pages

### FE-1 · Overview (`/`)

- **FE-1.1** Above the fold, four headline tiles: GPU utilization, unified memory, disk on the
  largest mount, container count.
- **FE-1.2** A sparkline on the GPU and memory tiles from `/api/history`.
- **FE-1.3** A **findings strip**: non-loopback binds (R6.2), filesystems over threshold (R3.4), and
  containers in a restart loop. Empty state is an explicit "no findings" — never a blank space.
- **FE-1.4** Top 5 GPU-consuming processes with their owning container, linking to Containers.
- **FE-1.5** Every tile links to its detail page.

### FE-2 · GPU (`/gpu`)

- **FE-2.1** Utilization, memory, temperature, power, clocks as live charts over the history window.
- **FE-2.2** Process table: PID, command, user, GPU memory, CPU %, RSS, container, uptime — sortable,
  default sorted by GPU memory descending.
- **FE-2.3** Kill action per row, subject to FE-C5/FE-C6 and the S6 refusal rules; a refused kill
  explains *why* it was refused.
- **FE-2.4** A unified-memory explainer: one bar, segmented into GPU-reserved / other processes /
  cache / free, with a note that the pool is shared.

### FE-3 · Containers (`/containers`)

- **FE-3.1** Table: name, image, status, uptime, CPU %, memory used/limit, net I/O, block I/O.
- **FE-3.2** Ports column showing bind address explicitly, styled per FE-C4.
- **FE-3.3** Row actions: start / stop / restart.
- **FE-3.4** Log drawer with a bounded, streaming tail and a pause control.
- **FE-3.5** Images tab: repository, tag, size, created, in-use flag.
- **FE-3.6** Launch flow from the catalog: pick an entry, fill its declared params (a `model_ref`
  param offers the model inventory), see the resolved command **before** confirming.
- **FE-3.7** If the launch is refused by the unified-memory budget guard, show which running servers
  consume the budget and their totals — not just a rejection.

### FE-4 · Storage (`/storage`)

- **FE-4.1** Per-filesystem bars with mount, device, used/total, free, percent.
- **FE-4.2** Named large consumers: Docker data root, HF cache, `~/projects`.
- **FE-4.3** Docker reclaimable breakdown (images / containers / volumes / build cache).
- **FE-4.4** Threshold crossings styled as findings, consistent with FE-1.3.

### FE-5 · Models (`/models`)

- **FE-5.1** Grouped by source (HuggingFace cache, Ollama, scan roots) with a size total per group.
- **FE-5.2** Per model: repo id, revision, size, last used, and a **"served by"** badge when a
  running service is serving it.
- **FE-5.3** Serving-relevant facts on the detail view: `max_position_embeddings`, parameter count,
  quantization, MoE active params.
- **FE-5.4** Scanning state is explicit — a cold scan shows progress rather than an empty list.
- **FE-5.5** "Serve this model" hands off to FE-3.6 with the model pre-filled.

### FE-6 · Agents & services (`/services`)

The page that answers "how do I get to my stuff" without going anywhere else.

- **FE-6.1** Cards per service: name, kind, port, bind (FE-C4), PID or container, uptime, health.
- **FE-6.2** An **Open** link that is correct for how the user reached the dashboard — loopback when
  local, the viewer's own host when remote. A link that resolves only on the server is a bug.
- **FE-6.3** For OpenAI-compatible endpoints, list the served model names inline, and offer the
  `base_url` a client needs, copyable.
- **FE-6.4** Unreachable services are visually distinct from unprobed ones.
- **FE-6.5** Where a credential can be read locally, the link includes it, masked per FE-C11.
- **FE-6.6** Where it cannot, the card says how to obtain it rather than offering a link that fails.
- **FE-6.7** For a loopback service viewed remotely, a copyable SSH tunnel command replaces the link.
- **FE-6.8** Declared services (R12) appear while offline, with a Start control when one is declared.

### FE-10 · Services, grouped and explained

- **FE-10.1** Services appear under category headings — Model servers, Notebooks, Agents, Tools —
  in that order. Empty categories are omitted.
- **FE-10.2** Each card leads with a human name and a one-line description of what the thing is.
- **FE-10.3** Infrastructure and unrecognised listeners are behind a single toggle that names what
  it reveals and how many there are.
- **FE-10.4** Every card shows exactly one primary action: open it, copy the API base URL, or the
  command that makes it reachable. Never a link that will not work from here.
- **FE-10.5** The access block states the viewer's position explicitly ("you are on the tailnet"),
  because that is what determines the answer.
- **FE-10.6** For a `127.0.0.1` viewer, both possibilities are shown and labelled: works if the
  browser is on the DGX, otherwise forward the port.

### FE-9 · Launch (on `/services`)

- **FE-9.1** Catalog entries of kind `process` are listed with their parameters.
- **FE-9.2** A `venv_ref` parameter offers the GPU-capable environments already discovered,
  defaulting to the entry's own default.
- **FE-9.3** An entry that is **already running** shows that instead of a launch control, including
  when it was started outside dgxctl, and says so.
- **FE-9.4** An externally-started instance is not offered a Stop control, and the card explains why.
- **FE-9.5** A launch that fails shows the tail of the process log, not just "failed".

### FE-7 · Network (`/network`)

- **FE-7.1** Listening sockets table: proto, bind, port, process, container, exposure level.
- **FE-7.2** Default filter shows **non-loopback first**; that is the reason to open this page.
- **FE-7.3** Tailscale panel: this node's name and IP, backend state, exit node, peer list with
  online status.
- **FE-7.4** An explicit banner stating the tailnet is shared and that non-loopback binds are
  reachable by other people's machines.

### FE-8 · Settings (`/settings`)

- **FE-8.1** Read-only view of effective config: bind, port, intervals, control gate, retention.
- **FE-8.2** Action log viewer (S7): timestamp, identity, action, target, result.
- **FE-8.3** `doctor` output (R8.3): each data source with available / degraded / unavailable and the
  reason.
- **FE-8.4** Never render the token, and never render any value from a credential file (S2, S9).
