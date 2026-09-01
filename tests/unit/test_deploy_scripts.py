"""Deploy scripts carry hard constraints; assert them rather than trusting review."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).parent.parent.parent / "deploy"


def test_no_script_uses_sudo():
    """sudo is password-protected on many DGX hosts; an agent or service cannot use it."""
    for script in DEPLOY.glob("*.sh"):
        text = script.read_text()
        assert not re.search(r"^\s*sudo\b", text, re.M), f"{script.name} calls sudo"


def test_scripts_are_shellcheck_clean_syntax():
    for script in DEPLOY.glob("*.sh"):
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{script.name}: {proc.stderr}"


def test_scripts_use_strict_mode():
    for script in DEPLOY.glob("*.sh"):
        assert "set -euo pipefail" in script.read_text(), f"{script.name} lacks strict mode"


def test_launch_script_is_idempotent_and_nonblocking():
    text = (DEPLOY / "nvidia-sync-launch.sh").read_text()
    assert "listening" in text, "must check whether the port is already served"
    assert "exit 0" in text, "an already-running service must succeed, not fail"
    assert "nohup" in text or "systemctl --user start" in text, "must not block the caller"
    assert "read " not in text, "must not require input: Sync runs it with no TTY"


def test_service_unit_is_user_scoped_and_unprivileged():
    unit = (DEPLOY / "dgxctl.service").read_text()
    assert "NoNewPrivileges=true" in unit
    assert "User=" not in unit, "a --user unit must not set User="
    assert "%h" in unit, "paths must be relative to the invoking user's home"


def test_readme_documents_every_nvidia_sync_dialog_field():
    readme = (DEPLOY.parent / "README.md").read_text()
    for field in ("Name", "Port", "URL Path", "Launch Script", "Launch in Terminal"):
        assert field in readme, f"README does not document the {field!r} field"


def test_unit_does_not_isolate_mounts():
    """Live regression (SDD-107): PrivateTmp/PrivateMounts put the unit in its own mount
    namespace, and `ss -tulnp` then reports every socket with NO owning process. The
    exposure audit still lists exposed ports but can no longer say who is listening —
    silently gutting the feature the whole product exists for.
    """
    unit = (DEPLOY / "dgxctl.service").read_text()
    # Inspect directives only: the comment explaining the absence names them deliberately.
    directives = [
        ln.strip() for ln in unit.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    for banned in ("PrivateTmp", "PrivateMounts", "ProtectProc"):
        offending = [d for d in directives if d.startswith(banned)]
        assert not offending, (
            f"{offending} hides socket ownership from `ss` — see the comment in the unit file"
        )
    assert "PrivateTmp" in unit, "the reason it is absent must stay documented in the unit"


def test_install_script_hands_over_to_onboarding():
    text = (DEPLOY / "install.sh").read_text()
    assert "onboard" in text, "installing without setting up leaves a stranger stuck"
    assert "--no-onboard" in text, "scripted installs need a way to skip the questions"


def test_install_script_checks_the_python_version():
    text = (DEPLOY / "install.sh").read_text()
    assert "MIN_PY_MINOR" in text
    assert "required" in text, "a too-old Python must fail with an explanation, not a traceback"


def test_install_script_ships_the_unit_inside_the_package():
    """Onboarding installs the service from the package, so a user who deletes the clone
    still has it."""
    text = (DEPLOY / "install.sh").read_text()
    assert "_data/dgxctl.service" in text


def test_install_script_degrades_without_npm():
    text = (DEPLOY / "install.sh").read_text()
    assert "npm not found" in text, "a missing Node must be a warning, not a failure"


def test_install_script_makes_dgxctl_runnable_by_name_even_without_onboarding():
    text = (DEPLOY / "install.sh").read_text()
    assert ".local/bin/dgxctl" in text, "a --no-onboard install must still leave a usable command"
    assert "ln -sfn" in text
    assert "not a symlink" in text, "must not clobber someone else's dgxctl"


def test_uninstall_script_exists_and_is_strict():
    script = DEPLOY / "uninstall.sh"
    assert script.exists(), "a tool anyone can install needs a way to remove it"
    text = script.read_text()
    assert "set -euo pipefail" in text
    assert not re.search(r"^\s*sudo\b", text, re.M), "uninstall must not need root either"


def test_uninstall_keeps_user_data_unless_purge_is_asked_for():
    text = (DEPLOY / "uninstall.sh").read_text()
    assert "--purge" in text
    assert "KEEPING" in text, "removing config and history silently would be hostile"


def test_uninstall_has_a_dry_run():
    assert "--dry-run" in (DEPLOY / "uninstall.sh").read_text()


def test_uninstall_does_not_remove_a_symlink_it_did_not_create():
    text = (DEPLOY / "uninstall.sh").read_text()
    assert "not ours" in text


def test_uninstall_never_removes_containers_or_images():
    """Stopping the service stops the host processes dgxctl launched, because they share its
    cgroup and dgxctl owns what it started. Containers and images are a different matter: the
    uninstaller must not delete them."""
    text = (DEPLOY / "uninstall.sh").read_text()
    for destructive in ("docker rm", "docker stop", "docker rmi", "docker system prune"):
        assert destructive not in text, f"uninstall must not run `{destructive}`"
    assert "Left running" in text, "the user must be told what survived"


def test_unit_relies_on_the_default_kill_mode():
    """dgxctl owns what it launched: stopping or restarting the service stops those processes
    too. Setting KillMode=process would let a restart bypass the Stop button, leaving
    workloads dgxctl believes it manages running behind its back. Processes started outside
    dgxctl are in a different cgroup and are unaffected either way.
    """
    unit = (DEPLOY / "dgxctl.service").read_text()
    directives = [ln.strip() for ln in unit.splitlines() if ln.strip() and not ln.startswith("#")]
    assert not any(d.startswith("KillMode") for d in directives), (
        "KillMode is deliberately unset — see the comment in the unit file"
    )
    assert "KillMode" in unit, "the reason it is unset must stay documented"
