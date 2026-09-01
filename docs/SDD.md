# SDD.md — Software Design Descriptions

Numbered, permanent work items. **IDs are never reused and never renumbered.** Superseded entries
are marked, not deleted. Reference the id in every commit: `feat(gpu): NVML collector [SDD-010]`.

Status vocabulary: `TODO` · `IN PROGRESS` · `BLOCKED (by SDD-NNN)` · `COMPLETE` · `SUPERSEDED (by
SDD-NNN)` · `DEFERRED`.

## Index

| ID | Title | Phase | Spec | Status |
|---|---|---|---|---|
| SDD-001 | Repo scaffolding, packaging, config | 0 Foundation | — | COMPLETE |
| SDD-002 | Collector framework | 0 Foundation | N3 | COMPLETE |
| SDD-003 | Snapshot store + SQLite history | 0 Foundation | N2, N7 | COMPLETE |
| SDD-004 | Poller / interval scheduler | 0 Foundation | N1 | COMPLETE |
| SDD-005 | API shell: health, snapshot, SSE | 0 Foundation | N2 | COMPLETE |
| SDD-006 | Auth, bind guard, control gate | 0 Foundation | S1–S5 | COMPLETE |
| SDD-010 | GPU collector (NVML) | 1 Collectors | R1.1, R1.5, R1.6 | COMPLETE |
| SDD-011 | Process collector + GPU/container attribution | 1 Collectors | R1.2–R1.4 | COMPLETE |
| SDD-012 | Container collector | 1 Collectors | R2.1–R2.3 | COMPLETE |
| SDD-013 | Image collector | 1 Collectors | R2.4 | COMPLETE |
| SDD-014 | Disk collector | 1 Collectors | R3 | COMPLETE |
| SDD-015 | Network / listening-socket collector | 1 Collectors | R6.1, R6.2, R6.4 | COMPLETE |
| SDD-016 | Tailscale collector | 1 Collectors | R6.3 | COMPLETE |
| SDD-017 | Service & agent discovery | 1 Collectors | R4 | COMPLETE |
| SDD-018 | Model inventory collector | 1 Collectors | R5 | COMPLETE |
| SDD-019 | Python environment collector | 1 Collectors | R8.1 | COMPLETE |
| SDD-030 | Action runner + action log | 2 Control | S5, S7 | COMPLETE |
| SDD-031 | Container lifecycle actions | 2 Control | R2.6 | COMPLETE |
| SDD-032 | Launch catalog + memory budget guard | 2 Control | R2.7–R2.9 | COMPLETE |
| SDD-033 | Process kill action | 2 Control | S6 | COMPLETE |
| SDD-034 | Container log streaming | 2 Control | R2.5 | COMPLETE |
| SDD-040 | Frontend foundation (tokens, shell, SSE client) | 3 Frontend | FE-C1–C10 | COMPLETE |
| SDD-041 | Overview page | 3 Frontend | FE-1 | COMPLETE |
| SDD-042 | GPU page | 3 Frontend | FE-2 | COMPLETE |
| SDD-043 | Containers page | 3 Frontend | FE-3 | COMPLETE |
| SDD-044 | Storage page | 3 Frontend | FE-4 | COMPLETE |
| SDD-045 | Models page | 3 Frontend | FE-5 | COMPLETE |
| SDD-046 | Services page | 3 Frontend | FE-6 | COMPLETE |
| SDD-047 | Network page | 3 Frontend | FE-7 | COMPLETE |
| SDD-048 | Settings / action log / doctor page | 3 Frontend | FE-8 | COMPLETE |
| SDD-050 | systemd --user unit + installer | 4 Deploy | N6 | COMPLETE |
| SDD-051 | NVIDIA Sync custom tool integration | 4 Deploy | R7 | COMPLETE |
| SDD-052 | `dgxctl doctor` preflight | 4 Deploy | R8.3 | COMPLETE |
| SDD-053 | Live verification on real hardware | 4 Deploy | all | COMPLETE |
| SDD-060 | vLLM `/metrics` scraping | 5 Later | — | DEFERRED |
| SDD-061 | Alerting / notification delivery | 5 Later | — | DEFERRED |
| SDD-070 | Multi-DGX federation (read) | 5 Fleet | R9 | COMPLETE |
| SDD-071 | Peer discovery via Tailscale | 5 Fleet | R9.1 | TODO |
| SDD-072 | Fleet overview page across nodes | 5 Fleet | R9.1 | TODO |
| SDD-073 | Cross-node history | 5 Fleet | R9 | TODO |
| SDD-080 | `dgxctl expose` — exposure guidance | 4 Deploy | S1 | COMPLETE |
| SDD-120 | Environment detection for onboarding | 7 Onboarding | R14.2 | COMPLETE |
| SDD-121 | Bind-option planning | 7 Onboarding | R14.3, R14.4 | COMPLETE |
| SDD-122 | `dgxctl onboard` wizard | 7 Onboarding | R14.1, R14.5–R14.9 | COMPLETE |
| SDD-123 | install.sh runs onboarding | 7 Onboarding | R14.1 | COMPLETE |
| SDD-124 | Repo layout and licence | 7 Onboarding | — | COMPLETE |
| SDD-125 | Put `dgxctl` on PATH during install | 7 Onboarding | R14.1 | COMPLETE |
| SDD-135 | Launched-process lifecycle is owned by dgxctl | 8 Services | R10.2 | COMPLETE |
| SDD-140 | Private-data guard for a public repo | 9 Release | N8 | COMPLETE |
| SDD-141 | Advertised addresses for links and forwards | 8 Services | R16.5 | COMPLETE |
| SDD-142 | README with hero and feature screenshots | 9 Release | — | COMPLETE |
| SDD-150 | Path traversal in the SPA handler | 9 Security | S1 | COMPLETE |
| SDD-151 | Restrictive modes on files dgxctl writes | 9 Security | S2 | COMPLETE |
| SDD-152 | Auth sweep must see app-level routes | 9 Security | S1 | COMPLETE |
| SDD-160 | README trimmed; methodology moved to docs | 9 Release | — | COMPLETE |
| SDD-161 | Relicence MIT → Apache 2.0 | 9 Release | — | COMPLETE |
| SDD-162 | CLAUDE.md shortened for release | 9 Release | — | COMPLETE |
| SDD-130 | Known-service catalog with explanations | 8 Services | R15.1, R15.4–R15.7 | COMPLETE |
| SDD-131 | Classify by command line, not port alone | 8 Services | R15.3 | COMPLETE |
| SDD-132 | Host address inventory | 8 Services | R16.1 | COMPLETE |
| SDD-133 | Reachability planner | 8 Services | R16.2–R16.7 | COMPLETE |
| SDD-134 | Services page, grouped and explained | 8 Services | FE-10 | COMPLETE |
| SDD-126 | A re-run must not eat user config | 7 Onboarding | R14.7 | COMPLETE |
| SDD-107 | Remove PrivateTmp from the unit | 4 Deploy | R6.1 | COMPLETE |
| SDD-114 | Prompt shutdown with live SSE streams | 4 Deploy | N6 | COMPLETE |
| SDD-100 | Process launchables in the catalog | 6 Launch | R10.1–R10.3, R10.7 | COMPLETE |
| SDD-101 | Adopt an already-running instance | 6 Launch | R10.4 | COMPLETE |
| SDD-102 | JupyterLab entry + venv selection | 6 Launch | R10.6 | COMPLETE |
| SDD-103 | Access endpoints and credential links | 6 Access | R11 | COMPLETE |
| SDD-104 | Declarable services | 6 Access | R12 | COMPLETE |
| SDD-105 | NVIDIA Sync registration CLI | 6 Access | R13 | COMPLETE |
| SDD-106 | Services page: launch, links, reveal | 6 Access | FE-9 | COMPLETE |

## Implementation record

| ID | Built by | Date | Notes |
|---|---|---|---|
| SDD-001…053 | Claude Opus 5 (single session, inline) | 2026-08-30/31 | Full v1. 148 backend + 17 frontend tests |
| SDD-070 | Claude Opus 5 | 2026-08-31 | Read-only federation; control stays local |
| SDD-090…094 | Claude Opus 5 | 2026-08-31 | Live-hardware regressions, filed below |
| SDD-100…106 | Claude Opus 5 | 2026-09-01 | Launchables, access endpoints, Sync registration |
| SDD-107, 110…114 | Claude Opus 5 | 2026-09-01 | Second round of live-hardware regressions |
| SDD-120…128 | Claude Opus 5 | 2026-09-01 | Onboarding wizard, install script, repo layout, PATH, uninstall |
| SDD-130…135 | Claude Opus 5 | 2026-09-01 | Service catalog, reachability planner, grouped page |
| SDD-140 | Claude Opus 5 | 2026-09-01 | Privacy review and permanent guard before going public |

## Live-hardware regressions (found by SDD-053, all fixed)

These are the defects the entire test matrix could not see. Each now has a named regression test.

| ID | Defect | Fix | Test |
|---|---|---|---|
| SDD-090 | `nvmlDeviceGetMemoryInfo` raises `NotSupported` on GB10 — unified memory has no separate GPU pool, so GPU memory read as 0 | Fall back to `/proc/meminfo`; record `memory_source` per device | `test_reported_memory_never_exceeds_physical`, live check 3 |
| SDD-091 | `container.image` raises `ImageNotFound` when the image was removed under a running container; `getattr(c, "image", None)` does not help, because the default only covers `AttributeError` | `safe_image()` wrapper | `test_sdd053_container_with_a_deleted_image_does_not_fail_the_collector` |
| SDD-092 | `Path.is_dir()` raises `PermissionError` on unreadable directories under `$HOME`, failing the whole pyenv collector | Guard per entry | `test_sdd053_unreadable_directory_does_not_fail_the_pyenv_walk` |
| SDD-093 | Dependent collectors (`services` → `network`/`containers`) published one empty result at startup, then waited a full interval. A vLLM port was mis-classified as generic `http` for 60 s | `Collector.depends_on`; the poller holds the first run until sources report. A fixed delay cannot work — how long `containers` takes depends on how many are running | `test_dependent_collector_waits_for_its_source` |
| SDD-107 | `PrivateTmp=true` in our own systemd unit put the service in a private mount namespace, and `ss -tulnp` then reported **every socket with no owning process** — the exposure audit still listed exposed ports but could no longer name who was listening | Removed, with the reason documented in the unit | `test_unit_does_not_isolate_mounts` |
| SDD-110 | `find_running` searched the process table for the literal command template `{venv}/bin/jupyter-lab`, so a running JupyterLab was never adopted | `Entry.resolved_executable()` fills in declared defaults first | `test_resolved_executable_fills_in_defaults` |
| SDD-111 | Matching a running instance by executable adopted an unrelated process when the command starts with a shared interpreter (`/usr/bin/python3` matched a two-week-old Python process and refused a valid launch). Full-argv matching would have been too strict to adopt a JupyterLab started with different flags | A service's identity is its **port**; the executable is a secondary hint, ignored for bare interpreters. A port held by something else is reported as a conflict, not as "already running" | `test_a_bare_interpreter_is_never_matched_by_executable`, `test_a_process_holding_the_port_but_not_ours_is_not_adopted` |
| SDD-112 | `torch-2.9.0+cu130.dist-info` parsed to version `2.9.0+cu130.dist`, and `cuda: Optional[str] = '13.0'` defeated the CUDA regex — so every GPU environment was reported as CPU | Strip the suffix before splitting; regex tolerates the type annotation; a `+cuNNN` tag is conclusive on its own | `test_torch_version_strips_the_dist_info_suffix`, `test_torch_cuda_detected_through_a_type_annotation` |
| SDD-114 | A live SSE response held uvicorn in "waiting for connections to close" until systemd's 90 s stop timeout expired and **SIGKILLed** the service. Setting a shutdown flag in lifespan shutdown does not help — uvicorn drains connections *before* running it | Chain onto uvicorn's own SIGTERM/SIGINT handler so the flag is set when the signal arrives, then delegate. Stop went from 90 s + SIGKILL to **359 ms**, result `success` | `test_sse_stream_ends_when_the_app_shuts_down`, `test_shutdown_signal_is_chained_not_replaced` |
| SDD-113 | A stale token left the UI on an empty shell with no way to re-enter one, because the prompt only appeared when *no* token was stored | Prompt on any unauthorized state; say the stored token was rejected | `test_a_rotated_token_must_not_strand_the_user` |
| SDD-094 | An empty cmdline was treated as "kernel thread", so a real process caught between `fork` and `execve` was refused. Wide enough to hit routinely on this hardware | Kernel threads identified by descent from kthreadd (pid 2) on Linux; the concept does not apply elsewhere | `test_sdd053_process_mid_exec_is_not_mistaken_for_a_kernel_thread` |

---

# Entries

## SDD-001 · Repo scaffolding, packaging, config
**Phase** 0 · **Status** TODO · **Depends on** — · **Spec** —

**Design.** `pyproject.toml` for package `dgxctl` (src layout), deps: `fastapi`, `uvicorn[standard]`,
`pydantic`, `pydantic-settings`, `pynvml`, `psutil`, `docker`, `httpx`, `typer`. Every dep must have
an aarch64 wheel (N5) — verify, do not assume. Ruff + pytest config in the same file.
`config.py` loads `~/.config/dgxctl/config.toml` layered over defaults, env prefix `DGXCTL_`.
`cli.py` exposes `serve`, `doctor`, `token`.

**Acceptance criteria**
1. `test_package_imports` — `import dgxctl` succeeds from a clean install.
2. `test_config_defaults` — missing config file yields documented defaults (host `127.0.0.1`,
   port 8770, `control_enabled=false`).
3. `test_config_file_overrides_defaults` and `test_env_overrides_file` — precedence is env > file >
   default.
4. `test_config_rejects_unknown_key` — a typo'd key errors rather than being silently ignored.
5. `test_all_deps_have_aarch64_wheels` — documented check; may be a script rather than a unit test.

## SDD-002 · Collector framework
**Phase** 0 · **Status** BLOCKED (by SDD-001) · **Spec** N3 · **Arch** §3

**Design.** `Collector` ABC and `CollectorResult` per architecture §3. `base.py` provides the wrapper
converting exceptions and timeouts into results, retaining prior good data. Single `run_cmd(argv,
timeout)` helper — argument lists only (S8). A registry maps name → instance.

**Acceptance criteria**
1. `test_collector_exception_becomes_error_result` — a raising collector yields `status=error`, and
   the poller is unaffected.
2. `test_collector_timeout_becomes_error_result` — exceeding `timeout` yields `status=error` within
   the timeout budget.
3. `test_error_retains_previous_good_data` — after ok→error, `data` is the last good payload and
   `error` is set.
4. `test_unavailable_collector_not_scheduled` — `available()` False yields `status=unavailable` and
   the collector is never invoked again.
5. `test_run_cmd_rejects_string_command` — passing a string instead of argv raises (S8 enforcement).

## SDD-003 · Snapshot store + SQLite history
**Phase** 0 · **Status** BLOCKED (by SDD-001) · **Spec** N2, N7 · **Arch** §5

**Design.** `SnapshotStore` with lock, version counter, and drop-oldest subscriber queues.
`HistoryStore` on SQLite with WAL + `busy_timeout=5000` + `synchronous=NORMAL` on **every**
connection, a fixed metric set, and a prune task honouring the retention window and size ceiling.

**Acceptance criteria**
1. `test_snapshot_read_is_last_known` — reads return stored data without invoking collectors.
2. `test_subscriber_drop_oldest` — a subscriber that never drains does not block a writer; it
   receives the newest snapshot, not a backlog.
3. `test_history_pragmas_applied` — every connection reports WAL and a non-zero busy_timeout.
4. `test_history_prune_respects_retention` — rows beyond the window are deleted.
5. `test_history_size_ceiling` — the file stays under the ceiling after sustained writes.
6. Each test uses a unique temp DB path — never `:memory:?cache=shared`.

## SDD-004 · Poller / interval scheduler
**Phase** 0 · **Status** BLOCKED (by SDD-002, SDD-003) · **Spec** N1 · **Arch** §3

**Design.** One asyncio task per collector on its own interval. Blocking work dispatched via
`asyncio.to_thread` with a bounded pool. Writes results to the store and pushes history metrics.

**Acceptance criteria**
1. `test_collectors_run_on_own_intervals` — a fast and a slow collector each fire at their rate.
2. `test_slow_collector_does_not_delay_fast_one` — a collector sleeping past its interval does not
   shift another's schedule.
3. `test_failing_collector_does_not_stop_poller` — the poller survives repeated failures.
4. `test_poller_shuts_down_cleanly` — cancellation leaves no pending tasks or threads.
5. `test_idle_cpu_budget` — documented measurement against N1 (may be a benchmark, not CI-gated).

## SDD-005 · API shell: health, snapshot, SSE
**Phase** 0 · **Status** BLOCKED (by SDD-003) · **Spec** N2 · **Arch** §6

**Design.** FastAPI app factory, lifespan starting/stopping the poller, `schemas.py` as the contract,
routes for health / snapshot / section / stream / history, static SPA mount last so `/api/*` wins.
SSE emits `snapshot` on version change and `ping` every 15 s.

**Acceptance criteria**
1. `test_health_returns_no_host_data` — the health body contains version and uptime only.
2. `test_snapshot_envelope_shape` — every section matches the envelope (status/data/error/
   collected_at/duration_ms).
3. `test_snapshot_served_from_cache` — no collector executes during a request.
4. `test_sse_emits_on_version_change` and `test_sse_ping_keepalive`.
5. `test_sse_client_disconnect_cleans_up_subscriber` — no subscriber leak.
6. `test_spa_fallback_does_not_shadow_api` — an unknown `/api/*` path returns 404 JSON, not the SPA.

## SDD-006 · Auth, bind guard, control gate
**Phase** 0 · **Status** BLOCKED (by SDD-005) · **Spec** S1–S5 · **Arch** §7

**Design.** Middleware implementing the §7 chain. Token generation and `0600` verification. SSE
ticket endpoint (short-lived, single-use). Tailscale identity allowlist with 60 s cache. Startup
bind guard in lifespan.

**Acceptance criteria**
1. `test_every_route_requires_auth` — **parametrized over the app's route table**; only
   `/api/health` may be unauthenticated. A newly added unauthenticated route fails this test.
2. `test_wrong_token_401_generic_body` — the body reveals nothing about the expected token.
3. `test_bind_guard_refuses_nonloopback_without_token` — startup raises, naming `dgxctl token --init`.
4. `test_bind_guard_asserts_listening_socket` — the guard reflects the socket actually bound, not
   just the config value (§11 seam).
5. `test_token_file_bad_permissions_refused` — a token file looser than `0600` is rejected.
6. `test_sse_ticket_single_use_and_expiring`; `test_long_lived_token_rejected_as_query_param`.
7. `test_control_gate_defaults_off` — an action returns 403 with `control_enabled` unset.
8. `test_tailscale_allowlist_rejects_unknown_identity` and `test_allowlist_miss_is_logged`.
9. `test_token_never_appears_in_logs_or_error_bodies`.

## SDD-010 · GPU collector (NVML)
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R1.1, R1.5, R1.6 · **Arch** §4

**Design.** pynvml for utilization, memory, temperature, power, clocks. Present unified memory as one
pool cross-checked against `psutil.virtual_memory()`. Push util and memory to history.

**Acceptance criteria**
1. `test_gpu_metrics_from_fixture` — parses a captured NVML response into the schema.
2. `test_unified_memory_single_pool` — reported total ≤ physical total; GPU and system memory are
   never summed (§11 seam).
3. `test_nvml_unavailable_yields_unavailable_status` — no NVML present → `unavailable`, not `error`.
4. `test_nvml_init_failure_is_recoverable` — a transient failure recovers on a later cycle.
5. `test_history_receives_gpu_metrics`.

## SDD-011 · Process collector + GPU/container attribution
**Phase** 1 · **Status** BLOCKED (by SDD-010, SDD-012) · **Spec** R1.2–R1.4 · **Arch** §4, §11

**Design.** psutil process walk joined with `nvmlDeviceGetComputeRunningProcesses`, then container
attribution via `/proc/<pid>/cgroup`. Ranked by GPU memory.

**Acceptance criteria**
1. `test_gpu_processes_ranked_by_memory`.
2. `test_containerized_process_attributed_to_container` — **using a real captured fixture from a
   containerized vLLM server**, covering the host-vs-container PID namespace seam.
3. `test_cgroup_v1_and_v2_parsing` — both layouts resolve the container id.
4. `test_process_exits_during_collection` — a PID vanishing mid-walk does not fail the collector.
5. `test_unattributable_process_has_null_container` — not an error, not a guess.

## SDD-012 · Container collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R2.1–R2.3 · **Arch** §4, §11

**Design.** Docker SDK. Containers with status, uptime, restart policy, stats, and port bindings with
`HostIp` preserved. `docker stats` is expensive — use the streaming API or cache per interval.

**Acceptance criteria**
1. `test_container_list_fields` — name, image, status, uptime, restart policy parsed.
2. `test_empty_hostip_classified_as_all` — `HostIp: ""` is `0.0.0.0`, **not** loopback (§11 seam;
   this test protects the entire safety signal).
3. `test_loopback_publish_classified_loopback` — `127.0.0.1` binding is distinct.
4. `test_docker_socket_missing_yields_unavailable`.
5. `test_stats_timeout_degrades_not_fails` — a hung stats call yields `degraded` with the list intact.
6. `test_stats_collection_within_interval_budget`.

## SDD-013 · Image collector
**Phase** 1 · **Status** BLOCKED (by SDD-012) · **Spec** R2.4

**Acceptance criteria** 1. `test_image_fields` (repo, tag, size, created). 2. `test_in_use_flag_from_running_containers`. 3. `test_dangling_images_labelled`. 4. `test_docker_unavailable_yields_unavailable`.

## SDD-014 · Disk collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R3

**Design.** `psutil` partitions/usage; cached `du -sb` for Docker root, HF cache, `~/projects`;
`docker.df()` for reclaimable. The `du` calls are the expensive part — cache and stagger them.

**Acceptance criteria**
1. `test_filesystem_usage_fields`. 2. `test_pseudo_filesystems_excluded` (tmpfs, overlay, devtmpfs).
3. `test_named_roots_reported`. 4. `test_threshold_crossing_flagged` at the configured percentage.
5. `test_du_failure_degrades_section_only` — an unreadable root does not fail the whole collector.
6. `test_docker_df_reclaimable_parsed`.

## SDD-015 · Network / listening-socket collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R6.1, R6.2, R6.4 · **Arch** §4, §11

**Design.** `ss -tulnpH`, parsed into `(proto, bind_ip, port, pid, process)`, then classified into
`loopback | lan | tailnet | all`. Joined with processes and containers for ownership.

**Acceptance criteria**
1. `test_ss_parse_real_fixture` — against **captured real output** from the box.
2. `test_ipv6_wildcard_classified_all` — `[::]:8010` and `*:8010` both classify as `all`.
3. `test_tailnet_address_classified_tailnet` — the node's own tailnet IP is not "lan".
4. `test_loopback_classified_loopback` for `127.0.0.1` and `::1`.
5. `test_nonloopback_binds_surface_as_findings` with the owning process named.
6. `test_ss_unavailable_yields_unavailable`.

## SDD-016 · Tailscale collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R6.3

**Acceptance criteria** 1. `test_status_json_fixture_parsed` (self name, IP, backend state, exit node, peers). 2. `test_missing_optional_fields_tolerated` — a schema change does not crash the collector (§11 seam). 3. `test_tailscale_not_installed_yields_unavailable`. 4. `test_tailscale_down_state_reported_not_errored`. 5. `test_human_readable_output_never_parsed` — the argv always includes `--json`.

## SDD-017 · Service & agent discovery
**Phase** 1 · **Status** BLOCKED (by SDD-011, SDD-015) · **Spec** R4

**Design.** Join listeners + processes + containers; classify by cmdline pattern (vLLM, Jupyter,
Ollama, `hermes serve`, `hermes gateway`, generic HTTP); probe `/v1/models` on loopback with a 2 s
timeout.

**Acceptance criteria**
1. `test_classifies_known_kinds` for each supported kind from real cmdline fixtures.
2. `test_openai_endpoint_probe_lists_models`.
3. `test_probe_timeout_marks_unreachable_not_error`.
4. `test_unprobed_distinct_from_unreachable` — three-state health, per FE-6.4.
5. `test_probe_only_targets_loopback` — the collector never probes an external address.
6. `test_hermes_serve_401_is_healthy` — `hermes serve` returns 401 on `/api/*` without its one-shot
   token; that is expected and must not be reported as unhealthy.

## SDD-018 · Model inventory collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R5

**Design.** Incremental HF-cache walk with an `(path, mtime, size)` cache; `ollama list` when present;
configured scan roots for loose weights. Reads `config.json` for R5.4 facts. Chunked so a cold scan
never blocks the loop.

**Acceptance criteria**
1. `test_hf_cache_walk_from_fixture_tree` — repo id, revision, size, last used.
2. `test_incremental_rescan_skips_unchanged` — a second scan does no filesystem work for unchanged
   entries.
3. `test_cold_scan_does_not_block_event_loop` — the API stays responsive during a large scan (R5.5).
4. `test_config_json_facts_extracted` — `max_position_embeddings`, params, quantization, MoE active.
5. `test_malformed_config_json_tolerated` — one bad model does not fail the section.
6. `test_credential_files_never_read` — a `token` or `.env` inside a scan root is never opened (S9).
7. `test_ollama_absent_is_not_an_error`.

## SDD-019 · Python environment collector
**Phase** 1 · **Status** BLOCKED (by SDD-002) · **Spec** R8.1

**Acceptance criteria** 1. `test_venv_and_conda_discovery_under_roots`. 2. `test_torch_detected_from_dist_metadata_without_import` — asserts torch is **never imported** in-process. 3. `test_python_version_from_pyvenv_cfg`. 4. `test_results_cached_between_intervals`. 5. `test_broken_env_skipped_not_fatal`.

## SDD-030 · Action runner + action log
**Phase** 2 · **Status** BLOCKED (by SDD-006) · **Spec** S5, S7 · **Arch** §8

**Acceptance criteria**
1. `test_action_refused_when_control_disabled` — 403, and nothing executed.
2. `test_action_requires_token`.
3. `test_every_action_appends_to_log` — timestamp, identity, action, target, result.
4. `test_failed_action_also_logged` — failures are logged, not swallowed.
5. `test_action_log_append_only` — the runner never rewrites prior lines.
6. `test_action_log_survives_restart`.

## SDD-031 · Container lifecycle actions
**Phase** 2 · **Status** BLOCKED (by SDD-030, SDD-012) · **Spec** R2.6

**Acceptance criteria** 1. `test_start_stop_restart_call_docker_correctly`. 2. `test_unknown_container_404`. 3. `test_docker_error_returns_result_envelope_not_500`. 4. `test_stop_respects_timeout_then_reports`. 5. `test_no_destructive_action_exposed` — no route removes a container, image, or volume.

## SDD-032 · Launch catalog + memory budget guard
**Phase** 2 · **Status** BLOCKED (by SDD-030) · **Spec** R2.7–R2.9 · **Arch** §8

**Design.** TOML catalog loader with validation and param substitution. Three enforced host rules:
image pin (`vllm-spark:local`), unified-memory budget ≤ 0.70 summed across running catalog servers,
loopback bind default.

**Acceptance criteria**
1. `test_catalog_loads_and_validates_default_entries`.
2. `test_launch_builds_expected_docker_args` — snapshot-tested against the known-good invocation.
3. `test_bind_defaults_to_loopback` — the generated publish is `127.0.0.1:PORT:PORT`; a bare
   `PORT:PORT` never appears (R2.9).
4. `test_budget_guard_refuses_over_070` — refusal names the running servers and their totals.
5. `test_budget_guard_sums_only_running_catalog_servers`.
6. `test_unpinned_vllm_image_warns` — an image other than `vllm-spark:local` produces the driver
   warning (this is the trap that costs an hour).
7. `test_deep_gemm_env_always_set` — `VLLM_USE_DEEP_GEMM=0` on every vLLM entry (sm_121).
8. `test_free_form_docker_args_rejected` — only declared params are substitutable (R2.7).
9. `test_param_substitution_is_not_shell_interpolation` (S8).

## SDD-033 · Process kill action
**Phase** 2 · **Status** BLOCKED (by SDD-030, SDD-011) · **Spec** S6

**Acceptance criteria**
1. `test_kill_refuses_pid_1`; 2. `test_kill_refuses_kernel_thread` (no cmdline);
3. `test_kill_refuses_other_users_process`; 4. `test_kill_refuses_own_process_tree`;
5. `test_kill_sends_sigterm_then_sigkill_after_grace`;
6. `test_refusal_message_states_reason` (FE-2.3 depends on this).

## SDD-034 · Container log streaming
**Phase** 2 · **Status** BLOCKED (by SDD-012) · **Spec** R2.5

**Acceptance criteria** 1. `test_log_tail_bounded` — a huge log does not stream unbounded. 2. `test_client_disconnect_closes_docker_stream`. 3. `test_binary_log_output_does_not_crash_encoder`. 4. `test_log_route_requires_auth`.

## SDD-040 · Frontend foundation
**Phase** 3 · **Status** BLOCKED (by SDD-005) · **Spec** FE-C1–C10 · **Arch** §9

**Foundation slice — ONE owner. Later frontend slices inherit its conventions as BINDING.**

**Design.** Vite + React + TS + Tailwind. Design tokens including the FE-C4 exposure vocabulary.
App shell with nav and connection indicator. `SSEProvider` owning the single stream with ticket
acquisition, backoff reconnect, and section context. Panel primitives implementing FE-C2/C3.
OpenAPI → TS type generation wired as a build step.

**Acceptance criteria**
1. `test_sse_provider_reconnects_with_backoff`.
2. `test_panel_renders_last_known_data_on_error` with a staleness badge (FE-C3).
3. `test_unavailable_renders_calm_not_error` (FE-C2).
4. `test_exposure_badge_vocabulary` — all four levels render with their defined styles (FE-C4).
5. `test_generated_types_match_openapi` — CI regenerates and asserts no diff (§11 seam).
6. `test_shell_usable_at_390px` — no horizontal page scroll (FE-C8).
7. `test_actions_disabled_with_explanation_when_control_off` (FE-C6).
8. Report the breakpoint variants and utility classes established here; they are BINDING on
   SDD-041…048.

## SDD-041…SDD-047 · Feature pages
**Phase** 3 · **Status** BLOCKED (by SDD-040 + the named collector) · **Spec** FE-1…FE-7

Each page entry's acceptance criteria are **its FE requirements, one named test per numbered FE
item**, plus these three, which apply to every page:
- `test_page_renders_from_stream_not_own_fetch` (FE-C1/§9 one data source);
- `test_section_error_isolated_to_its_panel` (FE-C2);
- `test_confirm_required_for_mutating_action`, where the page has actions (FE-C5).

Expand each into its own full entry when picked up. Two page-specific criteria are called out now
because they are easy to get wrong:
- **SDD-046 / FE-6.2** — `test_service_link_correct_for_client_origin`: a loopback link must not be
  emitted to a tailnet client.
- **SDD-047 / FE-7.4** — `test_shared_tailnet_banner_present`: the warning is not optional copy.

## SDD-048 · Settings / action log / doctor page
**Phase** 3 · **Status** BLOCKED (by SDD-040, SDD-052) · **Spec** FE-8

**Acceptance criteria** 1. `test_effective_config_rendered`. 2. `test_token_never_rendered` (S2). 3. `test_action_log_paginates`. 4. `test_doctor_output_rendered_per_source`. 5. `test_no_credential_values_rendered` (S9).

## SDD-050 · systemd --user unit + installer
**Phase** 4 · **Status** BLOCKED (by SDD-001) · **Spec** N6

**Design.** `deploy/dgxctl.service` for `systemctl --user`; `deploy/install.sh` unprivileged —
builds the frontend, installs the package, writes the unit, enables it. **No `sudo` anywhere.**

**Acceptance criteria** 1. `test_install_script_uses_no_sudo` — a grep-level assertion. 2. `test_unit_file_valid` via `systemd-analyze verify`. 3. `test_installer_idempotent` — running twice is safe. 4. Live: the service survives logout (lingering).

## SDD-051 · NVIDIA Sync custom tool integration
**Phase** 4 · **Status** BLOCKED (by SDD-050) · **Spec** R7 · **Arch** §10

**Design.** `deploy/nvidia-sync-launch.sh` per §10, plus README documentation of the exact Name /
Port / URL Path / Launch Script / Launch-in-Terminal values (R7.5).

**Acceptance criteria**
1. `test_launch_script_idempotent` — with the port already listening, it exits 0 and starts nothing
   (R7.4).
2. `test_launch_script_no_tty_required` — runs correctly in background mode.
3. `test_launch_script_does_not_block` — returns promptly.
4. `test_single_port_serves_ui_and_api` — the built SPA and `/api/*` on one port (R7.3).
5. `test_readme_documents_all_dialog_fields` — Name, Port, URL Path, Launch Script, Launch in
   Terminal all documented (R7.5).
6. Live: registered in NVIDIA Sync, opens, and lands authenticated.

## SDD-052 · `dgxctl doctor` preflight
**Phase** 4 · **Status** BLOCKED (by SDD-002) · **Spec** R8.3

**Acceptance criteria** 1. `test_doctor_reports_every_registered_source`. 2. `test_doctor_exit_code_nonzero_on_hard_failure`. 3. `test_doctor_distinguishes_unavailable_from_error`. 4. `test_doctor_names_the_fix` for each known failure mode. 5. `test_doctor_runs_without_the_service_running`.

## SDD-053 · Live verification on real hardware
**Phase** 4 · **Status** BLOCKED (by SDD-051) · **Spec** all · **Arch** §12

**Not a test suite — a live checklist against the real box.** The suite cannot see driver quirks,
real cgroup layouts, or a genuinely exposed socket. Expect this to find bugs; file each as a new SDD.

**Checklist**
1. `dgxctl doctor` — every source resolves as expected on the real host.
2. GPU panel matches `nvidia-smi` for utilization and memory.
3. A running vLLM container's GPU memory attributes to that container (the SDD-011 seam, live).
4. `ss -tln` on the box agrees with the network panel, including every `0.0.0.0` line.
5. Tailscale panel matches `tailscale status`.
6. HF cache total agrees with `du -sh ~/.cache/huggingface` (±5%).
7. Stop and restart a throwaway container from the UI; confirm the action log entry.
8. Launch the catalog's Jupyter entry; confirm it publishes on loopback only.
9. Attempt a launch that would exceed the 0.70 budget; confirm refusal names the running servers.
10. From another tailnet machine: confirm the dashboard requires the token and that no route leaks
    host data unauthenticated.
11. Register in NVIDIA Sync; open; confirm it lands authenticated on one port.
12. Leave it running an hour; confirm idle CPU against N1 and that history pruning holds the size
    ceiling.

## SDD-100 · Process launchables in the catalog
**Phase** 6 · **Status** TODO · **Spec** R10.1–R10.3, R10.7 · **Arch** §8, §14

**Design.** Catalog entries gain `kind` (`container` | `process`). A process entry declares an
argv `command` with the same `{param}` substitution containers use — no free-form commands from
the browser. `ProcessLauncher` spawns it detached via `start_new_session=True`, redirects
stdout/stderr to `~/.local/share/dgxctl/logs/<entry>.log`, and records
`{entry, pid, port, started_at, log}` in `~/.local/share/dgxctl/processes.json`.

**Acceptance criteria**
1. `test_process_entry_parses_and_validates`; 2. `test_process_command_is_argv_not_shell` (S8);
3. `test_unknown_param_rejected_for_process_entry`;
4. `test_launch_records_pid_and_log_path`; 5. `test_launched_process_is_detached_from_the_server`
   (new session id, survives the request); 6. `test_stdout_captured_to_the_log_file`;
7. `test_process_entry_defaults_to_loopback_bind` (R10.7);
8. `test_stop_uses_the_same_refusal_rules_as_kill` (S6);
9. `test_registry_survives_restart_and_prunes_dead_pids`.

## SDD-101 · Adopt an already-running instance
**Phase** 6 · **Status** TODO · **Spec** R10.4

**Design.** Before launching, look for a live instance: a pid in the registry that is still
running, or any process whose argv matches the entry's executable, or the entry's port already
listening. An adopted instance is reported with its pid and origin (`dgxctl` or `external`).

**Acceptance criteria**
1. `test_running_instance_is_adopted_not_duplicated` — launching returns the existing instance.
2. `test_externally_started_instance_is_adopted` — a JupyterLab started from a terminal (the DGX
   Dashboard's own path) is found and shown, not ignored.
3. `test_dead_pid_in_registry_does_not_block_a_launch`.
4. `test_port_in_use_by_something_else_refuses_with_the_owner_named`.

## SDD-102 · JupyterLab entry + venv selection
**Phase** 6 · **Status** TODO · **Spec** R10.6

**Design.** A shipped `jupyterlab` process entry whose `venv` param is a `venv_ref`: the UI offers
the GPU-capable environments the pyenv collector (SDD-019) already finds, defaulting to
`~/jupyterlab/.venv`. The command matches what NVIDIA Sync's dashboard runs.

**Acceptance criteria**
1. `test_jupyter_entry_builds_the_expected_argv`;
2. `test_venv_ref_param_resolves_to_the_venv_binary`;
3. `test_missing_venv_refuses_with_a_useful_message`;
4. `test_jupyter_binds_loopback_by_default`.

## SDD-103 · Access endpoints and credential links
**Phase** 6 · **Status** TODO · **Spec** R11 · **Arch** §14

**Design.** `endpoints.py` derives, per service, everything needed to *use* it: the path, an
`auth_query` where a credential can be read locally, an `auth_hint` where it cannot, and an
OpenAI `base_url` for model servers. JupyterLab's token comes from
`~/.local/share/jupyter/runtime/jpserver-<pid>.json`, matched to a live pid. The client composes
the final origin, because only the browser knows how the viewer reached the dashboard.

**Acceptance criteria**
1. `test_jupyter_token_read_from_runtime_file`;
2. `test_jupyter_runtime_file_for_a_dead_pid_is_ignored` — a stale file must not produce a link;
3. `test_no_credential_yields_a_hint_not_a_broken_link` (R11.6);
4. `test_openai_services_expose_base_url_and_model`;
5. `test_credentials_never_appear_in_a_section_that_is_not_the_service_itself`;
6. `test_auth_query_absent_when_the_service_needs_no_token`.

## SDD-104 · Declarable services
**Phase** 6 · **Status** TODO · **Spec** R12

**Acceptance criteria**
1. `test_declared_service_appears_when_offline` (R12.2);
2. `test_declared_service_merges_with_a_live_listener_on_the_same_port`;
3. `test_declared_launch_requires_the_control_gate` (R12.3);
4. `test_declared_launch_is_argv_not_shell`;
5. `test_declared_service_survives_a_config_with_no_launch_command`.

## SDD-105 · NVIDIA Sync registration CLI
**Phase** 6 · **Status** TODO · **Spec** R13

**Design.** Sync stores custom tools as a JSON array at
`~/.config/NVIDIA/Sync/config/custom.json`, entries shaped
`{id, port, name, scriptContent, autoOpen, url, interactive, shown}`. `dgxctl sync register`
appends or updates one entry; `sync list` and `sync unregister` complete the loop. The file is
backed up before every write and existing entries are preserved untouched.

**Acceptance criteria**
1. `test_register_preserves_existing_entries` — an unrelated tool must survive;
2. `test_register_is_idempotent_by_name`;
3. `test_backup_written_before_any_modification`;
4. `test_unregister_removes_only_the_named_entry`;
5. `test_missing_sync_config_is_reported_not_created_silently` (R13.5);
6. `test_malformed_sync_config_is_refused_without_writing` — never clobber a file we cannot parse;
7. `test_registration_never_happens_on_startup` (R13.2).

## SDD-106 · Services page: launch, links, reveal
**Phase** 6 · **Status** TODO · **Spec** FE-9

**Acceptance criteria**
1. `test_credential_is_masked_until_revealed` (R11.3);
2. `test_copy_gives_the_full_authenticated_url`;
3. `test_loopback_service_viewed_remotely_offers_a_tunnel_command` (R11.4);
4. `test_offline_declared_service_still_renders_with_a_launch_control`;
5. `test_launch_controls_disabled_with_an_explanation_when_control_is_off` (FE-C6).

## SDD-120 · Environment detection for onboarding
**Phase** 7 · **Status** TODO · **Spec** R14.2

**Design.** `onboarding.detect()` returns an `Environment` dataclass describing what this machine
offers: python version, arch, NVML, Docker socket, `ss`, `du`, Tailscale (installed / backend
state / tailnet IP / MagicDNS name / already serving), NVIDIA Sync config path, `systemd --user`,
lingering, an existing dgxctl config, and whether a token already exists. Every probe is
best-effort: a missing tool is a fact to report, never an error.

**Acceptance criteria**
1. `test_detect_never_raises_on_a_bare_machine` — with nothing installed, every field is populated
   and no exception escapes.
2. `test_detect_reports_tailscale_absent_distinctly_from_logged_out`.
3. `test_detect_finds_an_existing_config_and_token`.
4. `test_detect_is_read_only` — detection writes nothing.

## SDD-121 · Bind-option planning
**Phase** 7 · **Status** TODO · **Spec** R14.3, R14.4

**Design.** `bind_options(env)` is a **pure function** of the detected environment returning the
choices to present, each with its reach, whether it needs root, and whether it is available here.
Keeping it pure is what makes the decision testable without a terminal.

**Acceptance criteria**
1. `test_loopback_is_always_offered_and_is_the_default`.
2. `test_tailnet_options_absent_without_tailscale` (R14.2).
3. `test_tailnet_serve_option_declares_its_root_requirement`.
4. `test_all_interfaces_option_states_it_reaches_the_lan`.
5. `test_tailnet_address_only_option_warns_it_breaks_nvidia_sync`.
6. `test_every_option_carries_a_reach_description` — no unexplained choice.

## SDD-122 · `dgxctl onboard` wizard
**Phase** 7 · **Status** TODO · **Spec** R14.1, R14.5–R14.9

**Design.** Interactive by default; every answer also settable by flag so the whole run can be
unattended. Steps: detect → choose bind → token → control gate → NVIDIA Sync → write config
(backing up) → install and enable the user service → verify it answers → print how to reach it.

**Acceptance criteria**
1. `test_noninteractive_run_needs_no_tty` (R14.8).
2. `test_choosing_a_nonloopback_bind_creates_a_token` — onboarding can never leave the service in
   a state where the bind guard refuses to start it (R14.4).
3. `test_control_defaults_to_off` (R14.5).
4. `test_existing_config_is_backed_up_before_being_replaced` (R14.7).
5. `test_rerun_offers_current_values_as_defaults` (R14.7).
6. `test_sync_registration_skipped_when_sync_is_absent` (R14.6).
7. `test_written_config_is_valid_and_round_trips` through `load_settings`.
8. `test_no_step_requires_sudo` (R14.1).

## SDD-123 · install.sh runs onboarding
**Phase** 7 · **Status** TODO · **Spec** R14.1

**Acceptance criteria** 1. `test_install_script_invokes_onboarding`. 2. `test_install_script_supports_skipping_onboarding` for scripted installs. 3. `test_install_script_checks_the_python_version`. 4. Existing: no sudo, strict mode, idempotent.

## SDD-124 · Repo layout and licence
**Phase** 7 · **Status** TODO

**Design.** Process documentation moves under `docs/`, leaving a root that reads as a product:
README, CLAUDE.md, config.example.toml, pyproject.toml. Add the MIT licence the package metadata
already claims. *(Superseded in part by SDD-161: the project relicensed to Apache 2.0 before its
first release. The requirement — ship the licence the metadata declares — is unchanged.)* Add a link checker so the move cannot silently break references.

**Acceptance criteria**
1. `test_licence_file_exists_and_matches_package_metadata`;
2. `test_no_broken_relative_links_in_markdown` — every `[x](y)` target resolves;
3. `test_readme_documents_every_nvidia_sync_dialog_field` (existing, must survive the move).

## SDD-130 · Known-service catalog with explanations
**Phase** 8 · **Status** TODO · **Spec** R15.1, R15.4–R15.7

**Design.** `services_catalog.py` holds what dgxctl knows about a service kind: display label, a
one-line summary of what it is, a category (`llm` | `notebook` | `agent` | `tool` |
`infrastructure`), the browsable path, the OpenAI API path where there is one, and whether a
browser is even the right client. Anything not in the catalog is `unknown` and hidden by default.

**Acceptance criteria**
1. `test_every_catalog_entry_has_a_label_summary_and_category` — an entry with no explanation
   would defeat the point.
2. `test_model_servers_declare_an_api_path`;
3. `test_infrastructure_kinds_are_categorised_as_such` for ssh, dns, mdns, cups, tailscale,
   docker-proxy, iron-proxy;
4. `test_unknown_kind_falls_back_to_unknown_category`;
5. `test_agents_are_categorised_as_agents` for hermes and openclaw.

## SDD-131 · Classify by command line, not port alone
**Phase** 8 · **Status** TODO · **Spec** R15.3

**Design.** Resolve each listener's pid to its cmdline and classify from that. Eight ZMQ ports
belonging to one `ipykernel_launcher` are a notebook's plumbing, not eight services.

**Acceptance criteria**
1. `test_ipykernel_ports_are_infrastructure_not_services` — the live case: eight ports, one kernel.
2. `test_tailscale_own_listeners_are_infrastructure` — including the `:443` it binds on the
   tailnet address.
3. `test_iron_proxy_is_infrastructure`;
4. `test_cmdline_beats_a_port_hint` — a vLLM on 8888 is a model server, not a notebook;
5. `test_unreadable_cmdline_degrades_to_the_port_hint` — another user's process still classifies.

## SDD-132 · Host address inventory
**Phase** 8 · **Status** TODO · **Spec** R16.1

**Design.** Report loopback, every routable LAN address, and the Tailscale address and MagicDNS
name. Docker bridges and link-local addresses are excluded from "LAN" — they are not somewhere a
viewer can be.

**Acceptance criteria**
1. `test_lan_addresses_exclude_docker_bridges_loopback_and_tailnet`;
2. `test_multiple_lan_addresses_are_all_reported` — this machine has two;
3. `test_tailnet_name_and_ip_reported_when_available`;
4. `test_absent_tailscale_yields_no_tailnet_fields_not_an_error`.

## SDD-133 · Reachability planner
**Phase** 8 · **Status** TODO · **Spec** R16.2–R16.7

**Design.** A **pure function** of (service bind, service port, viewer origin, host addresses)
returning the access plan: direct URLs that will work, and/or the port-forward command that makes
one, with the forward targeting an address the viewer can reach. Pure so the matrix is testable
without a browser.

**Acceptance criteria** — one per row of the matrix:
1. `test_lan_viewer_all_interfaces_service_links_to_the_lan_address`;
2. `test_lan_viewer_loopback_service_gets_a_forward_command_naming_the_lan_address`;
3. `test_tailnet_viewer_all_interfaces_service_links_to_the_tailnet_name`;
4. `test_tailnet_viewer_loopback_service_forwards_via_the_tailnet_name`;
5. `test_loopback_viewer_states_both_on_box_and_forwarded_cases` (R16.4);
6. `test_docker_bridge_bind_is_treated_as_host_only` (R16.6);
7. `test_tailnet_bound_service_is_unreachable_from_a_lan_viewer` and says so (R16.7);
8. `test_forward_command_never_contains_a_placeholder_host` (R16.5);
9. `test_a_service_on_the_dashboards_own_port_is_not_offered_a_forward`.

## SDD-134 · Services page, grouped and explained
**Phase** 8 · **Status** TODO · **Spec** FE-10

**Acceptance criteria**
1. `test_services_render_under_category_headings`;
2. `test_empty_categories_are_omitted`;
3. `test_infrastructure_hidden_behind_one_labelled_toggle`;
4. `test_every_visible_card_has_a_summary`;
5. `test_viewer_position_is_stated`;
6. `test_no_card_offers_a_link_that_cannot_work_from_here`.

## SDD-140 · Private-data guard for a public repo
**Phase** 9 · **Status** COMPLETE · **Spec** N8

**Design.** `tests/unit/test_no_private_data.py` scans every tracked text file for host-specific
data: Tailscale ULA and CGNAT addresses, MagicDNS hostnames, personal home paths, and
credential-shaped strings. Patterns are built from parts so the test does not itself contain the
strings it forbids, and known-good values sit in an explicit allowlist — a **new** address fails
the test until someone confirms it is not real.

Reviewing once is not enough: fixtures are captured from live machines, so a real address arrives
with them by default. It has to be a test.

**Acceptance criteria**
1. `test_no_real_tailnet_addresses` — the ULA prefix is universal to Tailscale, but the node
   suffix identifies a machine.
2. `test_no_real_magicdns_hostnames`;
3. `test_no_personal_home_paths` — a placeholder account is fine, a real one is not;
4. `test_no_credentials_or_keys`;
5. `test_local_notes_are_not_tracked` — `LOCAL.md`, tokens, `.env`.
6. Verified by planting a real-looking address and confirming the guard fails.

**Found on the first run.** Three peers' real tailnet IPv6 addresses in
`tests/fixtures/tailscale_status.json` — other people's machines, missed by an earlier manual
scrub that only replaced the `TailscaleIPs` field. Also a real tailnet address in a docstring
example, and the reference machine's LAN addresses in tests (now RFC 5737 documentation values).

## SDD-150 · Path traversal in the SPA handler — CRITICAL
**Phase** 9 · **Status** COMPLETE · **Spec** S1

**The defect.** The catch-all that serves the built UI joined attacker-controlled path segments
onto the web root and served whatever came back, with **no authentication**. Two ways out:

- `GET /../../etc/passwd` — ordinary `..` traversal.
- `GET //etc/passwd` — an **absolute** path. `Path("/srv/web") / "/etc/passwd"` does not join;
  it substitutes, discarding the base entirely. This one needs no traversal at all.

Confirmed reading `/etc/passwd`, `/etc/hosts`, and — decisively — the service's own API token at
`~/.config/dgxctl/token`. Reading the token converts an unauthenticated file read into a **complete
authentication bypass**, including control actions, on an instance bound beyond loopback.

**Why review missed it.** The `test_every_route_requires_auth` sweep enumerated the *routers*.
The SPA route is registered on the app, so the sweep never saw it (SDD-152). And a probe written
with an HTTP client passes against a vulnerable server, because the client normalises `..` out of
the path before it is sent — the request never arrives in its attacking form.

**The fix.** Resolve the candidate and require `Path.is_relative_to(web_root)` before serving.

**Acceptance criteria** (all in `tests/integration/test_path_traversal.py`, which drives the ASGI
app directly so no client normalises the payload):
1. `test_dot_dot_traversal_is_refused` — six encodings.
2. `test_absolute_path_injection_is_refused` — the substitution case.
3. `test_the_services_own_token_cannot_be_read` — the escalation that made this critical.
4. `test_legitimate_assets_are_still_served`, `test_unknown_paths_still_fall_back_to_the_spa`,
   `test_api_paths_are_not_swallowed_by_the_spa` — the fix must not break the UI.
5. `test_process_log_names_reject_separators` — defence in depth on the one other request-driven
   filesystem read.
6. Verified failing against the pre-fix code, then passing, then confirmed on the live service
   with `curl --path-as-is`.

## SDD-151 · Restrictive modes on files dgxctl writes
**Phase** 9 · **Status** COMPLETE · **Spec** S2

`config.toml`, `actions.jsonl`, `processes.json` and `history.db` were created under the process
umask, landing at 664/644 on a stock Ubuntu — group-writable and world-readable. `config.toml` can
hold a **peer instance's API token** and decides the bind address; the action log records who asked
for what. All are now created 0600, matching the token file.

**Acceptance criteria**
1. `test_files_written_by_dgxctl_are_not_world_readable`;
2. existing `test_token_file_with_loose_permissions_is_refused` still holds.

## SDD-152 · The auth sweep must see app-level routes
**Phase** 9 · **Status** COMPLETE · **Spec** S1

`collect_routes` walked only the routers, so any route registered directly on the app was outside
the sweep — which is how an unauthenticated file-serving route survived it. It now walks
`app.routes` as well, with an explicit `PUBLIC_BY_DESIGN` set so a public route is a decision
someone wrote down rather than an omission.

**Acceptance criteria**
1. `test_the_route_sweep_actually_sees_the_app_level_routes`;
2. every route not in `PUBLIC_BY_DESIGN` returns 401/403 without a token.

## SDD-161 · Relicence MIT → Apache 2.0
**Phase** 9 · **Status** COMPLETE

**Why.** The audience is companies and labs running DGX hardware, where legal review treats
Apache 2.0 as the safe default because its patent grant is explicit; MIT is silent on patents and
whether an implied licence exists is untested. Apache §5 also puts contributions under the same
terms without a separate CLA, which matters for a project that invites them.

Done before the first release and before any outside contribution, while the sole copyright holder
could still relicense unilaterally — 0 forks, 1 contributor. After that it would need every
contributor's agreement.

**Changes.** `LICENSE` replaced with the canonical text fetched from apache.org (not reproduced
from memory); `NOTICE` added, since §4(d) only means something if one is shipped;
`pyproject.toml` declares `Apache-2.0` plus the OSI classifier; README badge and licence section
updated. No per-file SPDX headers: the appendix suggests them, they are not required, and they
would touch every file for no practical gain on a project this size.

**Acceptance criteria**
1. `test_licence_exists_and_matches_package_metadata` — now maps the SPDX id to a phrase that must
   appear in the licence text, so a mismatch between metadata and file is caught for any licence.
2. `test_apache_notice_file_is_shipped`;
3. `test_the_licence_text_is_complete` — a truncated licence is worse than none, so the sections
   that motivated the choice are asserted present.
4. Installed package metadata reports `Apache-2.0` and the OSI classifier.

## SDD-060 · vLLM `/metrics` scraping — DEFERRED
Scrape running vLLM servers' Prometheus endpoint for queue depth, throughput, and TTFT — far richer
than `/v1/models`. Prior art: [spark-dashboard](https://github.com/niklasfrick/spark-dashboard).

## SDD-061 · Alerting / notification delivery — DEFERRED
Out of scope per spec §6. Findings are surfaced in-UI only for v1.
