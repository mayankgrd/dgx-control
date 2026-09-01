"""Where a service can actually be reached from, given where the viewer is (spec R16).

A URL is only correct relative to two facts: what the service is bound to, and where the person
looking at the page is. Getting this wrong hands someone a link that silently resolves on their
own laptop. This is a pure function of those two facts so the whole matrix can be tested.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

LOOPBACK = "loopback"
LAN = "lan"
TAILNET = "tailnet"
UNKNOWN = "unknown"

DOCKER_BRIDGE_PREFIXES = ("172.17.", "172.18.", "172.19.", "172.20.")


@dataclass
class HostAddresses:
    hostname: str = "this machine"
    loopback: str = "127.0.0.1"
    lan: list[str] = field(default_factory=list)
    tailnet_ip: str | None = None
    tailnet_name: str | None = None

    @property
    def tailnet(self) -> str | None:
        """Prefer the MagicDNS name: it survives an address change and reads better."""
        return self.tailnet_name or self.tailnet_ip


@dataclass
class AccessRoute:
    url: str
    label: str
    caveat: str | None = None


@dataclass
class AccessPlan:
    viewer: str  # loopback | lan | tailnet | unknown
    viewer_note: str = ""
    routes: list[AccessRoute] = field(default_factory=list)
    forward_command: str | None = None
    forward_url: str | None = None
    forward_reason: str | None = None
    unreachable_reason: str | None = None

    @property
    def primary(self) -> AccessRoute | None:
        return self.routes[0] if self.routes else None


def _is(addr: str, predicate: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.strip("[]").split("%")[0])
    except ValueError:
        return False
    if predicate == "loopback":
        return ip.is_loopback
    if predicate == "wildcard":
        return ip.is_unspecified
    return False


def classify_viewer(origin_host: str, host: HostAddresses) -> str:
    """Where is the person looking at this page?"""
    if not origin_host:
        return UNKNOWN
    bare = origin_host.strip("[]").split("%")[0]
    if bare in ("localhost", "127.0.0.1", "::1") or _is(bare, "loopback"):
        return LOOPBACK
    if host.tailnet_name and bare == host.tailnet_name:
        return TAILNET
    if host.tailnet_ip and bare == host.tailnet_ip:
        return TAILNET
    try:
        ip = ipaddress.ip_address(bare)
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return TAILNET
    except ValueError:
        pass
    if bare in host.lan or bare == host.hostname:
        return LAN
    return LAN if _looks_routable(bare) else UNKNOWN


def _looks_routable(bare: str) -> bool:
    try:
        ipaddress.ip_address(bare)
        return True
    except ValueError:
        return bool(bare)  # a hostname we do not recognise; treat as LAN-ish


def service_scope(bind_ip: str) -> str:
    """What can reach this service at all."""
    bare = (bind_ip or "").strip("[]").split("%")[0]
    if bare in ("", "*", "0.0.0.0", "::"):  # noqa: S104 - recognising it, not binding it
        return "all"
    if _is(bare, "wildcard"):
        return "all"
    if _is(bare, "loopback"):
        return "host-only"
    if bare.startswith(DOCKER_BRIDGE_PREFIXES):
        # Reachable from the host and from containers, but from nowhere a viewer sits.
        return "host-only"
    try:
        ip = ipaddress.ip_address(bare)
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return "tailnet-only"
    except ValueError:
        return "all"
    return "lan-only"


def plan(
    bind_ip: str,
    port: int,
    origin_host: str,
    host: HostAddresses,
    scheme: str = "http",
    path: str = "/",
    is_self: bool = False,
) -> AccessPlan:
    """How this viewer should reach this service."""
    viewer = classify_viewer(origin_host, host)
    scope = service_scope(bind_ip)
    suffix = path if path.startswith("/") else f"/{path}"
    result = AccessPlan(viewer=viewer)

    result.viewer_note = {
        LOOPBACK: "You opened this dashboard on 127.0.0.1 — either from the machine itself, "
        "or through NVIDIA Sync or an SSH tunnel.",
        LAN: "You are reaching this dashboard over the local network.",
        TAILNET: "You are reaching this dashboard over the tailnet.",
        UNKNOWN: "",
    }[viewer]

    def url(hostpart: str) -> str:
        return f"{scheme}://{hostpart}:{port}{suffix}"

    remote_target = (
        host.tailnet if viewer == TAILNET else (host.lan[0] if host.lan else host.tailnet)
    )

    if scope == "all":
        if viewer == TAILNET and host.tailnet:
            result.routes.append(AccessRoute(url(host.tailnet), "over the tailnet"))
        elif viewer == LAN and host.lan:
            result.routes.extend(
                AccessRoute(url(a), f"over the local network ({a})") for a in host.lan
            )
        elif viewer == LOOPBACK:
            result.routes.append(
                AccessRoute(url("127.0.0.1"), "if your browser is on the DGX itself")
            )
            for a in host.lan:
                result.routes.append(AccessRoute(url(a), f"from another machine on the LAN ({a})"))
            if host.tailnet:
                result.routes.append(AccessRoute(url(host.tailnet), "from your tailnet"))
        else:
            for a in host.lan:
                result.routes.append(AccessRoute(url(a), f"over the local network ({a})"))
            if host.tailnet:
                result.routes.append(AccessRoute(url(host.tailnet), "over the tailnet"))
        return result

    if scope == "tailnet-only":
        if viewer == TAILNET:
            result.routes.append(AccessRoute(url(bind_ip), "over the tailnet"))
        else:
            result.unreachable_reason = (
                "This service is bound to the tailnet address only, so it cannot be reached "
                "from where you are. Connect to the tailnet, or use a port forward from the DGX."
            )
        return result

    if scope == "lan-only":
        if viewer in (LAN, LOOPBACK):
            result.routes.append(AccessRoute(url(bind_ip), f"at {bind_ip}"))
        else:
            result.unreachable_reason = (
                f"This service is bound to {bind_ip} only, which is not reachable from the tailnet."
            )
        return result

    # host-only: loopback or a Docker bridge address.
    if is_self:
        result.routes.append(AccessRoute(url("127.0.0.1"), "this dashboard"))
        return result

    if viewer == LOOPBACK:
        result.routes.append(
            AccessRoute(
                url("127.0.0.1"),
                "if your browser is running on the DGX itself",
                caveat="If you reached this dashboard through NVIDIA Sync or an SSH tunnel, "
                "only the dashboard's own port was forwarded — this one needs its own "
                "forward, below.",
            )
        )

    if remote_target:
        result.forward_command = f"ssh -N -L {port}:127.0.0.1:{port} {remote_target}"
        result.forward_url = url("127.0.0.1")
        result.forward_reason = (
            "This service listens on the DGX's loopback address, so nothing outside the machine "
            "can reach it directly. Run this on your own machine, then open the link."
        )
    else:
        result.unreachable_reason = (
            "This service listens on the DGX's loopback address and dgxctl does not know an "
            "address you could tunnel to. Use `ssh -N -L "
            f"{port}:127.0.0.1:{port} <your-dgx>`."
        )
    return result
