"""Onboarding a new machine (spec R14).

Detection and decision-making live here as plain functions; the terminal interaction lives in
`cli.py`. That split is what lets the interesting part — which exposure options a given machine
should even be offered — be tested without a TTY.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dgxctl.config import Settings, config_dir, load_settings

# --- detection ---------------------------------------------------------------


@dataclass
class Environment:
    """What this machine offers. Every probe is best-effort: a missing tool is a fact to
    report, never an error."""

    python_version: str = ""
    platform: str = ""
    arch: str = ""

    has_nvml: bool = False
    gpu_name: str | None = None
    has_docker: bool = False
    docker_error: str | None = None
    has_ss: bool = False

    has_tailscale: bool = False
    tailscale_state: str | None = None  # Running | NeedsLogin | Stopped | None
    tailnet_ip: str | None = None
    tailnet_name: str | None = None
    tailscale_serving: bool = False

    has_nvidia_sync: bool = False
    nvidia_sync_path: Path | None = None

    has_systemd_user: bool = False
    lingering: bool = False
    service_installed: bool = False

    config_path: Path | None = None
    config_exists: bool = False
    token_exists: bool = False
    current: Settings | None = None

    notes: list[str] = field(default_factory=list)

    @property
    def tailnet_ready(self) -> bool:
        return self.has_tailscale and self.tailscale_state == "Running"


def _run(argv: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout


def detect() -> Environment:
    """Read-only. Writes nothing, creates nothing, and never raises."""
    env = Environment(
        python_version=platform.python_version(),
        platform=platform.system(),
        arch=platform.machine(),
    )

    try:
        import pynvml

        pynvml.nvmlInit()
        env.has_nvml = True
        if pynvml.nvmlDeviceGetCount():
            name = pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(0))
            env.gpu_name = name.decode() if isinstance(name, bytes) else str(name)
    except Exception as exc:  # noqa: BLE001
        env.notes.append(f"NVML unavailable: {str(exc)[:80]}")

    try:
        from dgxctl.docker_client import get_client, get_error

        env.has_docker = get_client() is not None
        env.docker_error = None if env.has_docker else get_error()
    except Exception as exc:  # noqa: BLE001
        env.docker_error = str(exc)[:120]

    env.has_ss = shutil.which("ss") is not None
    env.has_tailscale = shutil.which("tailscale") is not None
    if env.has_tailscale:
        code, out = _run(["tailscale", "status", "--json"])
        if code == 0 and out.strip():
            try:
                status = json.loads(out)
                env.tailscale_state = status.get("BackendState")
                ips = status.get("TailscaleIPs") or []
                env.tailnet_ip = next((i for i in ips if ":" not in i), None)
                env.tailnet_name = (status.get("Self") or {}).get("DNSName", "").rstrip(".") or None
            except ValueError:
                env.tailscale_state = "Unknown"
        code, out = _run(["tailscale", "serve", "status"])
        env.tailscale_serving = code == 0 and "No serve config" not in out

    sync = Path("~/.config/NVIDIA/Sync/config/custom.json").expanduser()
    env.has_nvidia_sync = sync.exists()
    env.nvidia_sync_path = sync

    env.has_systemd_user = shutil.which("systemctl") is not None and _run(
        ["systemctl", "--user", "is-system-running"]
    )[1].strip() not in ("", "offline")
    code, out = _run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"])
    env.lingering = "Linger=yes" in out
    env.service_installed = Path("~/.config/systemd/user/dgxctl.service").expanduser().exists()

    env.config_path = config_dir() / "config.toml"
    env.config_exists = env.config_path.exists()
    try:
        env.current = load_settings(env.config_path)
        env.token_exists = env.current.token_path.exists()
    except Exception as exc:  # noqa: BLE001
        env.notes.append(f"existing config could not be read: {str(exc)[:80]}")
        env.current = None

    return env


# --- the exposure decision ---------------------------------------------------


@dataclass
class BindOption:
    key: str
    label: str
    host: str
    reach: str
    available: bool = True
    needs_root: bool = False
    warning: str | None = None
    post_steps: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None


def bind_options(env: Environment, port: int = 8770) -> list[BindOption]:
    """A pure function of the detected environment — which is what makes it testable.

    A machine with no Tailscale is never offered a tailnet option, and every option states
    what it actually reaches.
    """
    options = [
        BindOption(
            key="loopback",
            label="This machine only (recommended)",
            host="127.0.0.1",
            reach="Reachable only from the DGX itself. Use an SSH tunnel from elsewhere: "
            f"ssh -N -L {port}:127.0.0.1:{port} <this-host>",
        )
    ]

    if env.tailnet_ready:
        where = env.tailnet_name or env.tailnet_ip or "this node"
        options.append(
            BindOption(
                key="tailnet-serve",
                label="Tailnet only, over HTTPS (tightest remote option)",
                host="127.0.0.1",
                reach=f"Reachable from your tailnet at https://{where} — not from the local "
                f"network. Loopback keeps working, so NVIDIA Sync is unaffected.",
                needs_root=True,
                post_steps=[
                    "sudo tailscale set --operator=$USER   # once; needs root",
                    f"tailscale serve --bg {port}",
                ],
            )
        )
    else:
        reason = (
            "Tailscale is not installed on this machine."
            if not env.has_tailscale
            else f"Tailscale is installed but not connected (state: {env.tailscale_state})."
        )
        options.append(
            BindOption(
                key="tailnet-serve",
                label="Tailnet only, over HTTPS",
                host="127.0.0.1",
                reach="Requires Tailscale.",
                available=False,
                unavailable_reason=reason,
            )
        )

    options.append(
        BindOption(
            key="all",
            label="Any network this machine is on",
            host="0.0.0.0",  # noqa: S104 — the point of this option
            reach="Reachable from your tailnet AND your local network. Loopback keeps working. "
            "No root needed.",
            warning="This is broader than a tailnet: anything that can route to this host can "
            "reach it. A token is required and enforced at startup.",
        )
    )

    if env.tailnet_ready and env.tailnet_ip:
        options.append(
            BindOption(
                key="tailnet-address",
                label=f"Tailnet address only ({env.tailnet_ip})",
                host=env.tailnet_ip,
                reach="Reachable from your tailnet only, without root.",
                warning="This excludes loopback, which BREAKS the NVIDIA Sync integration — "
                "Sync opens localhost. Prefer the HTTPS option above, or 'any network'.",
            )
        )

    return options


def option_by_key(env: Environment, key: str, port: int = 8770) -> BindOption | None:
    return next((o for o in bind_options(env, port) if o.key == key), None)


# --- writing the result ------------------------------------------------------

# The only keys onboarding owns. Everything else in the file is the user's and is carried
# across verbatim on a re-run: declared services, peer nodes, intervals, scan roots.
MANAGED_KEYS = ("host", "port", "node_name", "control_enabled", "tailscale_allowlist")


def split_existing(text: str) -> tuple[list[str], str]:
    """Split a config into (unmanaged top-level lines, verbatim table sections).

    TOML requires top-level keys to precede tables, so the two halves are re-emitted in
    that order. Bracket depth is tracked so a multi-line array survives intact.
    """
    lines = text.splitlines()
    tail_start = None
    depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if depth == 0 and stripped.startswith("[") and not stripped.startswith("[]"):
            # A table header, not the start of an array value.
            if "=" not in stripped.split("]")[0]:
                tail_start = i
                break
        depth += line.count("[") - line.count("]")
        depth = max(depth, 0)

    head = lines[:tail_start] if tail_start is not None else lines
    tail = "\n".join(lines[tail_start:]).strip() if tail_start is not None else ""

    kept: list[str] = []
    depth = 0
    keeping = False
    for line in head:
        stripped = line.strip()
        if depth == 0:
            if not stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            keeping = key not in MANAGED_KEYS
        if keeping:
            kept.append(line.rstrip())
        depth += line.count("[") - line.count("]")
        depth = max(depth, 0)
    return kept, tail


TEMPLATE = """# dgxctl configuration — written by `dgxctl onboard` on {stamp}
# Re-run `dgxctl onboard` to change any of this, or edit it by hand and restart:
#   systemctl --user restart dgxctl

host = "{host}"
port = {port}
node_name = "{node_name}"

# Container start/stop, launching, and process kill. Off means the dashboard is read-only.
control_enabled = {control}
{allowlist}
# See config.example.toml in the repo for declared services, peer DGX systems and tuning.
"""


def render_config(
    host: str,
    port: int,
    node_name: str,
    control: bool,
    allowlist: list[str] | None = None,
    existing: str | None = None,
) -> str:
    """Render the managed keys, carrying everything else in `existing` across untouched."""
    allow = ""
    if allowlist:
        rendered = ", ".join(f'"{a}"' for a in allowlist)
        allow = (
            "\n# Only these Tailscale identities may connect, in addition to the token.\n"
            f"tailscale_allowlist = [{rendered}]\n"
        )
    rendered = TEMPLATE.format(
        stamp=datetime.now(UTC).strftime("%Y-%m-%d"),
        host=host,
        port=port,
        node_name=node_name,
        control="true" if control else "false",
        allowlist=allow,
    )
    if not existing:
        return rendered

    kept, tail = split_existing(existing)
    parts = [rendered.rstrip()]
    if kept:
        parts.append("\n# --- your settings, carried across from the previous config ---")
        parts.append("\n".join(kept))
    if tail:
        parts.append("\n" + tail)
    return "\n".join(parts) + "\n"


def write_config(path: Path, content: str) -> Path | None:
    """Returns the backup path when an existing config was replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        if path.read_text() == content:
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup = path.with_suffix(f".toml.bak-{stamp}")
        shutil.copy2(path, backup)
    path.write_text(content)
    # This file can hold a peer instance's API token and decides the bind address, so it is
    # not left to the umask: on a stock Ubuntu (umask 002) it would land group-writable and
    # world-readable.
    path.chmod(0o600)
    return backup


def default_node_name() -> str:
    return platform.node().split(".")[0] or "dgx"


def service_unit_source() -> Path | None:
    for candidate in (
        Path(__file__).parent / "_data" / "dgxctl.service",
        Path(__file__).parent.parent.parent / "deploy" / "dgxctl.service",
    ):
        if candidate.exists():
            return candidate
    return None


def install_service() -> Path | None:
    """Copy the user unit into place. No root: this is a --user service by design."""
    source = service_unit_source()
    if source is None:
        return None
    dest = Path("~/.config/systemd/user/dgxctl.service").expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    _run(["systemctl", "--user", "daemon-reload"], timeout=15)
    return dest


def restart_service() -> bool:
    code, _ = _run(["systemctl", "--user", "enable", "--now", "dgxctl"], timeout=30)
    if code != 0:
        return False
    _run(["systemctl", "--user", "restart", "dgxctl"], timeout=45)
    return True


# --- making `dgxctl` runnable by name ----------------------------------------

RC_MARKER = "# added by dgxctl"
# NOT "~/.local/bin": a tilde inside double quotes is not expanded by the shell, so
# `export PATH="~/.local/bin:$PATH"` silently adds a directory that does not exist.
USER_BIN = "$HOME/.local/bin"


@dataclass
class PathResult:
    link: Path | None = None
    linked: bool = False
    already_on_path: bool = False
    rc_files_updated: list[Path] = field(default_factory=list)
    manual_line: str | None = None
    problem: str | None = None
    noninteractive_note: bool = False


# Build sandboxes that are reclaimed after installation. Linking into one leaves a dangling
# symlink; this was observed for real when `uv` built the package in its cache.
# Deliberately NOT "anything under /tmp": installing to a temp prefix on purpose is valid,
# and pytest's own tmp_path lives there.
EPHEMERAL_MARKERS = (
    "/.cache/uv/builds",
    "/pip-build-env-",
    "/pip-install-",
    "/pip-req-build-",
    "/build-env-",
)


def is_ephemeral(path: Path) -> bool:
    """Is this path inside a build sandbox that will be cleaned up after installation?"""
    resolved = str(path.resolve() if path.exists() else path)
    return any(marker in resolved or marker in str(path) for marker in EPHEMERAL_MARKERS)


def console_script() -> Path:
    """Where the installed `dgxctl` entry point lives.

    `sys.argv[0]` is not it: running `python -m dgxctl.cli` makes argv[0] the module file,
    and symlinking that produces a non-executable link to a .py. The console script sits
    next to the interpreter that is running us.
    """
    candidate = Path(sys.executable).parent / "dgxctl"
    if candidate.exists():
        return candidate
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.name == "dgxctl" and argv0.exists():
        return argv0.resolve()
    return candidate


def _dir_on_path(directory: Path, path_value: str | None = None) -> bool:
    entries = (path_value or os.environ.get("PATH", "")).split(os.pathsep)
    resolved = str(directory)
    return any(e and Path(e).expanduser() == Path(resolved) for e in entries)


# Files a LOGIN shell reads. bash reads .bash_profile/.profile at login and .bashrc only for
# interactive non-login shells, so appending to .bashrc alone leaves `bash -l` without the
# directory — which is what a fresh terminal or a desktop session gets.
LOGIN_FILES = (".profile", ".bash_profile", ".zprofile")
INTERACTIVE_FILES = (".bashrc", ".zshrc")


def _shell_rc_files(home: Path) -> list[Path]:
    """Existing shell files to append to, plus `.profile` if nothing a login shell reads
    exists yet.

    Only existing files are touched — creating a `.zshrc` for someone who does not use zsh
    is a surprise, not a service. `.profile` is the one exception: it is the shell-neutral
    POSIX login file, and without *something* a login shell reads, the PATH entry would only
    apply to interactive shells.
    """
    targets = [home / name for name in (*INTERACTIVE_FILES, *LOGIN_FILES) if (home / name).exists()]
    if not any((home / name).exists() for name in LOGIN_FILES):
        targets.append(home / ".profile")  # created below
    return targets


def ensure_on_path(
    executable: Path, home: Path | None = None, path_value: str | None = None
) -> PathResult:
    """Make `dgxctl` runnable by name.

    Prefers a symlink into ~/.local/bin, which most distributions already put on PATH, over
    editing shell files. Only when that directory is NOT on PATH does it touch an rc file,
    and then only files that already exist, with a marker so a re-run is idempotent.
    """
    result = PathResult()
    home = home or Path.home()
    bindir = home / ".local" / "bin"
    link = bindir / "dgxctl"
    result.link = link

    if not executable.exists():
        result.problem = f"{executable} does not exist"
        return result
    if is_ephemeral(executable):
        # Installing from a build environment (uv/pip build venvs live under a cache that is
        # later reclaimed) would leave a symlink pointing at nothing.
        result.problem = (
            f"{executable} is inside a temporary build directory, which will be removed. "
            f"Run `dgxctl onboard` again from the installed virtualenv."
        )
        return result

    try:
        bindir.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == executable.resolve():
                result.linked = True
            else:
                link.unlink()
                link.symlink_to(executable)
                result.linked = True
        elif link.exists():
            # Something that is not ours. Never clobber it silently.
            result.problem = f"{link} already exists and is not a dgxctl symlink; leaving it alone"
        else:
            link.symlink_to(executable)
            result.linked = True
    except OSError as exc:
        result.problem = f"could not create {link}: {exc}"
        return result

    result.already_on_path = _dir_on_path(bindir, path_value)
    export_line = f'export PATH="{USER_BIN}:$PATH"  {RC_MARKER}'
    result.manual_line = export_line

    if not result.already_on_path:
        for rc in _shell_rc_files(home):
            try:
                text = rc.read_text() if rc.exists() else ""
            except OSError:
                continue
            if RC_MARKER in text or f"{USER_BIN}:$PATH" in text or ".local/bin" in text:
                continue
            with rc.open("a") as fh:
                fh.write(f"\n{export_line}\n")
            result.rc_files_updated.append(rc)

    # `ssh host 'cmd'` sources neither .profile nor (effectively) .bashrc, so ~/.local/bin
    # is absent there even when interactive shells have it. People will hit this the first
    # time they run `ssh dgx 'dgxctl doctor'`.
    result.noninteractive_note = True
    return result


def executable_hint() -> str:
    """Where dgxctl lives, for the closing instructions."""
    return sys.argv[0] if sys.argv and sys.argv[0].endswith("dgxctl") else "dgxctl"
