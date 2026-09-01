# DGX Control

Granular observability and safe control for NVIDIA DGX Spark systems, in a browser.

Goes well beyond NVIDIA Sync's DGX Dashboard: GPU utilisation attributed to the owning **process
and container**, Docker containers and images with lifecycle control, disk and HuggingFace-cache
inventory, one-click access to the services already running on the box, local model inventory, and
a **listening-socket exposure audit** that names what is reachable from outside and who owns it.

Runs unprivileged. Serves the UI and API from one port. Registers itself into NVIDIA Sync.

---

## Install

On the DGX:

```bash
git clone https://github.com/mayankgrd/dgx-control ~/dgx-control
cd ~/dgx-control
./deploy/install.sh
```

That installs into a virtualenv under `~/.local/share/dgxctl`, builds the UI, and then asks a
handful of questions — who should be able to reach it, whether control actions are allowed, and
whether to add it to NVIDIA Sync. **No `sudo` at any point.**

It adapts to the machine: no Tailscale means no tailnet options, no Docker means the container
pages report themselves unavailable rather than failing. Re-run `dgxctl onboard` any time to
change your answers.

<details>
<summary>Unattended / fleet install</summary>

```bash
./deploy/install.sh --yes --no-onboard          # install only
dgxctl onboard --yes --bind loopback --no-control --no-sync
```

Every question has a flag: `--bind loopback|tailnet-serve|all|tailnet-address`, `--port`,
`--node-name`, `--control/--no-control`, `--sync/--no-sync`, `--service/--no-service`.
</details>

The installer puts `dgxctl` on your PATH (a symlink into `~/.local/bin`, and a guarded line in
your shell files only if that directory is not already there). Open a new shell afterwards.

> **Remote one-liners.** `ssh host 'dgxctl doctor'` runs a non-interactive shell, which reads
> neither `.profile` nor `.bashrc`, so `~/.local/bin` is absent there. Use
> `ssh host 'export PATH="$HOME/.local/bin:$PATH"; dgxctl doctor'`.

**Requirements.** Python 3.11+, Linux, aarch64 or x86_64. Node 20+ if you want the dashboard as
well as the API. Everything else is optional and degrades gracefully — run `dgxctl doctor` to see
what your machine offers.

## Everyday commands

```bash
dgxctl doctor     # what works on this machine, and how to fix what doesn't
dgxctl expose     # who can reach this, and the exact command to change it
dgxctl token      # --show, --rotate
dgxctl onboard    # re-run setup
dgxctl sync       # register | list | unregister with NVIDIA Sync
```

## What it shows you that `nvidia-smi` will not

- **Which container is holding the GPU.** NVML reports host-namespace PIDs and the GPU process is
  usually a *child* of the container's main process, so the mapping is not obvious. dgxctl
  resolves it through `/proc/<gpu_pid>/cgroup`.
- **What is listening beyond loopback, and who owns it.** Every non-loopback bind is a finding,
  with the owning process or container named.
- **Unified memory told honestly.** On GB10 there is no separate GPU memory pool —
  `nvmlDeviceGetMemoryInfo` returns `NotSupported`. dgxctl reads `/proc/meminfo` and shows one
  segmented pool, because two bars would imply two budgets that do not exist.
- **Whether a model server will actually fit.** Launches are refused when the summed
  `--gpu-memory-utilization` across running servers would exceed 0.70.

## Launching things

Not everything worth launching is a container. NVIDIA Sync's own dashboard runs JupyterLab from a
**host virtualenv**, because that is what gives a notebook direct GPU access without container
plumbing — so dgxctl does the same. Catalog entries declare `kind = "container"` or
`kind = "process"`; commands come only from the catalog, never from the browser.

An instance that is **already running is adopted, not duplicated** — including one you started
from a terminal or from Sync itself. A service's identity is its port; a port held by something
else is reported as a conflict rather than as "already running".

## Getting to your services

The Services page answers "how do I actually open this", so you do not have to go and look:

- **Jupyter's token** is read from its runtime file and folded into a working link — masked until
  you reveal or copy it, since it grants code execution.
- **Model servers** show the OpenAI `base_url` and served model name, copyable.
- **Loopback services viewed remotely** get a ready-to-paste SSH tunnel command instead of a link
  that would resolve on the wrong machine.
- **Services that authenticate their own way** (Hermes) say so, rather than offering a link that 401s.
- **Services dgxctl cannot discover** are declarable in `config.toml` and shown while offline, with
  a Start button when you declare a launch command. See [config.example.toml](config.example.toml).

## Security posture

A Tailscale network can include machines belonging to other people, and a local network almost
certainly does. So:

- every route requires a bearer token (`GET /api/health` returns liveness only, no host data);
- startup **fails closed** — a non-loopback bind with no token file refuses to start;
- control actions are gated separately and default to **off**;
- launched containers publish to loopback unless a catalog entry explicitly opts out;
- a peer instance's token is never served to a browser;
- the dashboard reports **itself** as a finding when it is bound beyond loopback.

The token lives at `~/.config/dgxctl/token`, mode `0600`; a looser mode is refused.

### Choosing how to expose it

`dgxctl` binds **one** address. `dgxctl onboard` walks you through this, and `dgxctl expose`
prints the current state and how to change it.

| | Config | Reaches | Notes |
|---|---|---|---|
| **Loopback** | `host = "127.0.0.1"` | this host only | Safest. NVIDIA Sync works. Remote access via `ssh -N -L 8770:127.0.0.1:8770 <host>`. |
| **Tailnet via `tailscale serve`** *(tightest remote option)* | `host = "127.0.0.1"` + `tailscale serve --bg 8770` | tailnet + loopback | Tailnet only, **not** the LAN, with TLS: `https://<host>.<tailnet>.ts.net`. Loopback keeps working, so NVIDIA Sync is unaffected. Needs one root command first: `sudo tailscale set --operator=$USER`. |
| **All interfaces** | `host = "0.0.0.0"` | tailnet **and LAN** | No root needed, loopback still works. Broader than a tailnet: anything that can route to the host can reach it. |
| Tailnet address only | `host = "100.x.y.z"` | tailnet only | Tailnet-only without root — but it **breaks NVIDIA Sync**, which opens `localhost`. |

#### Restricting to named people

To require a specific Tailscale identity in addition to the token:

```toml
tailscale_allowlist = ["you@example.com", "teammate@example.com"]
```

Peers are resolved with `tailscale whois` (no root needed) and cached for 60 s; a rejection is
logged with the identity refused. Loopback bypasses the check. Left empty, any tailnet peer
holding the token gets in.

## NVIDIA Sync integration

`dgxctl onboard` offers this, or run `dgxctl sync register` later. It preserves entries it did not
create, backs the file up first, and refuses to touch a file it cannot parse.

<details>
<summary>Registering by hand instead</summary>

In Sync's **Add Custom** dialog ([screenshot](docs/nvidia-sync-add-custom.png)):

| Field | Value |
|---|---|
| **Name** | `DGX Control` |
| **Port** | `8770` |
| **Auto open in browser at the following path** | checked |
| **URL Path** | `/` |
| **Launch Script** | `bash ~/dgx-control/deploy/nvidia-sync-launch.sh` |
| **Launch in Terminal** | unchecked (runs in the background) |

Sync opens `localhost:<port>`, so the service must be bound somewhere loopback can reach —
`127.0.0.1` or `0.0.0.0`, not a tailnet address alone. The launch script is idempotent: if the
service is already listening it exits cleanly without starting a duplicate.
</details>

## Multiple DGX systems

One instance can aggregate others, so a fleet appears in one tab behind a node switcher. A peer is
just another dgxctl instance reached over its own authenticated API — no extra agent or protocol.

```toml
node_id   = "spark-1"
node_name = "Lab Spark"

[[node]]
id         = "spark-2"
url        = "http://spark-2.your-tailnet.ts.net:8770"
token_file = "~/.config/dgxctl/peers/spark-2.token"
```

Peer data is stored separately per node and can never be presented as the local machine's; an
unreachable peer is reported as unreachable rather than as missing data. Control actions are
deliberately local-only — operate a peer through its own UI, one click away in the switcher.
See [architecture.md §13](docs/architecture.md).

## Documentation

| Doc | What it is |
|---|---|
| [CLAUDE.md](CLAUDE.md) | How to work in this repo |
| [docs/spec.md](docs/spec.md) | Product requirements — R1–R14, S1–S9, N1–N7 |
| [docs/spec_frontend.md](docs/spec_frontend.md) | UI requirements — FE-C1–C11, FE-1–FE-9 |
| [docs/architecture.md](docs/architecture.md) | Architecture; §-indexed, load what you need |
| [docs/SDD.md](docs/SDD.md) | Numbered work items with acceptance criteria |
| [docs/AUDIT.md](docs/AUDIT.md) | Session log |
| [docs/prior_art.md](docs/prior_art.md) | What already exists, and why this was built |

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
cd web && npm ci && npm test && npm run typecheck && npm run build
```

Verify against real hardware — the suite cannot see driver quirks, real cgroup layouts, or a
genuinely exposed socket:

```bash
python3 scripts/live_verify.py   # run ON the DGX
```

Branches: `develop` for all work, `main` for deployment only (fast-forward promotion).

## Licence

MIT — see [LICENSE](LICENSE).
