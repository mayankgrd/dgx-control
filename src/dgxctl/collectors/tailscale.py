"""Tailscale state. Always `--json` — the human-readable form is not a stable contract."""

from __future__ import annotations

import asyncio
import json

from dgxctl.collectors.base import Collector, have, run_cmd
from dgxctl.schemas import TailscalePeer, TailscaleSection


def parse_status(payload: dict) -> TailscaleSection:
    """Tolerant of missing keys: fields move between Tailscale versions."""
    self_node = payload.get("Self") or {}
    section = TailscaleSection(
        backend_state=payload.get("BackendState", "Unknown"),
        version=payload.get("Version"),
        self_hostname=self_node.get("HostName"),
        self_dns_name=(self_node.get("DNSName") or "").rstrip("."),
        self_ips=list(payload.get("TailscaleIPs") or self_node.get("TailscaleIPs") or []),
        exit_node_active=bool(payload.get("ExitNodeStatus")),
    )
    for peer in (payload.get("Peer") or {}).values():
        section.peers.append(
            TailscalePeer(
                hostname=peer.get("HostName", "?"),
                dns_name=(peer.get("DNSName") or "").rstrip("."),
                os=peer.get("OS"),
                ips=list(peer.get("TailscaleIPs") or []),
                online=bool(peer.get("Online")),
                exit_node=bool(peer.get("ExitNode")),
            )
        )
    section.peers.sort(key=lambda p: (not p.online, p.hostname.lower()))
    return section


class TailscaleCollector(Collector):
    name = "tailscale"
    interval = 15.0
    timeout = 15.0

    def __init__(self) -> None:
        super().__init__()
        self.ips: set[str] = set()

    async def available(self) -> bool:
        if not have("tailscale"):
            self.mark_unavailable("tailscale CLI not installed")
            return False
        return True

    async def collect(self) -> dict:
        raw = await asyncio.to_thread(run_cmd, ["tailscale", "status", "--json"], 10.0)
        section = parse_status(json.loads(raw))
        self.ips = set(section.self_ips)
        return section.model_dump()
