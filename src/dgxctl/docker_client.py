"""Shared Docker client. One connection, reused; absence is a normal state."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_client = None
_error: str | None = None


def get_client():
    """Returns a docker.DockerClient, or None with get_error() explaining why not."""
    global _client, _error
    with _lock:
        if _client is not None:
            return _client
        try:
            import docker

            client = docker.from_env(timeout=10)
            client.ping()
            _client = client
            _error = None
        except Exception as exc:  # noqa: BLE001
            _error = f"{type(exc).__name__}: {exc}"
            _client = None
        return _client


def get_error() -> str | None:
    return _error


def reset() -> None:
    global _client, _error
    with _lock:
        _client, _error = None, None
