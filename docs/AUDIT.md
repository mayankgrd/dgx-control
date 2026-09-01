# AUDIT.md — Session log

Required at the end of every session. Newest entry first.

**Entry format:** date + title · user requests (numbered) · completed work (checkboxes) · changes by
file · commits · technical notes (patterns, decisions, gotchas).

---

## 2026-09-01 — CLAUDE.md shortened

### User request
1. Simplify CLAUDE.md before the release. Keep the spec-driven-development intent intact; only
   shorten.

### Completed
- [x] 212 lines down to 154, with the loop, the source-of-truth order, the session workflow and the
      hardware facts all intact.

### What was cut, and why

**The subagent delegation playbook (22 lines).** Inherited boilerplate describing worktree
isolation, model selection per slice, file-ownership per wave and a degradation ladder. None of it
was ever used — the whole project was built inline, and no commit mentions a worktree or a subagent.
A working agreement that describes a process nobody follows teaches the next reader the wrong thing.

**Generic advice.** "Think before coding", "simplicity first", "surgical changes" apply to any
project and earn nothing here. The hardware facts and the seam doctrine are the parts that could not
be guessed, so they stayed.

**Duplication.** The live-verification bar was stated twice, once at the top and again in a closing
"the live bar is not optional" section. Now once.

### What was corrected

The spec ranges were stale: `R1…R8, S1…S9, N1…N7` had become `R1…R16, S1…S11, N1…N8`. The stack line
said Python 3.12 where `requires-python` is `>=3.11`. A file that tells the next reader where truth
lives should not itself be out of date.

### What was added

Two lessons this session paid for, in one line each: the wiring seam (a function grows a parameter,
its unit tests pass, the caller never passes it, the feature is complete and inert — three times
now), and how to write a security probe (an HTTP client normalises `..` out of a path, so a
traversal test written with one passes against a vulnerable server).

---

## 2026-09-01 — Relicensed to Apache 2.0

### User request
1. Asked for the difference between MIT and Apache 2.0, and which to use. Chose Apache 2.0.

### Completed
- [x] `LICENSE` replaced with the canonical Apache 2.0 text, `NOTICE` added, `pyproject.toml`
      updated with the SPDX id and OSI classifier, README badge and licence section updated.
- [x] Tests: the licence check now maps an SPDX id to a phrase expected in the file, so it works
      for any licence rather than only the one in place when it was written. Added checks that a
      NOTICE ships and that the licence text is complete.

### Technical notes

**The reasoning, briefly.** Both are permissive with the same practical core. Apache adds an
explicit patent grant, patent retaliation, a state-your-changes requirement, a trademark
disclaimer, and §5, which puts inbound contributions under the same terms without a CLA. For a
tool whose users are companies with DGX hardware, the explicit patent grant is what removes
friction from legal review. Patent risk for an ops dashboard is near nil either way; the choice is
about how easily others can adopt it.

**Timing was the strongest argument.** Relicensing needs every copyright holder's agreement. With
0 forks and 1 contributor that was a formality; after the first outside contribution it would not
have been. Doing it before the release cost nothing.

**The licence text was fetched, not written.** A legal document reproduced from memory is a bad
idea, and a truncated one is worse than none — hence a test asserting the patent grant,
redistribution, warranty and liability sections are all present.

**SDD-124 says "add the MIT licence" and still does.** The project's rule is that entries are
marked, not rewritten, so it carries a note pointing at SDD-161 instead of being edited to look
like it always said Apache.

---

## 2026-09-01 — README trimmed, methodology moved out

### User request
1. The "How this project is built" section is too long; move it to `docs/`. Make the README simple
   and clean, focused on what the tool is useful for, direct in tone and concise in prose.

### Completed
- [x] Methodology moved verbatim to [`docs/methodology.md`](methodology.md), with its relative
      links re-rooted for its new location.
- [x] README rewritten: 316 lines down to 212. Shorter sentences, no throat-clearing, every
      feature heading now says what the tool *does for you* rather than naming a page.
- [x] A two-sentence **Contributing** section keeps the one part of the methodology a reader
      actually needs at the front door: write a numbered requirement in `docs/spec.md`.
- [x] `CLAUDE.md` points at the new doc instead of a README section that no longer exists.

### Technical notes

**Feature headings now lead with the verb.** "Which container is holding the GPU" became "Finds
which container is holding the GPU"; "How to actually reach your services" became "Tells you how to
reach everything that is running". A heading that names a page describes the software; a heading
that names an action describes what the reader gets.

**The methodology was not shortened, only relocated.** It is worth having in full — it is how
contributions are meant to arrive — but it is not what someone deciding whether to install the tool
needs in their first minute. Only its two load-bearing sentences stayed in the README, under
Contributing.

**Longest remaining paragraph is 72 words**, and that is the opening description, which earns it.
Everything after is under 65.

---

## 2026-09-01 — Security review of the whole repo

### User request
1. Perform a security review of the entire repo. (Their `/security-review` had failed because
   `origin/HEAD` was unset after the repo was recreated; fixed with `git remote set-head origin -a`.)

### Findings

**CRITICAL — unauthenticated arbitrary file read (SDD-150).** The catch-all serving the built UI
joined attacker-controlled path segments onto the web root and served whatever came back, with no
authentication. Two escapes, both confirmed working against a running instance:

- `GET /../../etc/passwd` — ordinary traversal.
- `GET //etc/passwd` — an absolute path. `Path("/srv/web") / "/etc/passwd"` does not join, it
  **substitutes**, discarding the base. No traversal sequence needed at all.

Confirmed reading `/etc/passwd`, `/etc/hosts`, and the service's own API token. That last one turns
the read into a **complete authentication bypass** — token in hand, an attacker has every route
including control actions. The reference machine was bound to `0.0.0.0` at the time, so it was
reachable from the LAN and the tailnet. Fixed, deployed, and re-verified against the live service
with `curl --path-as-is`.

**MEDIUM — files created under the umask (SDD-151).** `config.toml`, `actions.jsonl`,
`processes.json` and `history.db` were 664/644 on a stock Ubuntu. `config.toml` can hold a peer
instance's API token and decides the bind address; the action log records who asked for what. All
0600 now, and the existing files on the reference machine were tightened.

**The test gap that allowed it (SDD-152).** `test_every_route_requires_auth` enumerated the
*routers*. The UI route is registered on the app, so the sweep never saw it. It now walks
`app.routes` too, with an explicit `PUBLIC_BY_DESIGN` set, so a public route is something someone
wrote down rather than something nobody looked at.

**Checked and clean.** Service probing is loopback-only (no SSRF from an observed address); remote
peer URLs come from operator config, not requests; no `shell=True` anywhere and every subprocess
call is argv; catalog parameters cannot reach volumes, `privileged`, or namespace options; no
`dangerouslySetInnerHTML` or `eval` in the frontend; token comparison is `hmac.compare_digest`; the
token never appears in a response, an error body, or a log line; `pip-audit` and `npm audit` both
report zero known vulnerabilities.

### Technical notes

**The probe has to be written the way an attacker sends it.** A first pass using an HTTP client
reported everything safe — because httpx normalises `..` out of the path *before* transmitting, so
the malicious request never arrives in its malicious form. A test written that way passes against a
vulnerable server and proves nothing. The regression tests drive the ASGI app directly, with the
raw path in `scope["path"]`.

**Both fixes were verified by failing first.** The traversal tests were run against the pre-fix code
(five failures), then against the fix (all pass), then against the deployed service over the LAN.

**Then CI caught what local testing could not.** The new route-sweep guard assumed the production
shape; CI has no `web/dist`, so the app registers a "UI not built" hint at `/` instead of the SPA
route, and the assertion failed. Fixed by having the test supply a build, and verified both ways by
moving `web/dist` aside and running the suite again — the environment difference was the bug, so
reproducing it was the only honest check.

### Open follow-ups
- No response security headers (`X-Content-Type-Options`, `Referrer-Policy`, a CSP). Low value for a
  single-origin dashboard with no third-party content, but cheap hardening if wanted.
- No rate limiting on token verification. The token is 32 random bytes, so guessing is not the
  threat; this would only matter against a future weaker credential.

---

## 2026-09-01 — README rebuilt, with screenshots from the live machine

### User requests
1. Clean up README.md: clear feature articulation, a catchy intro, badges for passing tests,
   clear installation instructions, a hero screenshot and some feature screenshots.

### Completed
- [x] README rewritten: centred hero with badges, a one-line pitch, install first, then features
      each illustrated by a real screenshot, then security posture and configuration.
- [x] Five screenshots captured from the live DGX and committed under `docs/screenshots/`.
- [x] `advertise_addresses` (below) — a real feature the screenshot work surfaced.
- [x] Every screenshot reviewed by eye before committing.

### Technical notes

**Capturing the screenshots needed a real browser, not a headless flag.** Firefox's `--screenshot`
does not wait for asynchronous rendering, so the first attempt produced a page reading "Waiting for
first reading…" — technically a screenshot of the product, and useless. Playwright with an explicit
wait for a delivered SSE snapshot produced the real thing.

**They were taken against a temporary no-token instance on loopback**, which is open by design
(the OS is the boundary there), so a headless browser needed no localStorage priming. A generic
`node_name` kept the machine's identity out of the header.

**A screenshot leaks what a grep cannot.** The private-data test skips binaries, so reviewing each
image by eye is part of adding one — that is now stated in the test rather than left as folklore.
The first Services capture showed the machine's real LAN address in two `ssh -N -L` commands, which
is exactly the sort of thing a text scan would never have found.

**That produced a genuine feature, not a workaround.** `advertise_addresses` lets links and
port-forward commands use a name you actually reach the machine by — `dgx.lab.internal` rather than
a raw address that may change. Plenty of people reach a DGX by name; the raw IP was never the right
default for a forward command someone is meant to copy.

**And the wiring bug returned, a third time.** `host_addresses` grew the parameter and worked in
isolation while the collector kept calling it without the argument — the same seam as the config
preservation and the `existing=` parameter before it. The pattern is always the same: `ruff format`
reflows a call, a later `str.replace` silently fails to match, and unit tests pass because the unit
is correct. There is now a wiring test asserting a configured value actually reaches the section it
is supposed to reach.

---

## 2026-09-01 — Privacy review before going public, and a documentation pass

### User requests
1. Review the codebase for anything private leaking into it before making it public.
2. Update all docs — AUDIT, SDD, architecture.

### Completed
- [x] Scanned the working tree **and every commit in history** for host-specific data,
      credentials and personal paths.
- [x] Fixed what the scan found (below) and added `tests/unit/test_no_private_data.py` (SDD-140)
      so it cannot regress.
- [x] Verified the guard by planting a real-looking address and confirming it fails.
- [x] `docs/architecture.md`: repository layout brought up to date, and four new sections —
      §13 multi-DGX, §14 service identity & reachability, §15 launchables & process lifecycle,
      §16 onboarding & installation. The section index is the load-what-you-need contract, so it
      had to stop lying about what exists.
- [x] `docs/spec.md`: N8, publishability as a requirement rather than a habit.
- [x] History squashed to a single commit at the owner's direction.

### What the review found

Nothing was a credential, and nothing was internet-routable. Ranked by what actually mattered:

1. **Three peers' real tailnet IPv6 addresses** in `tests/fixtures/tailscale_status.json` — other
   people's machines. An earlier manual scrub had replaced the `TailscaleIPs` field and missed the
   same addresses appearing in `AllowedIPs` and `PeerAPIURL`. This is precisely why the check is
   now a test: a hand scrub is a snapshot, and fixtures keep arriving from live machines.
2. **A real tailnet IPv6 address in a docstring** in `collectors/util.py`, pasted in as a worked
   example of `ss` output. (The `fd7a:115c:a1e0` prefix itself is universal to Tailscale and stays
   — it is load-bearing in the exposure classifier. Only the node suffix identifies anything.)
3. **The reference machine's LAN addresses** in tests — RFC 1918, so barely sensitive, now RFC 5737
   documentation values, which also read unambiguously as examples.
4. **The machine's hostname in git history** (19 blobs) and one `/home/nvidia/jupyterlab` path.
   Scrubbed from the tree earlier, but history is what publishing exposes.

Checked and clean: the NVIDIA Sync screenshot (every field empty), `package-lock.json`, the
generated OpenAPI document, and `.gitignore` coverage of `LOCAL.md` and token files. Fixtures were
scrubbed before their first commit, so no unscrubbed version exists in any commit.

### Technical notes

**Scrubbing the working tree is not a privacy review.** Making a repository public exposes every
blob in every commit, so the scan has to run over `git rev-list --all`, not just `HEAD`. That is
what turned up the hostname in nineteen historical blobs, invisible from the tree.

**The guard is built so it cannot leak what it forbids.** Asserting "the string `<hostname>` does
not appear" would put that hostname in the repository. It matches *shapes* instead — Tailscale ULA
and CGNAT ranges, `.ts.net` hostnames, `/home/<account>/` paths, credential prefixes — with an
explicit allowlist of documentation values. New addresses fail until someone acknowledges them,
which is the right default for this kind of check.

**Squashing beat rewriting.** The history's granularity is worth less than it looks: every design
decision and every live-hardware regression is already recorded here in AUDIT.md and in SDD.md,
with far more reasoning than a commit message carries. A squash needs no extra tooling and leaves
nothing to miss.

### Open follow-ups
- Author email remains on the commit, by choice.
- Port 11000 on the reference machine is still unidentified; it is correctly hidden rather than
  guessed at.

---

## 2026-09-01 — Services page rebuilt around "what is this, and how do I reach it"

### User requests
1. Standard services (vLLM, Ollama) should come with a clear explanation of how to access them.
2. Services needing a token (JupyterLab) should show token details, for tailnet and local alike.
3. Coding agents (Hermes, OpenClaw) should be listed clearly.
4. Non-standard services should probably not be shown; everything shown needs an explanation.
5. Access must be correct for where the viewer is: loopback services need a port forward, a
   LAN-exposed service needs the DGX's real LAN address, and NVIDIA Sync users arrive on
   loopback after a forward.

### Completed
- [x] `services_catalog.py` (SDD-130): every kind has a label, a one-line explanation of what it
      is, and a category — model server, notebook, agent, tool, infrastructure.
- [x] Classification from the listener's **command line** (SDD-131), not its port alone.
- [x] Host address inventory (SDD-132) — loopback, every LAN address, tailnet IP and MagicDNS name.
- [x] Reachability planner (SDD-133) as a pure function, mirrored in Python and TypeScript.
- [x] Services page grouped by category, each card explaining what the thing is (SDD-134).
- [x] Verified live from a LAN browser against the real box.

### Technical notes

**The page went from 22 entries to 5.** Fourteen were previously marked "notable". What was
actually being listed: eight ZMQ ports belonging to a single notebook kernel, five internal ports
of the Hermes agent runtime's proxy, Tailscale's own ephemeral listeners, SSH, DNS and CUPS. None
of those are things an operator starts or acts on. They are still in the payload — hiding them
from the default view is a presentation decision, and silently dropping them would make the
exposure audit dishonest.

**Classification had to move to the command line.** A port hint cannot tell eight kernel ports
apart from eight services, and it gets the interesting case backwards: a vLLM server on 8888 is a
model server, not a notebook. The port is now the last resort, used only when `ss` shows no pid
because the socket belongs to another user. One heuristic earns its place: an unidentified
listener bound to the node's *own tailnet address* is the Tailscale daemon, because nothing else
binds there.

**Reachability is a matrix, not a boolean.** The previous code asked one question — "is the viewer
local?" — which is wrong in both directions. The answer depends on where the viewer is AND what
the service is bound to, and there is a third case that neither reading covers: a viewer at
127.0.0.1 might have a browser on the DGX, or might have arrived through NVIDIA Sync's port
forward, and **the server cannot tell those apart**. The page now states both, because guessing
either way is wrong half the time. It is a pure function of (bind, port, viewer origin, host
addresses), which is what makes the whole matrix testable without a browser; the same logic exists
twice, in Python for the API and TypeScript for the page, with matching test suites.

**A forwarded service still has an API endpoint.** The first cut only rendered the OpenAI base URL
when a direct route existed, so a loopback-bound vLLM viewed from the LAN showed a tunnel command
and nothing else — the one fact a model server exists to provide was missing.

**Launched-process lifecycle: corrected by the owner.** Finding that restarting dgxctl killed the
JupyterLab it had launched, `KillMode=process` was added so workloads would survive. The owner
said the original behaviour was correct: dgxctl owns what it started. That is the better model —
a restart must not bypass the Stop button and leave dgxctl believing it manages something it no
longer controls. Reverted, and verified both halves live: a dgxctl-launched notebook stops with
the service, one started from a terminal is untouched because it is in a different cgroup. The
unit now documents why `KillMode` is deliberately unset, with a test so nobody re-adds it. The
uninstaller's claim that it "leaves your workloads running" was wrong under this model and has
been corrected.

### Open follow-ups
- Two Hermes backends appear as two agents; they are genuinely two per-session processes, but a
  future pass could group per-session backends under one entry.
- Port 11000 remains genuinely unrecognised on the reference machine.

---

## 2026-09-01 — `dgxctl` on PATH, and a re-run that keeps your settings

### User request
1. Make sure the installation puts `dgxctl` on PATH so people can actually use it.

### Completed
- [x] Installation now symlinks `~/.local/bin/dgxctl` → the venv console script, and only when
      that directory is not already on PATH does it append a guarded line to the shell files
      that exist (SDD-125). Works from `--no-onboard` installs too.
- [x] Verified on real hardware with a throwaway `$HOME`: `dgxctl version` runs by name from a
      fresh **login** shell and a fresh **interactive** shell.
- [x] Fixed SDD-126: re-running onboarding silently discarded declared services, peer nodes and
      any other setting it does not manage.

### Technical notes

**Two shell facts decided the design.** `~/.local/bin` is already on PATH on most distributions,
so a symlink is enough and editing shell files is the fallback, not the plan. And bash reads
`.profile` at login but `.bashrc` only for interactive non-login shells — so appending to
`.bashrc` alone leaves `bash -l` (a fresh terminal, a desktop session) without the directory.
A throwaway `$HOME` containing only `.bashrc` demonstrated exactly that, which is why `.profile`
is now the one file created when nothing a login shell reads exists. Files for shells the user
does not use are still never created.

**`export PATH="~/.local/bin:$PATH"` is broken** — a tilde inside double quotes is not expanded,
so it appends a directory that does not exist. It is `$HOME` now, and a test runs the emitted
line through real bash and asserts the directory lands on PATH, because reading it is not enough
to notice.

**`ssh host 'dgxctl ...'` still will not find it**, and that is not fixable from here: a
non-interactive shell reads neither `.profile` nor (effectively) `.bashrc`. Onboarding says so
explicitly and prints the `export PATH=...; dgxctl ...` form, because everyone hits this the
first time they try a remote one-liner.

**A seam bug worth recording.** `render_config` grew an `existing` parameter, preserved user
config correctly, and had five passing unit tests — while `cli.py` kept calling it without that
argument. The feature was complete and inert. Every unit was right; the wiring was not. The fix
added an end-to-end test that invokes the actual command and inspects the file on disk, plus a
test asserting the CLI passes the argument at all. Twice in this session a `str.replace` patch
silently failed to match because `ruff format` had reflowed the anchor — every such patch now
asserts the anchor was found.

## 2026-09-01 — Onboarding for any DGX, and repo cleanup

### User requests
1. Clean up the repo.
2. An installation / onboarding script for a new device — a new DGX may or may not be on a
   tailnet, so that has to be an option.
3. Confirm during onboarding whether things are bound to LAN or loopback, and similar decisions.
4. Offer adding the utility to NVIDIA Sync during onboarding.
5. Anyone should be able to install this on their DGX.

### Completed
- [x] **`dgxctl onboard`** (SDD-122): detects what the machine offers, presents the exposure
      choice with consequences stated, generates a token, asks about control actions, offers
      NVIDIA Sync registration, writes config, installs and starts the user service, and prints
      how to reach it. Interactive by default; every answer has a flag for unattended installs.
- [x] **Environment detection** (SDD-120) and **bind-option planning** (SDD-121) as plain
      functions, so the interesting decision is testable without a terminal.
- [x] **`install.sh` rewritten** (SDD-123): checks the Python version, warns rather than fails
      without Node, ships the systemd unit inside the package, then hands over to onboarding.
      `--no-onboard` and `--yes` for scripted installs. Still no `sudo` anywhere.
- [x] **Repo layout** (SDD-124): process docs moved to `docs/`, MIT `LICENSE` added, README
      rewritten to lead with installation, a markdown link checker added so the move cannot
      silently break references.
- [x] Verified by doing a **clean install from scratch on a real DGX** into a throwaway venv and
      config dir: detection correct, config written, service answered, token enforced, re-run
      backed up the previous config, unknown options rejected with a usable message.
- [x] 237 backend tests, 30 frontend tests.

### Technical notes

**The decision, not the prompting, is the part worth testing.** `bind_options(env)` is a pure
function of the detected environment, so "a machine with no Tailscale is never offered a tailnet
option" and "the tailnet-address option warns that it breaks NVIDIA Sync" are ordinary unit tests
with no TTY involved. The wizard in `cli.py` only renders and prompts.

**Onboarding cannot leave the machine in a state that will not start.** Choosing any non-loopback
bind generates the token in the same step, so it is impossible to finish onboarding and then have
the S3 bind guard refuse to start the service — which would look like the installer had broken it.

**Detection writes nothing.** It runs before the user has agreed to anything, so it must be safe
on a machine whose owner is still deciding; there is a test asserting it creates no directories.

**Two things a stranger's machine will differ on** were the reason detection came first: Tailscale
may be absent, installed-but-logged-out, or connected — and those are three different answers, not
two. Docker may be present but not permitted to this user, which is reported as a fact with the
error rather than as a missing feature.

**A markdown link checker earned its place immediately** — it caught a broken reference introduced
by the docs move within a minute of being written, and then caught itself misreading a documented
`[x](y)` example inside backticks, which is why it now strips code spans before scanning.

### Open follow-ups
- Switching the reference machine to `tailscale serve` once the operator command has been run.
- A short screen recording or asciicast of `dgxctl onboard` would help the README more than prose.

---

## 2026-09-01 — Tailnet access configured and verified

### User requests
1. The tailnet is trusted (team members). Configure the app so it can be used over Tailscale.

### Completed
- [x] Bound the reference machine to `0.0.0.0` — reachable over the tailnet *and* the LAN, with
      loopback preserved so the NVIDIA Sync integration keeps working.
- [x] Verified end to end **from a second machine over Tailscale, with no tunnel**: 401
      unauthenticated, 401 with a wrong token, 200 with the right one, UI live over both the
      tailnet IP and the MagicDNS name.
- [x] Verified the identity allowlist live (S4): a valid token from an unlisted identity gets 403,
      the identity is resolved via `tailscale whois` and logged, loopback bypasses the check.
      Left **off**, because listing only the owner would lock out the teammates who need access.
- [x] `dgxctl expose` (SDD-080): prints the current exposure and the exact command for each
      alternative, including the one that needs root.
- [x] Fixed SDD-114 (below). Verified JupyterLab launch through the API over the tailnet: running
      with `torch 2.9.0+cu130`, `cuda_available True`, and its token link surfaced.

### Technical notes

**Shutdown was silently broken and only ordinary use revealed it.** A live SSE stream held uvicorn
in "waiting for connections to close" until systemd's 90-second stop timeout expired and SIGKILLed
the service — every restart. The obvious fix, setting a flag in lifespan shutdown, does nothing:
uvicorn drains open connections *before* running lifespan shutdown, so the flag is set far too
late. The fix chains onto uvicorn's own signal handler (it installs with `signal.signal`, so ours
runs first and then delegates rather than replacing it). Stop time went from 90 s + SIGKILL to
**359 ms** with result `success`.

**`tailscale serve` remains the better answer and still needs one root command.** It is tailnet-only
(no LAN), gets real TLS from Tailscale's cert domains, and keeps loopback so Sync is unaffected —
but it needs `sudo tailscale set --operator=$USER` once. `0.0.0.0` was chosen because it needs no
root and works immediately; the tradeoff is LAN reachability, which is stated plainly in the README
and in `dgxctl expose`.

**`tailscale serve status` is not a capability probe.** It succeeds for reads even when writing is
denied, so an early version of `dgxctl expose` suppressed the root hint on a machine where `serve`
would in fact have failed. Only attempting a write would tell us, and that is not something to do
as a side effect of printing help — so the requirement is stated unconditionally.

### Open follow-ups
- Switching to `tailscale serve` once the operator command has been run (`dgxctl expose` prints it).
- The dashboard correctly reports **itself** as a `0.0.0.0` finding while bound this way. That is
  honest, not a bug; it disappears under `tailscale serve`.

---

## 2026-09-01 — Launchables, access endpoints, NVIDIA Sync registration

### User requests
1. Mimic the DGX Dashboard features — notably a JupyterLab with GPU access, launched with
   the host virtualenv at `~/jupyterlab/.venv/bin/python`.
2. Get the IP address or launchable link for other services (Hermes agent, OpenClaw, …) from the
   dashboard, instead of going elsewhere to find out how to reach them.

### Completed
- [x] **R10 launchables**: catalog entries gained `kind = container | process`. Process entries
      launch a declared argv detached, capture logs, and are stoppable (SDD-100).
- [x] **R10.4 adoption**: an instance already running — including one started outside dgxctl —
      is adopted, not duplicated (SDD-101).
- [x] **R10.6 JupyterLab entry**, targeting a virtualenv chosen from the ones already discovered
      (SDD-102).
- [x] **R11 access endpoints**: Jupyter's token read from its runtime file and folded into a
      working link, masked until revealed; OpenAI `base_url` for model servers; a copyable SSH
      tunnel command for loopback services viewed remotely; a hint where no credential exists
      (SDD-103, SDD-106).
- [x] **R12 declared services**: `[[service]]` in config, shown while offline, launchable
      (SDD-104). OpenClaw declared on the reference machine.
- [x] **R13 NVIDIA Sync registration**: `dgxctl sync register|list|unregister` (SDD-105).
- [x] Verified live: JupyterLab adopted; launch → serve → refuse-duplicate → log → stop cycle;
      Sync registration with lmstudio preserved and a backup written.
- [x] 208 backend tests, 30 frontend tests, ruff + tsc clean.

### Technical notes

**The DGX Dashboard runs JupyterLab from a host virtualenv, not a container.** The request said
"jupyter-lab container", but the running process is
`~/jupyterlab/.venv/bin/python3 …/jupyter-lab --port 11002`, with torch 2.9.0+cu130 and CUDA
available. Containerising it would have added plumbing and *removed* the direct GPU access that
makes it useful, so process entries were added instead and the containerised Jupyter entry was
dropped rather than shipping two entries that invite picking the wrong one.

**NVIDIA Sync's custom tools are a plain JSON array** at `~/.config/NVIDIA/Sync/config/custom.json`
(`{id, port, name, scriptContent, autoOpen, url, interactive, shown}`). Registration is therefore
automatable, which removes the hand-typed dialog from R7.5. It is explicit-only, backs up first,
preserves entries it did not create, and refuses to write a file it could not parse — it is not
ours to rewrite.

**Five more defects that only real hardware could show** (SDD-107, 110–113 in SDD.md). Two are
worth repeating:

- **Our own hardening broke the product's headline feature.** `PrivateTmp=true` in the systemd
  unit puts the service in a private mount namespace, and `ss -tulnp` then reports every socket
  with *no owning process*. The exposure audit still listed exposed ports but could no longer say
  who was listening — a silent degradation that looks like a data problem, not a config one. The
  unit now documents why the directive is absent, and a test fails if anyone adds it back.
- **Service identity is the port, not the executable.** Matching a running instance by executable
  adopted an unrelated two-week-old `python3` process and refused a valid launch. Full-argv
  matching would have been the obvious fix and would have been *worse*: the real JupyterLab is
  started with different flags than our entry declares, so strict matching would have broken the
  adoption that already worked. The port is the identity; the executable is a secondary hint,
  ignored entirely for shared interpreters. A port held by something else is now reported as a
  conflict rather than as "already running", because those two send you looking in different places.

**A credential in the UI is a deliberate, narrow choice.** Jupyter's token grants code execution,
so the link carries it but renders masked, with reveal and copy beside it. The mask protects
against a shoulder or a screenshot — not against the reader, who already authenticated to the
dashboard. Where a credential cannot be read (Hermes), the card explains how to connect instead of
offering a link that would 401.

### Open follow-ups
- SDD-080 `tailscale serve` integration (still needs the one-time root command).
- Launching a *second* instance of a process entry on a different port is refused. Correct for
  JupyterLab; revisit if a fleet of per-project notebooks is ever wanted.

---

## 2026-08-31 — v1 implemented, verified on real hardware, published

### User requests
1. Implement it overnight, unattended.
2. Test against the real DGX Spark.
3. Keep the codebase generic — it is going to GitHub.
4. Add support for multiple DGX Sparks.
5. Create a private GitHub repo.

### Completed
- [x] **Backend**: config, collector framework, snapshot store, SQLite history, poller, API,
      auth, action runner, launch catalog, `doctor`, CLI. Ten collectors (SDD-001…034, 052).
- [x] **Frontend**: eight-page React SPA on a single SSE data source, generated API types,
      section-level error isolation, staleness badges, one exposure vocabulary (SDD-040…048).
- [x] **Multi-DGX** (R9, SDD-070): store keyed by node id, peer polling, node switcher,
      peer tokens stripped from `/api/config`. Architecture §13.
- [x] **Deploy**: unprivileged `systemd --user` install, idempotent NVIDIA Sync launch script.
- [x] **Live verification on a real DGX Spark** — `scripts/live_verify.py`, 11 sections, all pass.
- [x] **Generic**: no host-specific values in the code; machine notes moved to gitignored
      `LOCAL.md`; fixtures scrubbed of tailnet identities before publication.
- [x] Private repo published: https://github.com/mayankgrd/dgx-control
- [x] 148 backend tests (also green on aarch64), 17 frontend tests, ruff + tsc clean, CI workflow.

### Changes by file
| Area | Change |
|---|---|
| `src/dgxctl/**` | New — 24 modules |
| `web/**` | New — SPA, 8 pages, generated types |
| `tests/**` | New — 148 tests + fixtures captured from real hardware |
| `deploy/**`, `scripts/live_verify.py` | New |
| `catalog/default.toml`, `openapi.json`, `.github/workflows/ci.yml` | New |
| `spec.md` | +R9 (multiple DGX); S6 narrowed to ancestors |
| `architecture.md` | +§13 multi-DGX federation |
| `SDD.md` | Statuses → COMPLETE; +SDD-070…073, 080; live-regression table SDD-090…094 |
| `README.md`, `CLAUDE.md` | Genericised; exposure-option table added |

### Commits
- `docs: spec-driven scaffolding for DGX Control [SDD-000]`
- `feat(backend): collectors, store, poller, auth, catalog and API [SDD-001..SDD-034]`
- `feat(web): React SPA, generated API types, deploy scripts and CI [SDD-040..SDD-053]`
- `feat: multi-DGX federation, live-hardware fixes, publish [SDD-070, SDD-090..094]`

### Technical notes

**The live bar earned its place.** Five defects passed the entire test matrix and were caught only
by deploying to real hardware. They are tabulated in SDD.md as SDD-090…094; the two most instructive:

- `nvmlDeviceGetMemoryInfo` raises `NVMLError_NotSupported` on GB10. There is no separate GPU memory
  pool on unified-memory hardware, so the honest answer is `/proc/meminfo` plus a `memory_source`
  field recording which path was taken. A dashboard that had simply trusted NVML would have shown
  0 GB of GPU memory on a machine with 121 GB.
- An empty `/proc/<pid>/cmdline` is **not** evidence of a kernel thread. A userspace process caught
  between `fork` and `execve` has one too, and the window is wide enough on this hardware to hit
  routinely — it turned up as an intermittent test failure that only reproduced on the Spark. Kernel
  threads are now identified by descent from kthreadd, and the concept is treated as Linux-only.

**Two design rules were changed by contact with reality, not by review:**
- `Collector.depends_on` replaced a guessed startup delay. `services` reads `containers`, and how
  long `containers` takes to first report depends on how many containers are running — so no fixed
  delay is correct. The poller now holds a dependent collector's first run until its sources report.
- Services carry `notable` rather than being filtered out. The first live run buried the real
  services under a dozen ephemeral loopback ports belonging to other programs. Dropping them would
  have been lying about what is listening; de-emphasising them with a "show internal ports" toggle
  keeps the payload honest and the page useful.

**A deployment fact worth knowing before flipping exposure.** `dgxctl` binds one address, and the
options are not equivalent:
- NVIDIA Sync opens `localhost:<port>`, so a **tailnet-address-only bind breaks the Sync
  integration**. This is not obvious until you try it.
- `tailscale serve` is the best answer — tailnet only, loopback preserved, no LAN — but it needs
  one root command (`sudo tailscale set --operator=$USER`) that an agent cannot run.
- `0.0.0.0` needs no root and keeps loopback, but reaches the LAN as well as the tailnet.

The service was therefore left bound to **loopback** on the reference machine, with the three
options documented in the README. Flipping is one config line; it was left as the owner's decision
because the sudo requirement is new information they did not have when choosing tailnet exposure.

**Multi-DGX kept deliberately small.** A peer is just another dgxctl instance behind its own
authenticated API — no second agent, no second protocol. Control actions stay local: acting on a
remote host through an aggregator doubles the blast radius of a compromised token and makes the
action log ambiguous about who did what.

**Genericisation.** No host-specific value appears in `src/`. Fixtures captured from real hardware
were scrubbed of tailnet identities and public keys before commit, while preserving the structural
shapes the parsers must survive (IPv6 brackets, `%zone` suffixes, PID-less root-owned sockets).

### Open follow-ups
- SDD-080 `tailscale serve` integration (needs the one-time root command above).
- SDD-071…073 peer discovery, fleet overview, cross-node history.
- SDD-060 vLLM `/metrics` scraping for queue depth and throughput.
- The API token was printed to a terminal during setup; **rotate it** with
  `dgxctl token --rotate` if that transcript is not private.

---

## 2026-08-30 — Project scaffolding (spec-driven setup)

### User requests
1. Do spec-driven development using the vibe-engineering skill; create CLAUDE.md and the
   appropriate supporting files, from the high-level `spec.md`.
2. Search whether a better-than-vanilla-NVIDIA utility already exists online.

### Completed
- [x] Read the brief and the NVIDIA Sync *Add Custom* dialog screenshot; pulled machine facts from
      the `dgx-spark` skill.
- [x] Resolved four scoping decisions with the owner: **observe + safe control**;
      **FastAPI + React/Vite SPA**; **tailnet-exposed with auth**; **all seven spec areas in phase 1**.
- [x] Surveyed prior art (7 projects) → `prior_art.md`.
- [x] Expanded the brief into a full PRD: `spec.md` (R1–R8, S1–S9, N1–N7), original brief preserved
      in Appendix A with a requirement mapping.
- [x] Wrote `spec_frontend.md` (FE-C1–C10 cross-cutting rules, FE-1…FE-8 pages).
- [x] Wrote `architecture.md` (12 sections with a load-only-what-you-need index, incl. §11 known
      seams).
- [x] Wrote `SDD.md`: 36 numbered entries across 5 phases with dependencies and acceptance criteria.
- [x] Wrote `CLAUDE.md` from the vibe-engineering v2 template, specialised to this box.
- [x] Initialised the repo, `.gitignore`, `README.md`, `develop` branch.

### Changes by file
| File | Change |
|---|---|
| `spec.md` | Rewritten: brief → PRD. Original preserved as Appendix A |
| `spec_frontend.md` | New |
| `architecture.md` | New |
| `SDD.md` | New — SDD-001…053, plus deferred 060/061 |
| `CLAUDE.md` | New |
| `AUDIT.md` | New (this file) |
| `prior_art.md` | New |
| `README.md`, `.gitignore` | New |

### Commits
- `docs: spec-driven scaffolding for DGX Control [SDD-000]`

### Technical notes
- **The owner chose tailnet exposure against the `dgx-spark` skill's loopback-only advice.** Flagged
  at decision time; accepted as a deliberate tradeoff. The mitigation is written into the spec as
  hard requirements rather than left to implementation judgement: fail-closed auth on every route
  including SSE (S1), a startup bind guard that refuses non-loopback without a token (S3), a
  Tailscale identity allowlist (S4), a control gate defaulting off (S5), and a parametrized
  every-route-requires-auth test (SDD-006 AC-1) so a future unauthenticated route fails CI.
- **Prior art finding:** the ecosystem splits into telemetry dashboards (sparkDash, spark-dashboard,
  dgx-spark-status) and model/serving managers (DGX-Model-Manager); nothing spans both. Nothing
  audits listening-socket exposure, and sparkDash — the closest competitor — is *explicitly
  unauthenticated*. Those two gaps are the sharpest differentiators and are exactly what the chosen
  deployment demands. Build, don't adopt; see `prior_art.md` for the rejected-adoption reasoning.
- **`HostIp: ""` in a Docker port binding means `0.0.0.0`, not "unknown".** Reading it as loopback
  would invert the product's central safety signal. Recorded as a seam (architecture §11) with a
  dedicated test (SDD-012 AC-2) and called out in CLAUDE.md.
- **NVML PIDs are host-namespace PIDs**; a containerized process's in-container PID differs, so
  naive matching silently attributes GPU memory to nothing. SDD-011 AC-2 requires a real captured
  fixture from a containerized vLLM server rather than a synthetic one.
- **`EventSource` cannot set an `Authorization` header.** The naive workaround puts the long-lived
  token in the URL, where it lands in logs and browser history. Design uses a single-use 30 s ticket
  instead (architecture §6), with SDD-006 AC-6 asserting the long-lived token is *rejected* as a
  query parameter.
- **Unified memory is the recurring modelling hazard** — it invalidates the usual "GPU memory vs
  system memory" split. It shows up three times: R1.5 (presentation), the SDD-010 AC-2 assertion
  that the reported total never exceeds physical, and the SDD-032 launch budget guard capping summed
  `--gpu-memory-utilization` at 0.70.
- Collectors deliberately never run on the request path — that single decision is what buys N2
  (200 ms warm reads) and N3 (a hung `docker stats` cannot hang the API).
- Nothing is implemented yet. Next session starts at **SDD-001**, then the rest of phase 0 in
  dependency order; no collector work until SDD-002 and SDD-003 are COMPLETE.
