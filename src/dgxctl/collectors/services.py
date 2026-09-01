"""Discover what is running on this machine and say what each thing is (spec R15).

Classification uses the listener's full command line where it can be read: eight ZMQ ports
belonging to one notebook kernel are that notebook's plumbing, not eight services.
"""

from __future__ import annotations

import asyncio

import httpx
import psutil

from dgxctl import endpoints, services_catalog
from dgxctl.collectors.base import Collector
from dgxctl.schemas import Exposure, HostAddressInfo, ServiceInfo, ServiceSection

OPENAI_KINDS = {"vllm", "sglang", "llama.cpp", "tgi", "lmstudio"}
PROBE_KINDS = OPENAI_KINDS | {"ollama"}


def cmdline_for(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        return " ".join(psutil.Process(pid).cmdline() or [])
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


class ServiceCollector(Collector):
    name = "services"
    interval = 60.0
    timeout = 45.0
    depends_on = ("network", "processes", "containers")

    def __init__(
        self,
        listeners_fn,
        process_fn,
        container_fn,
        self_port: int | None = None,
        declared: list | None = None,
        tailnet_fn=None,
    ):
        super().__init__()
        self._listeners = listeners_fn
        self._processes = process_fn
        self._containers = container_fn
        self._self_port = self_port
        self._declared = declared or []
        self._tailnet = tailnet_fn or (lambda: (set(), None))

    async def collect(self) -> dict:
        listeners = self._listeners() or []
        procs = {p.get("pid"): p for p in (self._processes() or [])}
        containers = self._containers() or []

        by_port: dict[int, dict] = {}
        for c in containers:
            for pb in c.get("ports") or []:
                if pb.get("host_port"):
                    by_port[pb["host_port"]] = c

        section = ServiceSection()
        tailnet_ips, tailnet_name = self._tailnet()
        section.host = HostAddressInfo(**endpoints.host_addresses(tailnet_ips, tailnet_name))

        seen_ports: set[int] = set()
        for lst in listeners:
            if lst.get("protocol") != "tcp":
                continue
            port = lst["port"]
            # One service per port: a daemon on both 0.0.0.0 and :: is one service.
            if port in seen_ports:
                continue
            seen_ports.add(port)

            container = by_port.get(port)
            pid = lst.get("pid")
            cmdline = cmdline_for(pid) or (procs.get(pid, {}).get("cmdline") or "")
            hints = " ".join(
                filter(
                    None,
                    [
                        cmdline,
                        lst.get("process") or "",
                        container.get("name", "") if container else "",
                        container.get("image", "") if container else "",
                    ],
                )
            )
            kind_key = services_catalog.classify(hints, lst.get("process") or "", port)
            if kind_key == "unknown" and lst["bind_ip"] in (tailnet_ips or set()):
                # Tailscale binds ephemeral ports on the node's own tailnet address. Nothing
                # else does, so an unidentified listener there is the daemon itself.
                kind_key = "tailscale"
            kind = services_catalog.get(kind_key)
            is_self = port == self._self_port

            name = container.get("name") if container else (lst.get("process") or kind.label)
            section.services.append(
                ServiceInfo(
                    name=name or kind.label,
                    label=kind.label,
                    summary=kind.summary if not is_self else "This dashboard.",
                    category=kind.category,
                    recognised=kind_key != "unknown",
                    is_self=is_self,
                    kind=kind_key,
                    port=port,
                    bind_ip=lst["bind_ip"],
                    exposure=Exposure(lst.get("exposure", "unknown")),
                    pid=pid,
                    container_name=container.get("name") if container else None,
                    path=kind.ui_path,
                    base_url=kind.api_path,
                    auth_hint=kind.note,
                    linkable=kind.web,
                    notable=kind.category not in services_catalog.HIDDEN_BY_DEFAULT,
                )
            )

        self._merge_declared(section, seen_ports)
        await self._probe(section)
        self._attach_credentials(section)
        order = {c: i for i, c in enumerate(services_catalog.CATEGORY_ORDER)}
        section.services.sort(key=lambda s: (order.get(s.category, 99), not s.online, s.port))
        return section.model_dump()

    def _merge_declared(self, section: ServiceSection, seen_ports: set[int]) -> None:
        """Declared services are shown even when down, so their link and launch stay reachable."""
        for decl in self._declared:
            kind = services_catalog.get(
                decl.kind if decl.kind != "http" else services_catalog.classify(decl.id)
            )
            existing = next((s for s in section.services if s.port == decl.port), None)
            if existing is not None:
                existing.id = decl.id
                existing.name = decl.name or existing.name
                existing.declared = True
                existing.notable = True
                existing.recognised = True
                existing.launchable = bool(decl.launch)
                if existing.category == services_catalog.UNKNOWN:
                    existing.category = kind.category
                    existing.label = decl.name or kind.label
                    existing.summary = decl.note or kind.summary
                continue
            section.services.append(
                ServiceInfo(
                    id=decl.id,
                    name=decl.name or decl.id,
                    label=decl.name or kind.label,
                    summary=decl.note or kind.summary,
                    category=kind.category
                    if kind.category != services_catalog.UNKNOWN
                    else services_catalog.AGENT,
                    recognised=True,
                    kind=kind.key,
                    port=decl.port,
                    bind_ip="127.0.0.1",
                    exposure=Exposure.loopback,
                    path=decl.path,
                    health="unprobed",
                    declared=True,
                    online=False,
                    notable=True,
                    launchable=bool(decl.launch),
                )
            )
            seen_ports.add(decl.port)

    @staticmethod
    def _attach_credentials(section: ServiceSection) -> None:
        """Fold in a credential the service publishes locally (spec R11.2)."""
        for svc in section.services:
            if not svc.online or svc.kind != "jupyter":
                continue
            access = endpoints.describe("jupyter", svc.port)
            svc.path = access["path"] or svc.path
            svc.auth_query = access["auth_query"]
            svc.auth_hint = access["auth_hint"] or svc.auth_hint

    async def _probe(self, section: ServiceSection) -> None:
        """Probe loopback only — never reach out to an address we merely observed."""
        targets = [s for s in section.services if s.kind in PROBE_KINDS and s.online]
        if not targets:
            return
        async with httpx.AsyncClient(timeout=2.0) as client:

            async def probe(svc: ServiceInfo) -> None:
                path = "/api/tags" if svc.kind == "ollama" else "/v1/models"
                try:
                    resp = await client.get(f"http://127.0.0.1:{svc.port}{path}")
                except (httpx.HTTPError, OSError):
                    svc.health = "unreachable"
                    return
                svc.health = "ok" if resp.status_code < 500 else "unreachable"
                try:
                    payload = resp.json()
                except ValueError:
                    return
                if isinstance(payload, dict):
                    for item in payload.get("data") or payload.get("models") or []:
                        if isinstance(item, dict):
                            mid = item.get("id") or item.get("name") or item.get("model")
                            if mid:
                                svc.served_models.append(str(mid))

            await asyncio.gather(*(probe(s) for s in targets), return_exceptions=True)
