# CLAUDE.md — DGX Control

A web utility that runs on an NVIDIA DGX Spark and exposes granular observability
and safe control of the box, registered into NVIDIA Sync as a custom tool.

## Key Guidelines

1. **Think Before Coding** — Don't assume. Don't hide confusion. Surface tradeoffs.
2. **Simplicity First** — Minimum code that solves the problem. Nothing speculative.
3. **Surgical Changes** — Touch only what you must. Clean up only your own mess.
4. **Goal-Driven Execution** — Define success criteria. Loop until verified. Write unit,
   integration, smoke, and end-to-end tests.

## Documentation Structure (source of truth, in priority order)

1. **[docs/spec.md](docs/spec.md)** — Product Requirements (`R1…R8`, `S1…S9`, `N1…N7`). Owner-editable.
2. **[docs/spec_frontend.md](docs/spec_frontend.md)** — numbered `FE-N` UI requirements + cross-cutting
   `FE-C*` rules. Every UI change starts from an FE id.
3. **[docs/architecture.md](docs/architecture.md)** — architecture + implementation detail. **Long: load only
   the sections you need** — it has a section index at the top for exactly this.
4. **[docs/SDD.md](docs/SDD.md)** — numbered work items (the task system). Each `SDD-NNN` is independently
   implementable/testable with acceptance criteria that define "done". **IDs are permanent — never
   renumber.** Reference in every commit: `feat(gpu): NVML collector [SDD-010]`. If scope changes
   mid-implementation, update the entry — entry and code must not drift.
5. **[docs/AUDIT.md](docs/AUDIT.md)** — session log. **Required at end of every session.**
6. **[docs/prior_art.md](docs/prior_art.md)** — the existing DGX Spark dashboard landscape and why we build
   rather than adopt. Read before proposing a "we could just use X" pivot.

## Session Workflow

**Before implementing:** spec.md → the relevant architecture.md sections → SDD.md (pick an entry;
check its `BLOCKED (by …)` dependencies are COMPLETE).

**While implementing:** one SDD entry at a time; TDD — write the acceptance-criteria tests first.
Every acceptance criterion maps to at least one named test; error paths are criteria, not extras.

**At session end (REQUIRED):** cascade doc updates (spec → architecture → SDD statuses + newly
discovered entries → AUDIT entry), then commit and push. If spec.md changed, architecture and SDD
are reconciled in the same session.

## Branching & Deployment

- **`develop`** — all development; the default branch.
- **`main`** — deployment only; never commit to it directly. The DGX tracks `main`.
- **Promote:** `git checkout main && git merge --ff-only develop && git push`.
- **Gate promotion on:** all suites green, `dgxctl doctor` clean on the box, and the SDD-053 live
  verification checklist.

## The hardware changes the design — read before coding

DGX Spark is GB10, aarch64, Ubuntu 24.04. These facts are true of every Spark and are why parts of
this codebase look the way they do. (Host-specific details for a particular machine — SSH aliases,
tailnet names — belong in `LOCAL.md`, which is gitignored.)

- **121 GB unified memory.** CPU and GPU share one pool. Never present or compute GPU memory and
  system memory as independent budgets, and sum `--gpu-memory-utilization` across *all* servers —
  keep the total ≤ 0.70.
- **The tailnet is shared with other people's machines.** It is not a trust boundary. Non-loopback
  binds are reachable by strangers. This is why auth is fail-closed (spec S1–S5) and why surfacing
  `0.0.0.0` binds is a headline feature (R6.2), not a nicety.
- **Driver 580.159.03, sm_121.** vLLM images from `26.07-py3` onward require driver 610.43+ and die
  with a misleading `UnicodeDecodeError` from torch's op registry. `vllm-spark:local` is the only
  known-good image; the catalog pins it. Always set `VLLM_USE_DEEP_GEMM=0`.
- **`sudo` is password-protected with no passwordless entry.** An agent cannot complete any root
  step. The service runs unprivileged; anything needing root is *detected and reported unavailable*,
  never attempted. Hand root steps to the human as one copy-pasteable command.
- **Non-interactive SSH drops `~/.local/bin` from PATH.** A non-interactive `ssh host 'cmd'` does not
  source `.bashrc`, so `uv`, `hermes` and anything else under `~/.local/bin` is invisible and you get
  a confusing "command not found". Prefix remote commands:
  `ssh <host> 'export PATH="$HOME/.local/bin:$PATH"; …'`.
- **`nvmlDeviceGetMemoryInfo` raises `NVMLError_NotSupported` on GB10.** There is no separate GPU
  memory pool to report. Totals come from `/proc/meminfo`; `GpuDevice.memory_source` records which
  path was taken. Per-process GPU memory via `nvmlDeviceGetComputeRunningProcesses` *does* work.
- **The GPU process is usually a CHILD of the container's main process** (observed: container
  `State.Pid` 725512, GPU pid 726116). Attribution goes through `/proc/<gpu_pid>/cgroup`, never by
  matching the container's own PID.

## Subagent Delegation Playbook

**Model selection** — Fable/Opus: the collector framework, auth, the frontend foundation, anything
cross-cutting. Sonnet: a single well-specified collector or page against an existing foundation.
The **orchestrator** (main session) merges, resolves conflicts, verifies suites, deploys, and
implements inline when a slice is small or agent infrastructure is degraded.

**Contracts** — every agent prompt includes: (1) the SDD entry + spec/FE ids as the binding
contract; (2) the exact architecture.md sections to read (never "read architecture.md"); (3)
conventions inherited from merged slices, stated as BINDING; (4) file-ownership boundaries —
`schemas.py`, design tokens, the app shell, and the router belong to ONE agent per wave; (5) exact
test commands and known flakes by name; (6) rules: worktree only, commit `[SDD-NNN]`, no push, never
edit SDD.md/AUDIT.md, never touch live services on the DGX.

**Sequencing** — SDD-001…006 (foundation) before any collector; SDD-040 (frontend foundation) before
any page. Then parallel feature agents citing the foundation's report. Merge each promptly and
re-run all suites on `develop` after every merge.

**Infra degradation** — resume with a state snapshot (check the worktree's `git status`/diff FIRST
and tell the agent what exists); agents commit incrementally per completed part; ≤2 concurrent;
back off 20–45 min between retries; after ~3 fruitless resumes, implement inline instead. Worktrees
preserve partial work indefinitely.

## Seam-Bug Doctrine

Production bugs live at **seams between components**, almost never inside one component's logic.
**[architecture.md §11](docs/architecture.md) enumerates this project's known seams** — read it before
writing tests for anything crossing a boundary.

- Mocks on BOTH sides of a seam can share the same wrong assumption. At least one test per contract
  must exercise the REAL other side — real `ss` output, real cgroup files, real Docker payloads.
- **Capture real tool output into `tests/fixtures/` from the box.** Parsers get tested against real
  bytes, never invented ones.
- Regression-lock **verbatim live failure output** as a test.
- Fix at the boundary that serves all consumers, not per-caller.

The single highest-stakes seam: **`HostIp: ""` in a Docker port binding means `0.0.0.0`, not
"unknown".** Treating it as loopback inverts the safety signal this whole product exists to provide.

## Debugging & Ops Lessons

- **Evidence before theorizing.** Curl the endpoint with the exact client payload; run the real
  command and read its real output. A 30-second empirical smoke test de-risks a whole design.
- Read FULL command output, not `tail -1`.
- When a container crash-loops, read the log from the **beginning** — fatal causes on this box (the
  driver banner, config assertions) appear early and get buried under the resulting traceback.
  `docker update --restart=no <name>` first so it stops churning.
- SQLite: every connection needs WAL + `busy_timeout`. `":memory:"?cache=shared` is ONE process-wide
  DB — use a unique temp file per test.
- Background tasks: wrap in a quiet-guard (log, never raise). Fire-and-forget asyncio tasks need
  strong references or they are garbage-collected mid-flight.
- Tests never bind real ports (a deployed service may hold them) and never read the clock in
  assertions.
- Blocking work (NVML, Docker SDK, subprocess, filesystem walks) goes through `asyncio.to_thread` —
  never inline on the event loop.

## Verification Bar

- Every fix ships with a regression test named for its SDD.
- **Deploys are verified LIVE on the real box** via the SDD-053 checklist. The suite cannot see
  driver quirks, real cgroup layouts, or a genuinely exposed socket. Expect the first live run to
  find bugs; file each as a new SDD entry.
- Security-relevant changes (auth, bind, actions) additionally require: the parametrized
  every-route-requires-auth test green, and a live check from a second tailnet machine that no route
  leaks host data unauthenticated.

## Frontend Conventions

- **SDD-040 owns** design tokens, breakpoints, and the app shell for the whole project; pages never
  add their own nav and stay mobile-safe at 390 px. Once SDD-040 lands, record its breakpoint
  variants and utility classes here and mark them BINDING.
- The SPA speaks a single origin (`/api/*`) and is served by FastAPI from `web/dist`. The **Vite dev
  proxy masks production-only routing bugs** — test the production serving path too.
- **One data source:** a single `SSEProvider` owns the stream; components read from context and
  never fetch the same data independently.
- **TypeScript types are generated** from the OpenAPI schema into `web/src/api/types.gen.ts`.
  Hand-editing that file is prohibited; CI asserts a regenerated file has no diff.
- The exposure vocabulary (`loopback` / `lan` / `tailnet` / `all`) is defined once in tokens and used
  identically everywhere a bind is shown.
- Datetimes: UTC re-attached at the serialization boundary, rendered local in one util.
- The production build type-checks test files too — keep tests type-clean.

## Implementation Boundaries

- ✅ **Always**: run tests before commits; reference spec/FE/SDD ids in tests and commits; capture
  real fixtures from the box for any parser.
- ⚠️ **Ask first**: adding a dependency (must have an aarch64 wheel); changing the auth or bind
  model; adding a control action; changing the catalog's host-specific guards.
- 🚫 **Never**: commit host-specific data — a hostname, a real tailnet or LAN address, a personal
  home path — in any tracked file, fixtures included. `tests/unit/test_no_private_data.py` enforces
  this; capture fixtures from real machines, then scrub them before committing.
- 🚫 **Never**: commit secrets or the token file; bind non-loopback in code or defaults; publish a
  container port without an explicit bind address; interpolate user input into a shell string; run
  `sudo`; touch live services on the DGX from a subagent; edit generated files; commit DB files or
  WAL/SHM sidecars.

## Project Specifics

- **Stack:** Python 3.12 · FastAPI + uvicorn · pydantic v2 · pynvml · psutil · docker SDK · SQLite ·
  React 19 + TypeScript + Vite + Tailwind. Package `dgxctl`, src layout.
- **Reference test machine:** see `LOCAL.md` (gitignored) for the host alias. Deploy with
  `rsync` + `deploy/install.sh`, then `python3 scripts/live_verify.py` on the box.
- **Test commands:**
  - backend: `uv run pytest -q` (unit + integration)
  - backend one entry: `uv run pytest -q -k SDD_012`
  - frontend: `cd web && npm test` · types: `cd web && npm run typecheck`
  - lint: `uv run ruff check . && uv run ruff format --check .`
  - live verification on real hardware: `python3 scripts/live_verify.py` (run ON the DGX)
  - preflight: `dgxctl doctor`
- **Default port:** 8770. Default bind: `127.0.0.1` (overridden only in config, never in code).
- **Deploy:** promote `develop`→`main`, then on the box `git pull && ./deploy/install.sh &&
  systemctl --user restart dgxctl`, then run the SDD-053 checklist.
- **Known flaky tests:** none. Two tests skip on non-Linux (`test_refuses_kernel_threads_*`,
  `test_kthreadd_*`) because kernel threads are a Linux concept.
- **The live bar is not optional.** The first deployment to real hardware found five defects the
  entire suite could not see: NVML memory unsupported on GB10, `container.image` raising
  ImageNotFound, `is_dir()` raising PermissionError under `$HOME`, dependent collectors publishing
  empty results before their sources reported, and an empty cmdline being mistaken for a kernel
  thread. Deploy and run `scripts/live_verify.py` before claiming anything works.
