"""Onboarding a new machine (SDD-120..123).

The interesting part is which exposure options a given machine should even be offered, so
that decision is a pure function and gets tested without a terminal.
"""

from __future__ import annotations

from pathlib import Path

from dgxctl import onboarding as ob
from dgxctl.config import load_settings


def bare() -> ob.Environment:
    """A machine with nothing: no GPU, no Docker, no Tailscale, no Sync."""
    return ob.Environment(python_version="3.12.0", platform="Linux", arch="aarch64")


def connected(**kw) -> ob.Environment:
    env = bare()
    env.has_tailscale = True
    env.tailscale_state = "Running"
    env.tailnet_ip = "100.64.0.1"
    env.tailnet_name = "dgx-01.example.ts.net"
    for k, v in kw.items():
        setattr(env, k, v)
    return env


# --- SDD-120 detection -------------------------------------------------------


def test_detect_never_raises_and_populates_every_field(monkeypatch, tmp_path):
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(tmp_path / "cfg"))
    env = ob.detect()
    assert env.python_version and env.platform and env.arch
    assert isinstance(env.has_docker, bool)
    assert isinstance(env.has_tailscale, bool)
    assert isinstance(env.notes, list)


def test_detect_writes_nothing(monkeypatch, tmp_path):
    """Detection must be safe to run on someone else's machine before they agree to anything."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(cfg))
    ob.detect()
    assert not cfg.exists(), "detection created a directory"


def test_detect_finds_an_existing_config(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text('host = "0.0.0.0"\nport = 9999\n')
    (cfg / "token").write_text("x")
    (cfg / "token").chmod(0o600)
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(cfg))
    env = ob.detect()
    assert env.config_exists and env.token_exists
    assert env.current.port == 9999


# --- SDD-121 the exposure decision -------------------------------------------


def test_loopback_is_always_offered_first():
    for env in (bare(), connected()):
        options = ob.bind_options(env)
        assert options[0].key == "loopback"
        assert options[0].available
        assert options[0].host == "127.0.0.1"


def test_a_machine_without_tailscale_is_not_offered_a_tailnet_option():
    options = {o.key: o for o in ob.bind_options(bare())}
    assert options["tailnet-serve"].available is False
    assert "not installed" in options["tailnet-serve"].unavailable_reason
    assert "tailnet-address" not in options, "no tailnet address exists to offer"


def test_tailscale_installed_but_logged_out_is_distinct_from_absent():
    env = bare()
    env.has_tailscale = True
    env.tailscale_state = "NeedsLogin"
    opt = {o.key: o for o in ob.bind_options(env)}["tailnet-serve"]
    assert opt.available is False
    assert "NeedsLogin" in opt.unavailable_reason


def test_serve_option_declares_its_root_requirement_and_steps():
    opt = {o.key: o for o in ob.bind_options(connected())}["tailnet-serve"]
    assert opt.available and opt.needs_root
    assert any("sudo tailscale set --operator" in s for s in opt.post_steps)
    assert opt.host == "127.0.0.1", "serve fronts a loopback bind, so Sync keeps working"


def test_all_interfaces_states_that_it_reaches_the_lan():
    opt = {o.key: o for o in ob.bind_options(connected())}["all"]
    assert opt.host == "0.0.0.0"
    assert "local network" in opt.reach
    assert opt.warning and "route to this host" in opt.warning
    assert not opt.needs_root


def test_tailnet_address_option_warns_that_it_breaks_nvidia_sync():
    opt = {o.key: o for o in ob.bind_options(connected())}["tailnet-address"]
    assert opt.host == "100.64.0.1"
    assert "BREAKS" in opt.warning and "Sync" in opt.warning


def test_every_offered_option_explains_what_it_reaches():
    for env in (bare(), connected()):
        for opt in ob.bind_options(env):
            assert opt.reach, f"{opt.key} offers no explanation"
            assert opt.label


def test_option_lookup_by_key():
    assert ob.option_by_key(connected(), "all").host == "0.0.0.0"
    assert ob.option_by_key(bare(), "nonsense") is None


# --- SDD-122 writing the result ----------------------------------------------


def test_rendered_config_round_trips_through_load_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(tmp_path))
    content = ob.render_config("0.0.0.0", 8771, "lab-dgx", control=True)
    path = tmp_path / "config.toml"
    ob.write_config(path, content)
    settings = load_settings(path)
    assert settings.host == "0.0.0.0"
    assert settings.port == 8771
    assert settings.node_name == "lab-dgx"
    assert settings.control_enabled is True


def test_control_is_off_in_a_default_render():
    assert "control_enabled = false" in ob.render_config("127.0.0.1", 8770, "d", control=False)


def test_allowlist_is_only_written_when_set(tmp_path):
    assert "tailscale_allowlist" not in ob.render_config("127.0.0.1", 8770, "d", False)
    with_allow = ob.render_config("127.0.0.1", 8770, "d", False, ["a@example.com"])
    assert 'tailscale_allowlist = ["a@example.com"]' in with_allow
    settings = load_settings(_write(tmp_path, with_allow))
    assert settings.tailscale_allowlist == ["a@example.com"]


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(content)
    return p


def test_existing_config_is_backed_up_before_replacement(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('host = "1.2.3.4"\n')
    backup = ob.write_config(path, ob.render_config("127.0.0.1", 8770, "d", False))
    assert backup is not None and backup.exists()
    assert backup.read_text() == 'host = "1.2.3.4"\n'
    assert "127.0.0.1" in path.read_text()


def test_rewriting_identical_content_makes_no_backup(tmp_path):
    path = tmp_path / "config.toml"
    content = ob.render_config("127.0.0.1", 8770, "d", False)
    ob.write_config(path, content)
    assert ob.write_config(path, content) is None, "an unchanged re-run should not churn backups"


def test_default_node_name_is_a_bare_hostname():
    name = ob.default_node_name()
    assert name and "." not in name


# --- SDD-125: making `dgxctl` runnable by name -------------------------------


def _fake_exe(tmp_path):
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    exe = venv_bin / "dgxctl"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_symlinks_into_user_bin(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    exe = _fake_exe(tmp_path)
    result = ob.ensure_on_path(exe, home=home, path_value=str(home / ".local" / "bin"))
    assert result.linked
    link = home / ".local" / "bin" / "dgxctl"
    assert link.is_symlink() and link.resolve() == exe.resolve()
    assert result.already_on_path
    assert result.rc_files_updated == [], "no shell file needs touching when it is on PATH"


def test_is_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    exe = _fake_exe(tmp_path)
    on_path = str(home / ".local" / "bin")
    ob.ensure_on_path(exe, home=home, path_value=on_path)
    second = ob.ensure_on_path(exe, home=home, path_value=on_path)
    assert second.linked and second.problem is None


def test_repoints_a_stale_symlink(tmp_path):
    """Re-installing to a different venv must not leave the old binary on PATH."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    old = tmp_path / "old-dgxctl"
    old.write_text("#!/bin/sh\n")
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "dgxctl").symlink_to(old)

    exe = _fake_exe(tmp_path)
    result = ob.ensure_on_path(exe, home=home, path_value=str(bindir))
    assert result.linked
    assert (bindir / "dgxctl").resolve() == exe.resolve()


def test_never_clobbers_a_real_file(tmp_path):
    """Someone else's dgxctl — a distro package, a hand-written wrapper — is not ours to
    delete."""
    home = tmp_path / "home"
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    theirs = bindir / "dgxctl"
    theirs.write_text("#!/bin/sh\necho not ours\n")

    result = ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value=str(bindir))
    assert not result.linked
    assert "not a dgxctl symlink" in result.problem
    assert theirs.read_text() == "#!/bin/sh\necho not ours\n"


def test_updates_shell_files_only_when_the_dir_is_not_on_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bashrc").write_text("# my bashrc\n")
    (home / ".zshrc").write_text("# my zshrc\n")
    exe = _fake_exe(tmp_path)

    result = ob.ensure_on_path(exe, home=home, path_value="/usr/bin:/bin")
    names = {p.name for p in result.rc_files_updated}
    assert {".bashrc", ".zshrc"} <= names
    # No login file existed, so .profile is created — otherwise `bash -l` never sees it.
    assert ".profile" in names
    for rc in result.rc_files_updated:
        assert ob.RC_MARKER in rc.read_text()


def test_does_not_create_shell_files_for_shells_you_do_not_use(tmp_path):
    """Creating a .zshrc for someone who does not use zsh is a surprise, not a service.

    `.profile` is the deliberate exception — it is shell-neutral, and without something a
    login shell reads the PATH entry would apply only to interactive shells.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bashrc").write_text("# only bash here\n")
    ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value="/usr/bin")
    assert not (home / ".zshrc").exists()
    assert not (home / ".bash_profile").exists()


def test_does_not_append_twice(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bashrc").write_text("# my bashrc\n")
    exe = _fake_exe(tmp_path)
    ob.ensure_on_path(exe, home=home, path_value="/usr/bin")
    ob.ensure_on_path(exe, home=home, path_value="/usr/bin")
    assert (home / ".bashrc").read_text().count(ob.RC_MARKER) == 1


def test_leaves_an_existing_local_bin_export_alone(tmp_path):
    """Ubuntu's stock .profile already adds ~/.local/bin. Adding a second line is noise."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".profile").write_text(
        'if [ -d "$HOME/.local/bin" ]; then PATH="$HOME/.local/bin:$PATH"; fi\n'
    )
    result = ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value="/usr/bin")
    assert result.rc_files_updated == []


def test_reports_a_missing_executable_rather_than_linking_to_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = ob.ensure_on_path(tmp_path / "nope" / "dgxctl", home=home)
    assert not result.linked and "does not exist" in result.problem


def test_the_exported_path_line_actually_expands(tmp_path):
    """`export PATH="~/.local/bin:$PATH"` is broken: a tilde inside double quotes is not
    expanded, so it adds a directory that does not exist. Prove the emitted line works."""
    import subprocess

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bashrc").write_text("")
    result = ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value="/usr/bin")
    line = result.manual_line
    assert "~" not in line, f"a tilde will not expand inside quotes: {line}"

    # Run the emitted line for real. Each statement on its own line, because the line ends
    # in a comment that would otherwise swallow anything appended after a semicolon.
    script = "\n".join([f'export HOME="{home}"', line, 'echo "$PATH"'])
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    entries = [Path(p).resolve() for p in proc.stdout.strip().split(":") if p]
    assert (home / ".local" / "bin").resolve() in entries, proc.stdout


def test_console_script_is_found_next_to_the_interpreter(tmp_path, monkeypatch):
    """Running `python -m dgxctl.cli` makes argv[0] a .py file; symlinking that would
    produce a non-executable link."""
    import sys as _sys

    fake_bin = tmp_path / "venv" / "bin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "python").write_text("")
    script = fake_bin / "dgxctl"
    script.write_text("#!/bin/sh\n")

    monkeypatch.setattr(_sys, "executable", str(fake_bin / "python"))
    monkeypatch.setattr(_sys, "argv", ["/somewhere/src/dgxctl/cli.py", "onboard"])
    assert ob.console_script() == script


def test_console_script_falls_back_to_argv_when_named_dgxctl(tmp_path, monkeypatch):
    import sys as _sys

    elsewhere = tmp_path / "bin"
    elsewhere.mkdir()
    script = elsewhere / "dgxctl"
    script.write_text("#!/bin/sh\n")
    monkeypatch.setattr(_sys, "executable", str(tmp_path / "no-such" / "python"))
    monkeypatch.setattr(_sys, "argv", [str(script), "onboard"])
    assert ob.console_script() == script.resolve()


def test_login_shells_get_the_path_too(tmp_path):
    """bash reads .profile at login and .bashrc only for interactive non-login shells.
    Appending to .bashrc alone leaves `bash -l` — a fresh terminal, a desktop session —
    without the directory."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bashrc").write_text("# only a bashrc here\n")
    result = ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value="/usr/bin")

    names = {p.name for p in result.rc_files_updated}
    assert ".bashrc" in names
    assert ".profile" in names, "a login shell would otherwise never see the directory"
    assert ob.RC_MARKER in (home / ".profile").read_text()


def test_existing_login_file_is_used_rather_than_creating_profile(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".bash_profile").write_text("# login file\n")
    result = ob.ensure_on_path(_fake_exe(tmp_path), home=home, path_value="/usr/bin")
    assert ".bash_profile" in {p.name for p in result.rc_files_updated}
    assert not (home / ".profile").exists(), "do not add a second login file"


def test_no_shell_files_are_created_when_the_dir_is_already_on_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = ob.ensure_on_path(
        _fake_exe(tmp_path), home=home, path_value=str(home / ".local" / "bin")
    )
    assert result.rc_files_updated == []
    assert not (home / ".profile").exists()


# --- a re-run must not eat the user's own settings ---------------------------

EXISTING = """# my config
host = "127.0.0.1"
port = 8770
node_name = "old"
control_enabled = false
disk_warn_percent = 70
sized_roots = [
  "~/.cache/huggingface",
  "~/projects",
]

[[service]]
id = "openclaw"
name = "OpenClaw"
port = 8123
launch = ["ollama", "launch", "openclaw"]

[[node]]
id = "spark-2"
url = "http://spark-2:8770"

[intervals]
gpu = 5.0
"""


def test_rerun_preserves_declared_services_and_peers(tmp_path, monkeypatch):
    """Live regression: re-running onboarding silently dropped a [[service]] block."""
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(tmp_path))
    out = ob.render_config("0.0.0.0", 9999, "new", control=True, existing=EXISTING)
    assert "openclaw" in out
    assert "spark-2" in out
    assert "[intervals]" in out

    path = tmp_path / "config.toml"
    path.write_text(out)
    settings = load_settings(path)
    assert settings.host == "0.0.0.0" and settings.port == 9999
    assert settings.node_name == "new" and settings.control_enabled is True
    assert [s.id for s in settings.services] == ["openclaw"]
    assert [n.id for n in settings.nodes] == ["spark-2"]
    assert settings.intervals.gpu == 5.0


def test_rerun_preserves_unmanaged_top_level_keys(tmp_path):
    out = ob.render_config("127.0.0.1", 8770, "n", control=False, existing=EXISTING)
    path = tmp_path / "config.toml"
    path.write_text(out)
    settings = load_settings(path)
    assert settings.disk_warn_percent == 70, "an unmanaged scalar was lost"
    assert "~/projects" in settings.sized_roots, "a multi-line array was mangled"


def test_rerun_does_not_duplicate_managed_keys(tmp_path):
    out = ob.render_config("0.0.0.0", 9999, "new", control=True, existing=EXISTING)
    # Count assignments BEFORE the first table header only. Keys inside [[service]] are
    # also unindented, so "unindented" alone is not what "top-level" means in TOML.
    lines = out.splitlines()
    first_table = next((i for i, ln in enumerate(lines) if ln.strip().startswith("[")), len(lines))
    keys = [
        ln.split("=", 1)[0].strip()
        for ln in lines[:first_table]
        if "=" in ln and not ln.strip().startswith("#")
    ]
    for key in ("host", "port", "node_name", "control_enabled"):
        assert keys.count(key) == 1, f"{key} appears {keys.count(key)} times: {keys}"
    assert '"old"' not in out, "the previous value must be replaced, not kept alongside"
    load_settings(_write(tmp_path, out))


def test_render_without_existing_is_unchanged(tmp_path):
    out = ob.render_config("127.0.0.1", 8770, "n", control=False)
    assert "carried across" not in out
    load_settings(_write(tmp_path, out))


def test_split_existing_separates_head_from_tables():
    kept, tail = ob.split_existing(EXISTING)
    joined = "\n".join(kept)
    assert "disk_warn_percent" in joined
    assert "host" not in joined and "control_enabled" not in joined
    assert tail.startswith("[[service]]")


def test_the_cli_actually_passes_the_existing_config_through(tmp_path, monkeypatch):
    """Regression on the wiring, not the logic: `render_config` grew an `existing`
    parameter and preserved everything correctly, while the CLI kept calling it without
    that argument — so the feature was complete and inert."""
    import inspect

    from dgxctl import cli

    source = inspect.getsource(cli.onboard)
    assert "existing=" in source, "onboard does not pass the previous config through"
    assert "read_text()" in source, "onboard does not read the previous config"


def test_onboard_end_to_end_preserves_a_declared_service(tmp_path, monkeypatch):
    """The real path: run the command and check the file on disk."""
    from typer.testing import CliRunner

    from dgxctl.cli import app

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text(
        'host = "127.0.0.1"\nport = 8770\n\n[[service]]\nid = "openclaw"\nport = 8123\n'
    )
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("DGXCTL_STATE_DIR", str(tmp_path / "state"))

    result = CliRunner().invoke(
        app,
        ["onboard", "--yes", "--bind", "loopback", "--no-control", "--no-sync", "--no-service"],
    )
    assert result.exit_code == 0, result.output
    written = (cfg / "config.toml").read_text()
    assert "openclaw" in written, "onboarding ate a declared service"
    assert load_settings(cfg / "config.toml").services[0].id == "openclaw"


def test_refuses_to_link_into_a_build_sandbox(tmp_path):
    """Live regression: running onboarding from a `uv` build venv pointed the user's
    ~/.local/bin/dgxctl at a cache directory that was later reclaimed, leaving the command
    broken. A build sandbox is not a durable install location."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    build = tmp_path / ".cache" / "uv" / "builds-v0" / ".tmpXYZ" / "bin"
    build.mkdir(parents=True)
    exe = build / "dgxctl"
    exe.write_text("#!/bin/sh\n")

    assert ob.is_ephemeral(exe)
    result = ob.ensure_on_path(exe, home=home, path_value=str(home / ".local" / "bin"))
    assert not result.linked
    assert "temporary build directory" in result.problem
    assert not (home / ".local" / "bin" / "dgxctl").exists(), "a dangling link was created"


def test_a_normal_venv_is_not_treated_as_ephemeral(tmp_path):
    exe = tmp_path / ".local" / "share" / "dgxctl" / "venv" / "bin" / "dgxctl"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert not ob.is_ephemeral(exe)
