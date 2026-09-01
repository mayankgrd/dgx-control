"""Listening sockets and the exposure audit — the headline safety feature."""

from __future__ import annotations

import asyncio

from dgxctl.collectors.base import Collector, have, run_cmd
from dgxctl.collectors.util import is_finding, parse_ss
from dgxctl.schemas import Listener, NetworkSection


class NetworkCollector(Collector):
    name = "network"
    interval = 15.0
    timeout = 15.0

    def __init__(self, tailnet_ips=None, port_owner=None) -> None:
        super().__init__()
        self._tailnet_ips = tailnet_ips or (lambda: set())
        # Root-owned listeners show no PID to an unprivileged caller; a container's
        # published port is still attributable by matching the host port.
        self._port_owner = port_owner or (lambda _p: None)

    async def available(self) -> bool:
        if not have("ss"):
            self.mark_unavailable("`ss` not found (install iproute2)")
            return False
        return True

    async def collect(self) -> dict:
        tailnet = self._tailnet_ips()
        out = await asyncio.to_thread(run_cmd, ["ss", "-tulnpH"], 10.0)
        section = NetworkSection(local_addresses=sorted(tailnet))
        for row in parse_ss(out, tailnet):
            listener = Listener(**row)
            if listener.pid is None:
                listener.container_name = self._port_owner(listener.port)
            listener.is_finding = is_finding(listener.exposure)
            section.listeners.append(listener)
        section.listeners.sort(key=lambda x: (not x.is_finding, x.port))
        section.findings = [x for x in section.listeners if x.is_finding]
        return section.model_dump()
