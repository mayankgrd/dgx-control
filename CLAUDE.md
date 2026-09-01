# CLAUDE.md — DGX Control

A dashboard and control panel that runs on an NVIDIA DGX Spark, serving UI and API from one port.

## The loop

**spec → architecture → numbered SDD entry → tests first, then code → live check on hardware → audit.**

Every change starts as a numbered requirement and ends as a test that proves it. Acceptance criteria
in an SDD entry are the *names of the tests*, so "done" is not a judgement call.

Hardware is part of the loop, not a final smoke test. The suite cannot see driver quirks, real cgroup
layouts, or a genuinely exposed socket — live verification has found **eleven defects the whole suite
missed**. A bug found on hardware becomes a new SDD entry with its own regression test, and what was
learned goes back into the spec.

Full description: [docs/methodology.md](docs/methodology.md). Contributors arrive via `docs/spec.md`;
if you are handed a requirement with no SDD entry, write the entry before the code.

## Source of truth, in priority order

1. **[docs/spec.md](docs/spec.md)** — requirements: `R1…R16`, `S1…S11`, `N1…N8`. Owner-editable.
2. **[docs/spec_frontend.md](docs/spec_frontend.md)** — `FE-C1…C11` cross-cutting rules and `FE-1…FE-10`
   per page. Every UI change starts from an FE id.
3. **[docs/architecture.md](docs/architecture.md)** — long, with a section index at the top. **Load only
   the sections you need.** §11 lists the known seams.
4. **[docs/SDD.md](docs/SDD.md)** — numbered work items. **IDs are permanent — never renumber.** Cite in
   commits: `feat(gpu): NVML collector [SDD-010]`. If scope changes mid-implementation, update the
   entry; entry and code must not drift.
5. **[docs/AUDIT.md](docs/AUDIT.md)** — session log. **Required at the end of every session.**
6. **[docs/prior_art.md](docs/prior_art.md)** — read before proposing "we could just use X".

## Session workflow

- **Before:** spec → the relevant architecture sections → pick an SDD entry, check its
  `BLOCKED (by …)` dependencies are COMPLETE.
- **While:** one entry at a time, tests first. Every acceptance criterion maps to a named test.
  Error paths are criteria, not extras.
- **At the end (required):** cascade doc updates (spec → architecture → SDD statuses and any new
  entries → AUDIT), then commit and push. If spec.md changed, reconcile architecture and SDD in the
  same session.

## Branching

`develop` for all work and the default branch. `main` for deployment only — never commit to it
directly. Promote with `git checkout main && git merge --ff-only develop && git push`, gated on green
suites and a clean `scripts/live_verify.py` on the box.

## The hardware changes the design

DGX Spark is GB10, aarch64, Ubuntu 24.04. These are true of every Spark and explain why parts of this
codebase look the way they do. Host-specific details go in `LOCAL.md`, which is gitignored.

- **121 GB unified memory.** CPU and GPU share one pool. Never present or compute them as separate
  budgets, and sum `--gpu-memory-utilization` across *all* servers — keep the total ≤ 0.70.
- **`nvmlDeviceGetMemoryInfo` raises `NotSupported`.** There is no separate GPU pool. Totals come from
  `/proc/meminfo`; `GpuDevice.memory_source` records which path was taken. Per-process GPU memory via
  `nvmlDeviceGetComputeRunningProcesses` does work.
- **The GPU process is usually a CHILD of the container's main process.** Attribution goes through
  `/proc/<gpu_pid>/cgroup`, never by matching the container's own `State.Pid`.
- **A tailnet is not a trust boundary.** Non-loopback binds are reachable by machines you do not
  control. Hence fail-closed auth (S1–S5) and why surfacing `0.0.0.0` binds is a headline feature
  (R6.2), not a nicety.
- **Driver 580.159.03, sm_121.** vLLM images from `26.07-py3` on need driver 610.43+ and die with a
  misleading `UnicodeDecodeError` from torch's op registry. `vllm-spark:local` is the known-good
  image; the catalog pins it. Always set `VLLM_USE_DEEP_GEMM=0`.
- **`sudo` is password-protected.** An agent cannot complete a root step. Anything needing root is
  detected and reported unavailable, never attempted — hand it to the human as one command.
- **Non-interactive SSH drops `~/.local/bin` from PATH.** Prefix remote commands with
  `export PATH="$HOME/.local/bin:$PATH";` or get a confusing "command not found".

## Seam-bug doctrine

Production bugs live at **seams between components**, almost never inside one component's logic.
[architecture.md §11](docs/architecture.md) enumerates this project's; read it before testing anything
that crosses a boundary.

- Mocks on BOTH sides of a seam can share the same wrong assumption. At least one test per contract
  must exercise the real other side — real `ss` output, real cgroup files, real Docker payloads.
- **Capture real tool output into `tests/fixtures/`.** Parsers are tested against real bytes.
- Regression-lock verbatim live failure output as a test.
- Fix at the boundary that serves all consumers, not per caller.
- A wiring seam has bitten three times: a function grows a parameter, its unit tests pass, and the
  caller never passes it — so the feature is complete and inert. Assert the wiring, not just the unit.

The highest-stakes seam: **`HostIp: ""` in a Docker port binding means `0.0.0.0`, not "unknown".**
Reading it as loopback inverts the safety signal this product exists to provide.

## Verification bar

- Every fix ships a regression test named for its SDD.
- **Deploys are verified live** with `scripts/live_verify.py`. Expect the first live run to find
  things; file each as a new SDD entry.
- Security-relevant changes (auth, bind, actions) also need the parametrized
  every-route-requires-auth test green, and a check from a second machine that no route leaks host
  data unauthenticated. Write the probe the way an attacker sends it — an HTTP client normalises `..`
  out of a path, so a traversal test written with one passes against a vulnerable server.

## Debugging habits

- **Evidence before theorising.** Run the real command, read its real output. A 30-second empirical
  check de-risks a whole design.
- Read FULL command output, not `tail -1`.
- A crash-looping container: `docker update --restart=no <name>`, then read the log from the
  **beginning** — fatal causes appear early and get buried under the resulting traceback.
- SQLite: every connection needs WAL + `busy_timeout`. `":memory:?cache=shared"` is one process-wide
  DB; use a unique temp file per test.
- Background tasks get a quiet-guard (log, never raise). Fire-and-forget asyncio tasks need strong
  references or they are collected mid-flight.
- Tests never bind real ports, never read the clock in assertions, and never touch the real `$HOME`.
- Blocking work (NVML, Docker SDK, subprocess, filesystem walks) goes through `asyncio.to_thread`.

## Frontend conventions

- One `SSEProvider` owns the stream; components read from context and never fetch the same data
  independently.
- The SPA speaks a single origin (`/api/*`) and is served by FastAPI from `web/dist`. The Vite dev
  proxy masks production-only routing bugs — test the served path too.
- TypeScript types are **generated** into `web/src/api/types.gen.ts`; hand-editing is prohibited and
  CI asserts a regenerated file has no diff.
- The exposure vocabulary (`loopback` / `lan` / `tailnet` / `all`) is defined once in tokens and used
  identically wherever a bind is shown.
- Datetimes: UTC at the serialisation boundary, rendered local in one util. Pages stay usable at
  390 px. The production build type-checks tests too.

## Boundaries

- ✅ **Always** run tests before committing; cite spec/FE/SDD ids; capture real fixtures for parsers.
- ⚠️ **Ask first** before adding a dependency (needs an aarch64 wheel), changing the auth or bind
  model, adding a control action, or changing the catalog's host guards.
- 🚫 **Never** commit host-specific data — a hostname, a real tailnet or LAN address, a personal home
  path — in any tracked file, fixtures included; `tests/unit/test_no_private_data.py` enforces it.
- 🚫 **Never** commit secrets or the token file; bind non-loopback in code or defaults; publish a
  container port without an explicit bind address; interpolate user input into a shell string; run
  `sudo`; edit generated files; commit DB files or WAL/SHM sidecars.

## Project specifics

- **Stack:** Python 3.11+ · FastAPI + uvicorn · pydantic v2 · psutil · docker SDK · SQLite ·
  React 19 + TypeScript + Vite + Tailwind. Package `dgxctl`, src layout.
- **Default port** 8770, default bind `127.0.0.1` — overridden in config, never in code.
- **Commands:**
  ```bash
  uv run pytest -q                                   # backend
  uv run pytest -q -k SDD_012                        # one entry
  uv run ruff check . && uv run ruff format --check .
  cd web && npm test && npm run typecheck            # frontend
  python3 scripts/live_verify.py                     # ON the DGX
  dgxctl doctor                                      # preflight
  ```
- **Deploy:** promote `develop`→`main`, then on the box `git pull && ./deploy/install.sh &&
  systemctl --user restart dgxctl`, then `scripts/live_verify.py`.
- **Known flakes:** none. Two tests skip on non-Linux (`test_refuses_kernel_threads_*`,
  `test_kthreadd_*`) — kernel threads are a Linux concept.
