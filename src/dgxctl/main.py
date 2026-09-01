"""Application factory. One process, one port: the SPA and the API share an origin."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dgxctl import __version__
from dgxctl.actions.runner import ActionRunner
from dgxctl.auth import Authenticator, check_bind_guard
from dgxctl.collectors.containers import ContainerCollector
from dgxctl.collectors.disk import DiskCollector
from dgxctl.collectors.gpu import GpuCollector
from dgxctl.collectors.images import ImageCollector
from dgxctl.collectors.models import ModelCollector
from dgxctl.collectors.network import NetworkCollector
from dgxctl.collectors.processes import ProcessCollector
from dgxctl.collectors.pyenvs import PyEnvCollector
from dgxctl.collectors.services import ServiceCollector
from dgxctl.collectors.tailscale import TailscaleCollector
from dgxctl.config import Settings, load_settings, state_dir
from dgxctl.history import HistoryStore
from dgxctl.poller import Poller
from dgxctl.schemas import NodeInfo
from dgxctl.store import SnapshotStore

log = logging.getLogger("dgxctl")


def _install_shutdown_signal(event: asyncio.Event):
    """Tell long-lived SSE responses to finish as soon as a stop signal arrives.

    Setting the flag in lifespan *shutdown* is too late: uvicorn drains open connections
    BEFORE running lifespan shutdown, so an SSE stream holds the server open until the
    graceful-shutdown timeout fires. systemd then waits out its own timeout and SIGKILLs
    the service -- a 90-second restart ending in a kill.

    uvicorn installs its handlers with signal.signal, so chain onto them rather than
    replacing them: ours sets the flag, then uvicorn's begins the shutdown it was going to.
    """
    loop = asyncio.get_running_loop()
    previous: dict[int, object] = {}

    def make_handler(sig: int, prior):
        def handler(signum, frame):
            loop.call_soon_threadsafe(event.set)
            if callable(prior):
                prior(signum, frame)

        return handler

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            prior = signal.getsignal(sig)
            previous[sig] = prior
            signal.signal(sig, make_handler(sig, prior))
        except (ValueError, OSError):  # not the main thread (tests, embedded use)
            continue

    def restore() -> None:
        for sig, prior in previous.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, prior)

    return restore


def _web_dist() -> Path | None:
    for candidate in (
        Path(__file__).parent / "_web",
        Path(__file__).parent.parent.parent / "web" / "dist",
    ):
        if (candidate / "index.html").exists():
            return candidate
    return None


def build_collectors(settings: Settings, store: SnapshotStore) -> list:
    """Wired so collectors can read each other's latest output without coupling."""
    tailscale = TailscaleCollector()

    def tailnet_ips() -> set[str]:
        return tailscale.ips

    def section_data(name: str, key: str, default):
        env = store.section(name)
        if env is None or not isinstance(env.data, dict):
            return default
        return env.data.get(key, default)

    def container_name_for_id(cid: str) -> str | None:
        for c in section_data("containers", "containers", []):
            if c.get("id", "").startswith(cid[:12]) or cid.startswith(c.get("id", "")[:12]):
                return c.get("name")
        return None

    def container_for_host_port(port: int) -> str | None:
        for c in section_data("containers", "containers", []):
            for pb in c.get("ports") or []:
                if pb.get("host_port") == port:
                    return c.get("name")
        return None

    containers = ContainerCollector(tailnet_ips=tailscale.ips)
    containers.tailnet_ips = tailscale.ips  # refreshed each cycle below

    class _Containers(ContainerCollector):
        async def collect(self):
            self.tailnet_ips = tailnet_ips()
            return await super().collect()

    collectors = [
        GpuCollector(),
        ProcessCollector(container_lookup=container_name_for_id),
        _Containers(),
        ImageCollector(),
        DiskCollector(roots=settings.sized_roots, warn_percent=settings.disk_warn_percent),
        NetworkCollector(tailnet_ips=tailnet_ips, port_owner=container_for_host_port),
        tailscale,
        ServiceCollector(
            listeners_fn=lambda: section_data("network", "listeners", []),
            process_fn=lambda: (
                section_data("processes", "gpu_processes", [])
                + section_data("processes", "top_cpu", [])
            ),
            container_fn=lambda: section_data("containers", "containers", []),
            self_port=settings.port,
            declared=settings.services,
            advertise=settings.advertise_addresses,
            tailnet_fn=lambda: (
                tailscale.ips,
                (section_data("tailscale", "self_dns_name", None)),
            ),
        ),
        ModelCollector(hf_cache=settings.hf_cache, scan_roots=settings.model_scan_roots),
        PyEnvCollector(roots=settings.pyenv_roots),
    ]
    intervals = settings.intervals.model_dump()
    for c in collectors:
        if c.name in intervals:
            c.interval = intervals[c.name]
    return collectors


def create_app(settings: Settings | None = None, start_poller: bool = True) -> FastAPI:
    settings = settings or load_settings()
    check_bind_guard(settings)

    node = NodeInfo(id=settings.node_id, name=settings.node_name or settings.node_id, kind="local")
    store = SnapshotStore(node)
    history = HistoryStore(
        state_dir() / "history.db",
        window_minutes=settings.history_window_minutes,
        max_bytes=settings.history_max_bytes,
    )
    collectors = build_collectors(settings, store)
    poller = Poller(collectors, store, history, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.shutting_down = asyncio.Event()
        restore = _install_shutdown_signal(app.state.shutting_down)
        if start_poller:
            await poller.start()
        yield
        app.state.shutting_down.set()
        restore()
        if start_poller:
            await poller.stop()
        history.close()

    app = FastAPI(
        title="dgxctl",
        version=__version__,
        description="Observability and safe control for NVIDIA DGX Spark systems",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.history = history
    app.state.poller = poller
    app.state.auth = Authenticator(settings)
    app.state.actions = ActionRunner(settings)
    app.state.started_at = time.monotonic()

    from dgxctl.api.routes import public_router, router

    app.include_router(public_router)
    app.include_router(router)

    dist = _web_dist()
    if dist is not None:
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            # /api/* is matched by the routers above; anything reaching here and starting
            # with api/ is a genuine 404, not a route for the SPA to handle.
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse(
                {
                    "detail": (
                        "UI not built. Run: npm --prefix web ci && npm --prefix web run build"
                    ),
                    "api": "/api/snapshot",
                }
            )

    return app
