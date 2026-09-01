"""Fail-closed authentication. See spec S1-S5 and architecture.md section 7."""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import stat
import time
from pathlib import Path

from dgxctl.collectors.base import have, run_cmd
from dgxctl.config import Settings

log = logging.getLogger(__name__)

TICKET_TTL = 30.0


class AuthError(RuntimeError):
    pass


def generate_token(path: Path, force: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path.read_text().strip()
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def read_token(path: Path) -> str | None:
    """A token file readable by others is refused, not used (spec S2)."""
    if not path.exists():
        return None
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise AuthError(
            f"{path} has permissions {oct(stat.S_IMODE(mode))}; must be 0600. "
            f"Fix with: chmod 600 {path}"
        )
    token = path.read_text().strip()
    return token or None


def check_bind_guard(settings: Settings) -> None:
    """Startup fails closed on a non-loopback bind with no token (spec S3)."""
    if settings.is_loopback:
        return
    token = read_token(settings.token_path)
    if not token:
        raise AuthError(
            f"Refusing to start: host is {settings.host!r} (not loopback) and no token "
            f"exists at {settings.token_path}.\n"
            f"This network may be shared with machines you do not control.\n"
            f'Run `dgxctl token --init` first, or set host = "127.0.0.1".'
        )


class TicketStore:
    """Single-use, short-lived tickets so EventSource can authenticate without a header."""

    def __init__(self, ttl: float = TICKET_TTL) -> None:
        self.ttl = ttl
        self._tickets: dict[str, float] = {}

    def issue(self) -> str:
        self._sweep()
        t = secrets.token_urlsafe(24)
        self._tickets[t] = time.monotonic() + self.ttl
        return t

    def consume(self, ticket: str) -> bool:
        self._sweep()
        expiry = self._tickets.pop(ticket, None)
        return expiry is not None and expiry > time.monotonic()

    def _sweep(self) -> None:
        now = time.monotonic()
        for k, v in list(self._tickets.items()):
            if v <= now:
                self._tickets.pop(k, None)


class Authenticator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tickets = TicketStore()
        self._whois_cache: dict[str, tuple[float, str | None]] = {}
        try:
            self._token = read_token(settings.token_path)
        except AuthError:
            raise
        if self._token is None and os.environ.get("DGXCTL_TOKEN"):
            self._token = os.environ["DGXCTL_TOKEN"]

    @property
    def token_configured(self) -> bool:
        return bool(self._token)

    def verify_token(self, presented: str | None) -> bool:
        if not self._token:
            # No token configured: only possible on a loopback bind (the guard blocks the
            # alternative), where the OS is the boundary.
            return self.settings.is_loopback
        if not presented:
            return False
        return hmac.compare_digest(presented, self._token)

    def whois(self, peer_ip: str) -> str | None:
        cached = self._whois_cache.get(peer_ip)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        identity: str | None = None
        if have("tailscale"):
            try:
                raw = run_cmd(["tailscale", "whois", "--json", peer_ip], timeout=5.0)
                data = json.loads(raw)
                identity = (data.get("UserProfile") or {}).get("LoginName") or (
                    data.get("Node") or {}
                ).get("Name")
            except Exception:  # noqa: BLE001
                identity = None
        self._whois_cache[peer_ip] = (time.monotonic() + 60.0, identity)
        return identity

    def check_allowlist(self, peer_ip: str | None) -> tuple[bool, str]:
        """Returns (allowed, identity). Empty allowlist means the check is disabled."""
        allow = self.settings.tailscale_allowlist
        if not allow:
            return True, peer_ip or "unknown"
        if peer_ip in ("127.0.0.1", "::1", None):
            return True, "local"
        identity = self.whois(peer_ip)
        if identity and identity in allow:
            return True, identity
        log.warning("allowlist rejected peer %s (identity=%s)", peer_ip, identity)
        return False, identity or peer_ip or "unknown"
