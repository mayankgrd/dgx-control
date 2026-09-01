"""Turning "a service exists" into "here is how you use it" (spec R11).

Only the browser knows how the viewer reached the dashboard, so this module never composes a
full URL. It supplies everything after the origin: the path, a credential query where one can
be read locally, a hint where one cannot, and an OpenAI base_url for model servers.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlencode

import psutil

JUPYTER_RUNTIME_DIRS = (
    "~/.local/share/jupyter/runtime",
    "~/.jupyter/runtime",
)


def _pid_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def jupyter_servers() -> dict[int, dict]:
    """{port: {token, pid, root_dir, base_url}} for LIVE Jupyter servers.

    Jupyter leaves its runtime json behind when it dies, so a stale file would otherwise
    produce a confident link to nothing. Every entry is checked against a live pid.
    """
    found: dict[int, dict] = {}
    for raw_dir in JUPYTER_RUNTIME_DIRS:
        d = Path(raw_dir).expanduser()
        if not d.is_dir():
            continue
        for f in d.glob("jpserver-*.json"):
            try:
                info = json.loads(f.read_text())
            except (ValueError, OSError):
                continue
            pid, port = info.get("pid"), info.get("port")
            if not isinstance(pid, int) or not isinstance(port, int):
                continue
            if not _pid_alive(pid):
                continue
            found[port] = {
                "token": info.get("token") or None,
                "pid": pid,
                "root_dir": info.get("root_dir"),
                "base_url": info.get("base_url") or "/",
            }
    return found


def describe(kind: str, port: int, served_models: list[str] | None = None) -> dict:
    """Access details for one service. Values here reach an authenticated browser only."""
    out: dict[str, str | None] = {
        "auth_query": None,
        "auth_hint": None,
        "base_url": None,
        "path": "/",
    }

    if kind == "jupyter":
        server = jupyter_servers().get(port)
        if server and server["token"]:
            out["path"] = server["base_url"] or "/"
            out["auth_query"] = "?" + urlencode({"token": server["token"]})
        else:
            out["auth_hint"] = (
                "Could not read this server's token. Run `jupyter lab list` on the DGX to get "
                "the URL with its token."
            )
        return out

    # `base_url` is a PATH, never a full URL: only the browser knows the right origin.
    # Composing it here produced "http://host:8010/docs/v1" and "http://host:11434//v1".
    if kind in ("vllm", "sglang", "llama.cpp"):
        out["path"] = "/docs"
        out["base_url"] = "/v1"
        return out

    if kind == "ollama":
        out["base_url"] = "/v1"
        return out

    if kind in ("hermes", "hermes-gateway"):
        out["auth_hint"] = (
            "Hermes authenticates with a per-session token it prints at startup; a 401 here is "
            "expected, not a fault. Connect with Hermes Desktop or the CLI rather than a browser."
        )
        return out

    if kind == "ssh":
        out["auth_hint"] = "Not a web service — connect with an SSH client."
        return out

    return out


def tunnel_command(port: int, host_alias: str = "<your-dgx>") -> str:
    """What to run locally to reach a loopback-bound service."""
    return f"ssh -N -L {port}:127.0.0.1:{port} {host_alias}"


# --- where this machine can be reached (spec R16.1) --------------------------

# Addresses a viewer can never be at, so they are not "LAN".
DOCKER_BRIDGE_NETS = (
    ipaddress.ip_network("172.17.0.0/16"),
    ipaddress.ip_network("172.18.0.0/16"),
    ipaddress.ip_network("172.19.0.0/16"),
    ipaddress.ip_network("172.20.0.0/14"),
)
TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")


def is_docker_bridge(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.strip("[]").split("%")[0])
    except ValueError:
        return False
    return ip.version == 4 and any(ip in net for net in DOCKER_BRIDGE_NETS)


def lan_addresses() -> list[str]:
    """Routable IPv4 addresses of this host, excluding loopback, Docker bridges and the tailnet.

    IPv6 is omitted deliberately: a link built from a temporary privacy address would be worse
    than none, and every machine here has a usable v4 address.
    """
    import socket

    found: list[str] = []
    try:
        interfaces = psutil.net_if_addrs()
    except Exception:  # noqa: BLE001 - an address list is a nicety, never a failure
        return found

    for _iface, addrs in interfaces.items():
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            addr = (a.address or "").split("%")[0]
            if not addr:
                continue
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local or ip in TAILNET_NET:
                continue
            if is_docker_bridge(addr):
                continue
            if addr not in found:
                found.append(addr)
    return found


def host_addresses(tailnet_ips: set[str] | None = None, tailnet_name: str | None = None) -> dict:
    """What a URL to this machine could legitimately be built from."""
    import socket

    ips = sorted(tailnet_ips or set())
    v4 = next((i for i in ips if ":" not in i), None)
    return {
        "hostname": socket.gethostname(),
        "loopback": "127.0.0.1",
        "lan": lan_addresses(),
        "tailnet_ip": v4,
        "tailnet_name": tailnet_name,
    }
