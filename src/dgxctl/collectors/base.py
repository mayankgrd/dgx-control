"""Collector framework. A collector never raises to the poller."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from dgxctl.schemas import Envelope, Status

log = logging.getLogger(__name__)


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class CommandError(RuntimeError):
    pass


def run_cmd(argv: list[str], timeout: float = 10.0) -> str:
    """Run a command. Argument LISTS only — never a shell string (spec S8)."""
    if isinstance(argv, str):
        raise TypeError("run_cmd requires an argument list, not a shell string (spec S8)")
    if not argv:
        raise ValueError("empty command")
    try:
        proc = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=timeout, check=False, shell=False
        )
    except FileNotFoundError as exc:
        raise CommandError(f"{argv[0]}: not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{argv[0]}: timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise CommandError(f"{argv[0]} exited {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


class Collector(ABC):
    """Subclasses implement collect(); the framework handles every failure mode."""

    name: str = "unnamed"
    interval: float = 30.0
    timeout: float = 20.0
    # Sections this collector reads from the store. The poller holds its first run until
    # they exist, so a dependent collector never publishes one empty result and then waits
    # a whole interval to correct it. A guessed startup delay cannot do this reliably: how
    # long `containers` takes to first report depends on how many containers are running.
    depends_on: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._last_good: Any | None = None
        self._unavailable_reason: str | None = None

    @abstractmethod
    async def collect(self) -> Any:
        """Return this section's payload, or raise. Never called if available() is False."""

    async def available(self) -> bool:
        return True

    async def run(self) -> Envelope:
        """Never raises. Converts every outcome into an Envelope."""
        started = time.perf_counter()
        if self._unavailable_reason is not None:
            return Envelope(
                status=Status.unavailable,
                data=None,
                error=self._unavailable_reason,
                collected_at=utcnow_iso(),
                duration_ms=0.0,
            )
        try:
            ok = await self.available()
        except Exception as exc:  # noqa: BLE001
            ok = False
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
        if not ok:
            self._unavailable_reason = self._unavailable_reason or "not available on this host"
            return Envelope(
                status=Status.unavailable,
                error=self._unavailable_reason,
                collected_at=utcnow_iso(),
                duration_ms=0.0,
            )

        try:
            data = await asyncio.wait_for(self.collect(), timeout=self.timeout)
        except TimeoutError:
            return self._failure(f"timed out after {self.timeout}s", started)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("collector %s failed", self.name, exc_info=True)
            return self._failure(f"{type(exc).__name__}: {exc}", started)

        self._last_good = data
        return Envelope(
            status=Status.ok,
            data=data,
            collected_at=utcnow_iso(),
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def _failure(self, message: str, started: float) -> Envelope:
        """On error, keep serving the last good payload — labelled, not blank."""
        return Envelope(
            status=Status.error,
            data=self._last_good,
            error=message,
            collected_at=utcnow_iso(),
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def mark_unavailable(self, reason: str) -> None:
        self._unavailable_reason = reason
