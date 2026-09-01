"""Shared helpers: exposure classification and cgroup→container parsing."""

from __future__ import annotations

import ipaddress
import re

from dgxctl.schemas import Exposure

# cgroup v2: 0::/system.slice/docker-<64hex>.scope
# cgroup v1: 12:cpu,cpuacct:/docker/<64hex>
_CGROUP_PATTERNS = [
    re.compile(r"docker[-/]([0-9a-f]{64})"),
    re.compile(r"/docker/([0-9a-f]{12,64})"),
    re.compile(r"cri-containerd-([0-9a-f]{64})"),
    re.compile(r"/kubepods.*/([0-9a-f]{64})"),
]


def container_id_from_cgroup(text: str) -> str | None:
    """Works for cgroup v1 and v2. Returns the full container id, or None."""
    for pat in _CGROUP_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def strip_zone(addr: str) -> str:
    """`127.0.0.53%lo` and `fe80::1%eth0` carry an interface zone. Drop it."""
    return addr.split("%", 1)[0]


def classify_exposure(bind_ip: str, tailnet_ips: set[str] | None = None) -> Exposure:
    """The safety signal. Wildcard binds are reachable by anyone who can route to the host."""
    if bind_ip is None:
        return Exposure.unknown
    addr = strip_zone(bind_ip.strip())
    if addr in ("*", "", "0.0.0.0", "::", "[::]"):  # noqa: S104
        return Exposure.all
    addr = addr.strip("[]")
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return Exposure.unknown
    if ip.is_unspecified:
        return Exposure.all
    if tailnet_ips and addr in tailnet_ips:
        return Exposure.tailnet
    if ip.is_loopback:
        return Exposure.loopback
    # Tailscale's CGNAT range, even when we could not read `tailscale status`.
    if ip.version == 4 and ipaddress.ip_address(addr) in ipaddress.ip_network("100.64.0.0/10"):
        return Exposure.tailnet
    if ip.version == 6 and addr.lower().startswith("fd7a:115c:a1e0"):
        return Exposure.tailnet
    if ip.is_link_local:
        return Exposure.lan
    return Exposure.lan


def is_finding(exposure: Exposure) -> bool:
    return exposure in (Exposure.all, Exposure.lan, Exposure.tailnet)


def parse_ss(output: str, tailnet_ips: set[str] | None = None) -> list[dict]:
    """Parse `ss -tulnpH`.

    Real-world shapes this must survive (all captured from a live DGX Spark):
        tcp LISTEN 0 4096 0.0.0.0:6006 0.0.0.0:*
        tcp LISTEN 0 2048 127.0.0.1:42835 0.0.0.0:* users:(("hermes",pid=1442365,fd=6))
        tcp LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*
        tcp LISTEN 0 4096 [::]:22 [::]:*
        tcp LISTEN 0 4096 [fd7a:115c:a1e0::1111:2222]:54847 [::]:*
        udp UNCONN 0 0 [fe80::efb7:...]%wlP9s9:546 [::]:*
    PIDs appear only for processes the caller owns; absence is normal, not an error.
    """
    results: list[dict] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        proto, state = parts[0], parts[1]
        if proto not in ("tcp", "udp"):
            continue
        if proto == "tcp" and state != "LISTEN":
            continue
        if proto == "udp" and state not in ("UNCONN", "LISTEN"):
            continue
        local = parts[4]
        # Split host:port from the right — IPv6 hosts contain colons.
        if ":" not in local:
            continue
        host, _, port_s = local.rpartition(":")
        try:
            port = int(port_s)
        except ValueError:
            continue
        host = strip_zone(host).strip("[]")  # `[::]` and `::` must not be two things
        pid: int | None = None
        process: str | None = None
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if m:
            process, pid = m.group(1), int(m.group(2))
        exposure = classify_exposure(host, tailnet_ips)
        results.append(
            {
                "protocol": proto,
                "bind_ip": host if host else "0.0.0.0",  # noqa: S104
                "port": port,
                "exposure": exposure,
                "pid": pid,
                "process": process,
            }
        )
    return results
