"""Optional privileged visibility (spec R17, architecture §17).

dgxctl runs unprivileged. The one fact that costs on a stock DGX is socket ownership: `ss` only
names the owning process for sockets the caller owns. An operator can opt in by installing a
root-owned, read-only helper with deploy/privileged/enable.sh; this module decides whether that
helper exists, can be trusted, and is permitted — and otherwise stays out of the way.

A sudoers rule pointing at a file a user can modify is a root shell for that user, so trust is
re-checked here rather than assumed from the fact that the file exists.
"""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from dgxctl.collectors.base import CommandError, run_cmd

HELPER_PATH = Path("/usr/local/libexec/dgxctl/dgxctl-helper")
SUBCOMMANDS = ("check", "sockets")

ENABLED = "enabled"
NOT_INSTALLED = "not_installed"
NOT_PERMITTED = "not_permitted"
INSECURE = "insecure"
DISABLED = "disabled"


def enable_script() -> str:
    """Where enable.sh lives on this install, for the instructions we print."""
    for candidate in (
        Path(__file__).parent / "_data" / "privileged" / "enable.sh",
        Path(__file__).parent.parent.parent / "deploy" / "privileged" / "enable.sh",
    ):
        if candidate.exists():
            return str(candidate)
    return "deploy/privileged/enable.sh"


@dataclass(frozen=True)
class HelperStatus:
    state: str
    detail: str
    fix: str | None = None

    @property
    def usable(self) -> bool:
        return self.state == ENABLED


def _writable_by_others(mode: int) -> bool:
    return bool(mode & (stat.S_IWGRP | stat.S_IWOTH))


def inspect(helper: Path = HELPER_PATH, mode: str = "auto", runner=run_cmd) -> HelperStatus:
    enable = enable_script()
    if mode == "off":
        return HelperStatus(DISABLED, 'disabled in config (privileged = "off")')

    if not helper.exists():
        return HelperStatus(
            NOT_INSTALLED,
            "not installed — socket owners belonging to other users are hidden",
            f"sudo {enable}",
        )

    # The file AND the directory holding it: a writable directory lets someone replace a
    # correctly-permissioned file outright.
    for path in (helper, helper.parent):
        st = os.stat(path)
        if st.st_uid != 0 or _writable_by_others(st.st_mode):
            return HelperStatus(
                INSECURE,
                f"{path} is not root-owned and protected (uid={st.st_uid}, "
                f"mode={oct(stat.S_IMODE(st.st_mode))}); refusing to use it",
                f"sudo {enable} --remove && sudo {enable}",
            )

    try:
        answer = runner(["sudo", "-n", str(helper), "check"], timeout=10.0)
    except CommandError as exc:
        return HelperStatus(
            NOT_PERMITTED,
            f"installed but sudo will not run it ({str(exc)[:80]})",
            f"sudo {enable}",
        )
    if (answer or "").strip() != "ok":
        return HelperStatus(
            NOT_PERMITTED, f"unexpected reply from helper: {answer!r:.60}", f"sudo {enable}"
        )
    return HelperStatus(ENABLED, "enabled — socket owners are visible for every user")


class PrivilegedRunner:
    """Runs a fixed helper subcommand if, and only if, the helper is trusted and permitted."""

    def __init__(
        self, mode: str = "auto", helper: Path = HELPER_PATH, runner=run_cmd, ttl: float = 60.0
    ) -> None:
        self.mode = mode
        self.helper = helper
        self._runner = runner
        self._ttl = ttl
        self._cached: tuple[float, HelperStatus] | None = None

    def status(self) -> HelperStatus:
        now = time.monotonic()
        if self._cached is None or now - self._cached[0] > self._ttl:
            self._cached = (now, inspect(self.helper, self.mode, self._runner))
        return self._cached[1]

    def run(self, subcommand: str) -> str | None:
        """Helper output, or None to mean "use the unprivileged path". Never raises on failure."""
        if subcommand not in SUBCOMMANDS:
            raise ValueError(f"unknown helper subcommand {subcommand!r}")
        if not self.status().usable:
            return None
        try:
            return self._runner(["sudo", "-n", str(self.helper), subcommand], timeout=10.0)
        except CommandError:
            self._cached = None  # re-inspect next time; something changed
            return None
