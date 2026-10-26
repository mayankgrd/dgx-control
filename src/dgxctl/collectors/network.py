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

    def __init__(self, tailnet_ips=None, port_owner=None, privileged=None) -> None:
        super().__init__()
        # Optional PrivilegedRunner (spec R17). Same command, same parser; only whose sockets
        # `ss` is allowed to name changes.
        self._privileged = privileged
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
        out, source = None, "unprivileged"
        if self._privileged is not None:
            out = await asyncio.to_thread(self._privileged.run, "sockets")
            if out is not None:
                source = "privileged"
        if out is None:
            out = await asyncio.to_thread(run_cmd, ["ss", "-tulnpH"], 10.0)
        section = NetworkSection(local_addresses=sorted(tailnet), owners_source=source)
        if self._privileged is not None:
            status = await asyncio.to_thread(self._privileged.status)
            section.privileged = status.state
            section.privileged_detail = status.detail
            section.privileged_fix = status.fix
        for row in parse_ss(out, tailnet):
            listener = Listener(**row)
            if listener.pid is None:
                listener.container_name = self._port_owner(listener.port)
            listener.is_finding = is_finding(listener.exposure)
            section.listeners.append(listener)
        section.listeners.sort(key=lambda x: (not x.is_finding, x.port))
        section.findings = [x for x in section.listeners if x.is_finding]
        section.hidden_owners = sum(
            1 for x in section.listeners if x.pid is None and not x.container_name
        )
        return section.model_dump()
