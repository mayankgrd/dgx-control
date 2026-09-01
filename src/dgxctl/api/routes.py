"""HTTP surface. Every route requires auth except /api/health (spec S1)."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from dgxctl import __version__
from dgxctl.actions.runner import ActionDenied
from dgxctl.catalog import load_catalog
from dgxctl.docker_client import get_client
from dgxctl.schemas import (
    ActionLogEntry,
    ActionResult,
    CatalogSection,
    DoctorReport,
    HealthResponse,
    NodeInfo,
    SectionPayloads,
    Snapshot,
)

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api")

SSE_PING_SECONDS = 15.0


def peer_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def require_auth(request: Request) -> str:
    """Returns the caller's identity. Raises 401/403 otherwise."""
    auth = request.app.state.auth
    if not auth.verify_token(bearer(request)):
        raise HTTPException(status_code=401, detail="authentication required")
    allowed, identity = auth.check_allowlist(peer_ip(request))
    if not allowed:
        raise HTTPException(status_code=403, detail="identity not permitted")
    return identity


async def require_control(request: Request, identity: str = Depends(require_auth)) -> str:
    if not request.app.state.settings.control_enabled:
        raise HTTPException(
            status_code=403,
            detail="control actions are disabled (set control_enabled = true in config)",
        )
    return identity


# --- public -----------------------------------------------------------------


@public_router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Liveness only. Deliberately exposes NO host data (spec S1)."""
    return HealthResponse(
        version=__version__,
        uptime_seconds=round(time.monotonic() - request.app.state.started_at, 1),
    )


# --- read -------------------------------------------------------------------


@router.get("/nodes", response_model=list[NodeInfo])
async def nodes(request: Request, _: str = Depends(require_auth)) -> list[NodeInfo]:
    return request.app.state.store.nodes()


@router.get("/snapshot", response_model=Snapshot)
async def snapshot(
    request: Request, node: str | None = None, _: str = Depends(require_auth)
) -> Snapshot:
    try:
        return request.app.state.store.snapshot(node)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown node {node!r}") from exc


@router.get("/section/{name}")
async def section(
    request: Request, name: str, node: str | None = None, _: str = Depends(require_auth)
):
    env = request.app.state.store.section(name, node)
    if env is None:
        raise HTTPException(status_code=404, detail=f"unknown section {name!r}")
    return env


@router.get("/history")
async def history(
    request: Request,
    metric: str,
    window: int = Query(3600, ge=60, le=86400),
    node: str | None = None,
    _: str = Depends(require_auth),
):
    hist = request.app.state.history
    if hist is None:
        return {"metric": metric, "points": []}
    points = await asyncio.to_thread(
        hist.series, metric, window, node or request.app.state.store.local_id
    )
    return {"metric": metric, "points": points}


@router.post("/stream-ticket")
async def stream_ticket(request: Request, _: str = Depends(require_auth)):
    """EventSource cannot send an Authorization header, so it presents a single-use ticket.

    The long-lived token is never accepted as a query parameter: URLs land in logs,
    proxies and browser history.
    """
    return {"ticket": request.app.state.auth.tickets.issue(), "ttl": 30}


@public_router.get("/stream")
async def stream(request: Request, ticket: str = Query(...)):
    auth = request.app.state.auth
    if not auth.tickets.consume(ticket):
        raise HTTPException(status_code=401, detail="invalid or expired ticket")
    allowed, _identity = auth.check_allowlist(peer_ip(request))
    if not allowed:
        raise HTTPException(status_code=403, detail="identity not permitted")

    store = request.app.state.store

    shutting_down = getattr(request.app.state, "shutting_down", None)

    async def events():
        async with store.subscribe() as queue:
            payload = store.snapshot().model_dump_json()
            yield f"event: snapshot\ndata: {payload}\n\n"
            last_ping = time.monotonic()
            while True:
                # Without this the stream outlives the app, uvicorn waits for it, and
                # systemd eventually SIGKILLs the service.
                if shutting_down is not None and shutting_down.is_set():
                    return
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"event: snapshot\ndata: {store.snapshot().model_dump_json()}\n\n"
                except TimeoutError:
                    pass
                if time.monotonic() - last_ping >= SSE_PING_SECONDS:
                    last_ping = time.monotonic()
                    yield f"event: ping\ndata: {json.dumps({'ts': time.time()})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/schema/sections", response_model=SectionPayloads)
async def section_schema(_: str = Depends(require_auth)) -> SectionPayloads:
    """Type anchor: pins every section payload into the OpenAPI document (see SectionPayloads)."""
    return SectionPayloads()


@router.get("/catalog", response_model=CatalogSection)
async def catalog(_: str = Depends(require_auth)) -> CatalogSection:
    """Entries plus whether each is already running — including instances dgxctl did not
    start, which is the normal case for JupyterLab (spec R10.4)."""
    from dgxctl.catalog import find_running

    entries = []
    for entry in load_catalog():
        schema = entry.to_schema()
        schema.running = await asyncio.to_thread(find_running, entry)
        entries.append(schema)
    return CatalogSection(entries=entries)


@router.get("/process/{entry_id}/logs")
async def process_logs(
    entry_id: str, tail: int = Query(200, ge=1, le=2000), _: str = Depends(require_auth)
):
    from dgxctl import processes as procreg

    text = await asyncio.to_thread(procreg.read_log, entry_id, tail)
    if not text:
        raise HTTPException(status_code=404, detail=f"no log for {entry_id!r}")
    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.get("/containers/{name}/logs")
async def container_logs(
    name: str, tail: int = Query(200, ge=1, le=2000), _: str = Depends(require_auth)
):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Docker is not reachable")
    try:
        container = await asyncio.to_thread(client.containers.get, name)
        raw = await asyncio.to_thread(container.logs, tail=tail, timestamps=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    return Response(
        content=raw.decode("utf-8", errors="replace"), media_type="text/plain; charset=utf-8"
    )


@router.get("/doctor", response_model=DoctorReport)
async def doctor_route(request: Request, _: str = Depends(require_auth)) -> DoctorReport:
    from dgxctl.doctor import run_doctor

    return await run_doctor(request.app.state.settings)


@router.get("/config")
async def effective_config(request: Request, _: str = Depends(require_auth)):
    """Effective settings. The token is never included (spec S2)."""
    s = request.app.state.settings
    data = s.model_dump()
    for node in data.get("nodes", []):
        node.pop("token", None)
    data["token_configured"] = request.app.state.auth.token_configured
    return data


@router.get("/actions/log", response_model=list[ActionLogEntry])
async def action_log(
    request: Request, limit: int = Query(200, ge=1, le=1000), _: str = Depends(require_auth)
):
    return request.app.state.actions.read_log(limit)


# --- control ----------------------------------------------------------------


async def _run_action(request: Request, action: str, target: str, identity: str, **kwargs):
    try:
        result = await request.app.state.actions.run(action, target, identity, **kwargs)
    except ActionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return result


@router.post("/actions/container/{name}/{verb}", response_model=ActionResult)
async def container_action(
    request: Request, name: str, verb: str, identity: str = Depends(require_control)
):
    if verb not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail=f"unsupported verb {verb!r}")
    return await _run_action(request, verb, name, identity)


@router.post("/actions/launch/{entry_id}", response_model=ActionResult)
async def launch(request: Request, entry_id: str, identity: str = Depends(require_control)):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — an empty or non-JSON body means "no parameters"
        body = {}
    return await _run_action(request, "launch", entry_id, identity, params=body.get("params") or {})


@router.post("/actions/entry/{entry_id}/stop", response_model=ActionResult)
async def stop_entry(request: Request, entry_id: str, identity: str = Depends(require_control)):
    """Stop a host process dgxctl launched from a catalog entry."""
    return await _run_action(request, "stop_process", entry_id, identity)


@router.post("/actions/service/{service_id}/launch", response_model=ActionResult)
async def launch_service(
    request: Request, service_id: str, identity: str = Depends(require_control)
):
    """Launch a service declared in config."""
    return await _run_action(request, "launch_service", service_id, identity)


@router.post("/actions/process/{pid}/kill", response_model=ActionResult)
async def kill_process(request: Request, pid: int, identity: str = Depends(require_control)):
    return await _run_action(request, "kill", str(pid), identity)
