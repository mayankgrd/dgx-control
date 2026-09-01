"""dgxctl command line."""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import typer

from dgxctl import __version__
from dgxctl.auth import AuthError, generate_token
from dgxctl.config import Settings, config_dir, load_settings

app = typer.Typer(add_completion=False, help="Observability and control for NVIDIA DGX Spark.")


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind address (default 127.0.0.1)"),
    port: int = typer.Option(None, help="Port (default 8770)"),
    log_level: str = typer.Option("info"),
):
    """Run the server. Refuses a non-loopback bind without a token."""
    import uvicorn

    from dgxctl.main import create_app

    settings = load_settings()
    if host:
        settings.host = host
    if port:
        settings.port = port
    try:
        application = create_app(settings)
    except AuthError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    if not settings.is_loopback:
        typer.secho(
            f"Serving on {settings.host}:{settings.port} — reachable beyond this host. "
            f"Token authentication is required for every route.",
            fg=typer.colors.YELLOW,
        )
    uvicorn.run(
        application,
        host=settings.host,
        port=settings.port,
        log_level=log_level,
        # Backstop: even if a client refuses to let go, do not sit in "waiting for
        # connections to close" until systemd loses patience and kills us.
        timeout_graceful_shutdown=10,
    )


@app.command()
def token(
    init: bool = typer.Option(False, "--init", help="Create the token if absent"),
    rotate: bool = typer.Option(False, "--rotate", help="Replace an existing token"),
    show: bool = typer.Option(False, "--show", help="Print the token"),
):
    """Manage the API token (0600 at ~/.config/dgxctl/token)."""
    settings = load_settings()
    path = settings.token_path
    if rotate or init or not path.exists():
        value = generate_token(path, force=rotate)
        typer.echo(f"Token written to {path}")
        if show or rotate or init:
            typer.echo(value)
        return
    if show:
        typer.echo(path.read_text().strip())
    else:
        typer.echo(f"Token exists at {path} (use --show to print, --rotate to replace)")


@app.command()
def onboard(
    bind: str = typer.Option(
        None, help="loopback | tailnet-serve | all | tailnet-address (skips the question)"
    ),
    port: int = typer.Option(None, help="Port to serve on"),
    node_name: str = typer.Option(None, help="Name shown in the header"),
    control: bool = typer.Option(None, "--control/--no-control", help="Allow control actions"),
    sync: bool = typer.Option(None, "--sync/--no-sync", help="Register with NVIDIA Sync"),
    service: bool = typer.Option(True, "--service/--no-service", help="Install the user service"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults; ask nothing"),
):
    """Set this machine up: detect what it offers, choose how it is reachable, start it.

    Interactive by default. Every answer also has a flag, so a fleet install can run unattended:
    `dgxctl onboard --yes --bind loopback --no-control`.
    """
    from dgxctl import onboarding as ob
    from dgxctl.auth import generate_token

    def say(text: str = "", **kw):
        typer.secho(text, **kw)

    def head(text: str):
        typer.secho(f"\n{text}", bold=True)

    say("Inspecting this machine…", fg=typer.colors.BRIGHT_BLACK)
    env = ob.detect()
    interactive = sys.stdin.isatty() and not yes

    head("What this machine offers")

    def line(ok: bool, label: str, detail: str = ""):
        mark = "yes" if ok else "no "
        colour = typer.colors.GREEN if ok else typer.colors.BRIGHT_BLACK
        typer.secho(f"  [{mark}] {label:<22}{detail}", fg=colour)

    line(env.has_nvml, "GPU (NVML)", env.gpu_name or "GPU metrics will be unavailable")
    line(env.has_docker, "Docker", "" if env.has_docker else (env.docker_error or "")[:60])
    line(env.has_ss, "ss (sockets)", "" if env.has_ss else "network page will be unavailable")
    line(
        env.tailnet_ready,
        "Tailscale",
        (env.tailnet_name or env.tailnet_ip or "")
        if env.tailnet_ready
        else ("not installed" if not env.has_tailscale else f"state: {env.tailscale_state}"),
    )
    line(env.has_nvidia_sync, "NVIDIA Sync", "" if env.has_nvidia_sync else "not found")
    line(env.has_systemd_user, "systemd --user", "" if env.has_systemd_user else "cannot autostart")
    if env.has_systemd_user and not env.lingering:
        say(
            "       note: lingering is off, so the service stops when you log out.\n"
            f"       enable it with: loginctl enable-linger {os.environ.get('USER', '$USER')}",
            fg=typer.colors.YELLOW,
        )

    current = env.current or Settings()
    chosen_port = port or (current.port if env.config_exists else 8770)

    # --- exposure ---------------------------------------------------------
    options = ob.bind_options(env, chosen_port)
    available = [o for o in options if o.available]
    chosen: ob.BindOption | None = None

    if bind:
        chosen = ob.option_by_key(env, bind, chosen_port)
        if chosen is None:
            say(
                f"Unknown --bind {bind!r}. Choose from: {', '.join(o.key for o in options)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if not chosen.available:
            say(f"{bind!r} is not available here: {chosen.unavailable_reason}", fg=typer.colors.RED)
            raise typer.Exit(2)
    elif not interactive:
        chosen = available[0]
    else:
        head("Who should be able to reach the dashboard?")
        for i, opt in enumerate(options, 1):
            if not opt.available:
                typer.secho(f"  {i}) {opt.label} — unavailable", fg=typer.colors.BRIGHT_BLACK)
                typer.secho(f"       {opt.unavailable_reason}", fg=typer.colors.BRIGHT_BLACK)
                continue
            typer.secho(f"  {i}) {opt.label}")
            typer.secho(f"       {opt.reach}", fg=typer.colors.BRIGHT_BLACK)
            if opt.needs_root:
                typer.secho(
                    "       needs one root command (shown at the end)", fg=typer.colors.YELLOW
                )
            if opt.warning:
                typer.secho(f"       {opt.warning}", fg=typer.colors.YELLOW)
        while chosen is None:
            raw = typer.prompt("Choice", default="1")
            try:
                candidate = options[int(raw) - 1]
            except (ValueError, IndexError):
                say("Enter one of the numbers above.", fg=typer.colors.RED)
                continue
            if not candidate.available:
                say(f"That one is unavailable: {candidate.unavailable_reason}", fg=typer.colors.RED)
                continue
            chosen = candidate

    # --- token: never leave a bind the service would refuse to start on ----
    token_value = None
    needs_token = chosen.host not in ("127.0.0.1", "::1", "localhost")
    if needs_token or not env.token_exists:
        token_value = generate_token(current.token_path)
        say(
            f"\nAPI token written to {current.token_path} (mode 0600).",
            fg=typer.colors.GREEN if needs_token else typer.colors.BRIGHT_BLACK,
        )

    # --- control gate ------------------------------------------------------
    if control is None:
        control_enabled = current.control_enabled if env.config_exists else False
        if interactive:
            head("Allow control actions?")
            say(
                "  Start/stop containers, launch JupyterLab and model servers, kill a process.",
                fg=typer.colors.BRIGHT_BLACK,
            )
            say(
                "  Off means the dashboard is read-only. You can change this later.",
                fg=typer.colors.BRIGHT_BLACK,
            )
            control_enabled = typer.confirm("Enable control actions", default=control_enabled)
    else:
        control_enabled = control

    name = node_name or (current.node_name if env.config_exists else None) or ob.default_node_name()
    if interactive and not node_name:
        name = typer.prompt("\nName for this machine in the UI", default=name)

    # --- write it ----------------------------------------------------------
    config_file = current.token_path.parent / "config.toml"
    # Carry the user's own settings across: onboarding owns only a handful of keys.
    previous = config_file.read_text() if config_file.exists() else None
    content = ob.render_config(
        chosen.host,
        chosen_port,
        name,
        control_enabled,
        current.tailscale_allowlist,
        existing=previous,
    )
    backup = ob.write_config(config_file, content)
    head("Configuration")
    say(f"  {current.token_path.parent / 'config.toml'}")
    if backup:
        say(f"  previous version backed up to {backup}", fg=typer.colors.BRIGHT_BLACK)
    say(f"  bind={chosen.host}:{chosen_port}  control={'on' if control_enabled else 'off'}")

    # --- NVIDIA Sync -------------------------------------------------------
    do_sync = sync
    if do_sync is None:
        do_sync = False
        if env.has_nvidia_sync and interactive:
            head("Add to NVIDIA Sync?")
            say(
                "  Adds a 'DGX Control' entry to Sync's custom tools so it opens from there.",
                fg=typer.colors.BRIGHT_BLACK,
            )
            say(
                "  Your existing entries are preserved and the file is backed up first.",
                fg=typer.colors.BRIGHT_BLACK,
            )
            do_sync = typer.confirm("Register with NVIDIA Sync", default=True)
    if do_sync:
        if not env.has_nvidia_sync:
            say("NVIDIA Sync config not found; skipping registration.", fg=typer.colors.YELLOW)
        else:
            from dgxctl.nvidia_sync import SyncError, register

            try:
                entry, sync_backup = register(name="DGX Control", port=chosen_port)
                say(f"  registered with NVIDIA Sync → {entry['url']}", fg=typer.colors.GREEN)
                say(f"  Sync config backed up to {sync_backup}", fg=typer.colors.BRIGHT_BLACK)
            except SyncError as exc:
                say(f"  NVIDIA Sync registration skipped: {exc}", fg=typer.colors.YELLOW)

    # --- make `dgxctl` runnable by name -------------------------------------
    head("Command")
    exe = ob.console_script()
    path_result = ob.ensure_on_path(exe)
    if path_result.linked:
        say(f"  {path_result.link} -> {exe}", fg=typer.colors.GREEN)
    if path_result.problem:
        say(f"  {path_result.problem}", fg=typer.colors.YELLOW)
        say(f"  run it directly with: {exe}", fg=typer.colors.BRIGHT_BLACK)
    if path_result.rc_files_updated:
        for rc in path_result.rc_files_updated:
            say(f"  added ~/.local/bin to PATH in {rc}", fg=typer.colors.GREEN)
        say(
            "  open a new shell (or `source` that file) before using `dgxctl`.",
            fg=typer.colors.YELLOW,
        )
    elif path_result.already_on_path:
        say("  `dgxctl` is on your PATH", fg=typer.colors.BRIGHT_BLACK)

    # --- service -----------------------------------------------------------
    if service and env.has_systemd_user:
        head("Service")
        unit = ob.install_service()
        if unit is None:
            say("  unit file not found in this install; skipping", fg=typer.colors.YELLOW)
        elif ob.restart_service():
            say(f"  installed and started ({unit})", fg=typer.colors.GREEN)
        else:
            say(
                "  could not start the service; check: systemctl --user status dgxctl",
                fg=typer.colors.YELLOW,
            )

    # --- verify and hand over ---------------------------------------------
    head("Done")
    if chosen.post_steps:
        say("  Two commands left to finish this option:", fg=typer.colors.YELLOW)
        for step in chosen.post_steps:
            say(f"    {step}", fg=typer.colors.YELLOW)
    urls = []
    if chosen.host in ("127.0.0.1", "::1"):
        urls.append(f"http://127.0.0.1:{chosen_port}/  (from this machine)")
        urls.append(
            f"ssh -N -L {chosen_port}:127.0.0.1:{chosen_port} <this-host>   (from elsewhere)"
        )
    else:
        urls.append(f"http://127.0.0.1:{chosen_port}/  (from this machine)")
        if env.tailnet_name:
            urls.append(f"http://{env.tailnet_name}:{chosen_port}/  (from your tailnet)")
        elif env.tailnet_ip:
            urls.append(f"http://{env.tailnet_ip}:{chosen_port}/  (from your tailnet)")
    for u in urls:
        say(f"  {u}")
    if token_value or env.token_exists:
        say("\n  The browser will ask for the API token once. Get it with:")
        say("    dgxctl token --show")
    say("\n  dgxctl doctor    check every data source")
    say("  dgxctl expose    see or change who can reach this")
    if path_result.noninteractive_note:
        say(
            "\n  Note: `ssh <host> 'dgxctl ...'` runs a non-interactive shell, which does not\n"
            "  read your shell files, so ~/.local/bin is absent there. For remote one-liners:\n"
            "    ssh <host> 'export PATH=\"$HOME/.local/bin:$PATH\"; dgxctl doctor'",
            fg=typer.colors.BRIGHT_BLACK,
        )


@app.command()
def expose():
    """Explain how this instance is reachable, and how to change it.

    dgxctl binds ONE address, and the options are not equivalent. This prints the current
    state and the exact command for each alternative, including the one that needs root.
    """
    from dgxctl.collectors.base import have, run_cmd

    settings = load_settings()
    token_ok = settings.token_path.exists()

    tailnet_ip = tailnet_name = None
    if have("tailscale"):
        try:
            tailnet_ip = run_cmd(["tailscale", "ip", "-4"], timeout=5).strip().splitlines()[0]
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            import json as _json

            status = _json.loads(run_cmd(["tailscale", "status", "--json"], timeout=5))
            tailnet_name = (status.get("Self") or {}).get("DNSName", "").rstrip(".") or None
        except Exception:  # noqa: BLE001, S110
            pass

    bold = typer.style
    typer.echo(bold("Current", bold=True))
    typer.echo(f"  bind            {settings.host}:{settings.port}")
    typer.echo(f"  token           {'configured' if token_ok else 'NOT configured'}")
    allow = settings.tailscale_allowlist or "off (any tailnet peer holding the token)"
    typer.echo(f"  identity filter {allow}")

    if settings.is_loopback:
        typer.echo("  reachable from  this host only")
        typer.echo(f"  remotely via    ssh -N -L {settings.port}:127.0.0.1:{settings.port} <host>")
    elif settings.host in ("0.0.0.0", "::"):  # noqa: S104
        typer.echo("  reachable from  the tailnet AND the local network")
        if tailnet_ip:
            typer.echo(f"                  http://{tailnet_ip}:{settings.port}/")
        if tailnet_name:
            typer.echo(f"                  http://{tailnet_name}:{settings.port}/")
    else:
        typer.echo(f"  reachable from  whatever can route to {settings.host}")
        typer.secho(
            "  note            NVIDIA Sync opens localhost, so a single-address bind that "
            "excludes loopback breaks it.",
            fg=typer.colors.YELLOW,
        )

    typer.echo("")
    typer.echo(bold("Options", bold=True))
    cfg = config_dir() / "config.toml"
    typer.echo(f'  loopback only     set host = "127.0.0.1" in {cfg}')
    typer.echo(f'  tailnet + LAN     set host = "0.0.0.0" in {cfg}   (no root needed)')

    # `tailscale serve status` succeeds for READS even when writing is denied, so it is no
    # evidence that `serve` will work. Only attempting a write would tell us, and that is not
    # a thing to do as a side effect of printing help — so state the requirement plainly.
    typer.echo('  tailnet only      keep host = "127.0.0.1", then:')
    typer.secho(
        "                      sudo tailscale set --operator=$USER   # once; needs root",
        fg=typer.colors.YELLOW,
    )
    typer.echo(f"                      tailscale serve --bg {settings.port}")
    if tailnet_name:
        typer.echo(f"                    → https://{tailnet_name}/  (TLS, tailnet only, no LAN)")
    typer.echo("                    This is the tightest option: loopback keeps working, so")
    typer.echo("                    NVIDIA Sync is unaffected, and the LAN is not exposed.")

    if not settings.is_loopback and not token_ok:
        typer.secho(
            "\nThis instance is bound beyond loopback with no token. It will refuse to start. "
            "Run `dgxctl token --init`.",
            fg=typer.colors.RED,
        )
    typer.echo("")
    typer.echo("Restart after any change:  systemctl --user restart dgxctl")


@app.command()
def doctor():
    """Check every data source and report what will and will not work here."""
    from dgxctl.doctor import run_doctor

    settings = load_settings()
    report = asyncio.run(run_doctor(settings))
    colors = {
        "ok": typer.colors.GREEN,
        "degraded": typer.colors.YELLOW,
        "unavailable": typer.colors.BRIGHT_BLACK,
        "error": typer.colors.RED,
    }
    for check in report.checks:
        status = check.status.value
        typer.secho(f"{status.upper():<12} {check.name:<12} {check.detail}", fg=colors[status])
        if check.fix:
            typer.secho(f"{'':<12} {'':<12} fix: {check.fix}", fg=typer.colors.BRIGHT_BLACK)
    if not report.ok:
        typer.secho("\nOne or more checks failed.", fg=typer.colors.RED)
        sys.exit(1)


sync_app = typer.Typer(help="Register dgxctl (or any service) with NVIDIA Sync.")
app.add_typer(sync_app, name="sync")


@sync_app.command("list")
def sync_list():
    """Show NVIDIA Sync's registered custom tools."""
    from dgxctl.nvidia_sync import SyncError, config_path, read_entries

    try:
        entries = read_entries()
    except SyncError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{config_path()}")
    if not entries:
        typer.echo("  (no custom tools registered)")
    for e in entries:
        typer.echo(f"  {e.get('name', '?'):<20} port {e.get('port', '?'):<8} {e.get('url', '')}")


@sync_app.command("register")
def sync_register(
    name: str = typer.Option(None, help="Tool name shown in Sync (default: DGX Control)"),
    port: int = typer.Option(None, help="Port (default: this instance's configured port)"),
    url_path: str = typer.Option("/", "--url-path", help="Path Sync opens"),
    no_auto_open: bool = typer.Option(False, "--no-auto-open"),
):
    """Add dgxctl to NVIDIA Sync's custom tools, so it appears in Sync's own UI."""
    from dgxctl.nvidia_sync import SyncError, register

    settings = load_settings()
    try:
        entry, backup = register(
            name=name or "DGX Control",
            port=port or settings.port,
            url_path=url_path,
            auto_open=not no_auto_open,
        )
    except SyncError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"Registered {entry['name']!r} → {entry['url']}", fg=typer.colors.GREEN)
    typer.echo(f"Previous config backed up to {backup}")
    typer.echo("Restart NVIDIA Sync (or reconnect) for it to appear.")


@sync_app.command("unregister")
def sync_unregister(name: str = typer.Argument("DGX Control")):
    """Remove a tool from NVIDIA Sync's custom tools."""
    from dgxctl.nvidia_sync import SyncError, unregister

    try:
        removed, backup = unregister(name)
    except SyncError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if not removed:
        typer.secho(f"No entry named {name!r}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    typer.secho(f"Removed {name!r} (backup: {backup})", fg=typer.colors.GREEN)


@app.command()
def schema(
    out: str = typer.Option("openapi.json", help="Where to write the OpenAPI document"),
):
    """Dump the OpenAPI schema. The frontend's TypeScript types are generated from this."""
    import json

    from dgxctl.config import Settings
    from dgxctl.main import create_app

    application = create_app(Settings(host="127.0.0.1"), start_poller=False)
    pathlib.Path(out).write_text(json.dumps(application.openapi(), indent=2) + "\n")
    typer.echo(f"Wrote {out}")


@app.command()
def version():
    typer.echo(__version__)


if __name__ == "__main__":
    app()
