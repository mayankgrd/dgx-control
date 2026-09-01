"""API shape, poller behaviour, and the SPA/API routing seam."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dgxctl.collectors.base import Collector
from dgxctl.config import Settings, config_dir
from dgxctl.history import HistoryStore
from dgxctl.main import create_app
from dgxctl.poller import Poller
from dgxctl.schemas import Envelope, NodeInfo, Status
from dgxctl.store import SnapshotStore

TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def client():
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "token").write_text(TOKEN)
    (path / "token").chmod(0o600)
    return TestClient(create_app(Settings(), start_poller=False))


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_snapshot_envelope_shape(client):
    client.app.state.store._sections["local"]["gpu"] = Envelope(
        status=Status.ok, data={"devices": []}, collected_at="2026-01-01T00:00:00Z", duration_ms=3.2
    )
    body = client.get("/api/snapshot", headers=headers()).json()
    assert set(body) == {"node", "version", "sections"}
    env = body["sections"]["gpu"]
    assert set(env) == {"status", "data", "error", "collected_at", "duration_ms"}
    assert env["status"] == "ok"


def test_snapshot_is_served_from_cache_not_by_collecting(client):
    """Spec N2: collectors never run on the request path."""
    ran = []

    class Tripwire(Collector):
        name = "tripwire"

        async def collect(self):
            ran.append(1)
            return {}

    client.app.state.poller.collectors.append(Tripwire())
    for _ in range(5):
        assert client.get("/api/snapshot", headers=headers()).status_code == 200
    assert ran == [], "a request triggered collection"


def test_unknown_section_and_node_are_404(client):
    assert client.get("/api/section/nope", headers=headers()).status_code == 404
    assert (
        client.get("/api/snapshot", params={"node": "nope"}, headers=headers()).status_code == 404
    )


def test_api_404_is_json_not_the_spa(client):
    """The SPA catch-all must never shadow /api/*."""
    resp = client.get("/api/does-not-exist", headers=headers())
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


def test_nodes_lists_the_local_node(client):
    body = client.get("/api/nodes", headers=headers()).json()
    assert [n["id"] for n in body] == ["local"]
    assert body[0]["kind"] == "local"


def test_catalog_is_exposed_with_its_warnings(client):
    body = client.get("/api/catalog", headers=headers()).json()
    ids = {e["id"] for e in body["entries"]}
    assert {"vllm-server", "jupyterlab"} <= ids
    vllm = next(e for e in body["entries"] if e["id"] == "vllm-server")
    assert vllm["bind"] == "127.0.0.1" and vllm["kind"] == "container"
    jl = next(e for e in body["entries"] if e["id"] == "jupyterlab")
    assert jl["kind"] == "process" and jl["bind"] == "127.0.0.1"


def test_history_endpoint_returns_points(client, tmp_path):
    hist = HistoryStore(tmp_path / "h.db")
    hist.record("gpu.utilization", 42.0)
    client.app.state.history = hist
    body = client.get(
        "/api/history", params={"metric": "gpu.utilization"}, headers=headers()
    ).json()
    assert [p["value"] for p in body["points"]] == [42.0]
    hist.close()


def test_openapi_documents_every_section_schema(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for expected in ("GpuSection", "ContainerSection", "NetworkSection", "ModelSection"):
        assert expected in schemas, f"{expected} missing from the generated contract"


# --- poller -----------------------------------------------------------------


class Counter(Collector):
    def __init__(self, name, interval):
        super().__init__()
        self.name, self.interval, self.count = name, interval, 0

    async def collect(self):
        self.count += 1
        return {"n": self.count}


class Hanger(Collector):
    name = "hanger"
    interval = 0.01
    timeout = 0.05

    async def collect(self):
        await asyncio.sleep(10)


async def test_slow_collector_does_not_delay_a_fast_one():
    fast = Counter("fast", 0.02)
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    poller = Poller([fast, Hanger()], store)
    await poller.start()
    await asyncio.sleep(0.3)
    await poller.stop()
    assert fast.count >= 5, f"fast collector only ran {fast.count} times behind a hung one"
    assert store.section("hanger").status is Status.error


async def test_failing_collector_does_not_stop_the_poller():
    class Boom(Collector):
        name = "boom"
        interval = 0.01

        async def collect(self):
            raise RuntimeError("nope")

    good = Counter("good", 0.01)
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    poller = Poller([Boom(), good], store)
    await poller.start()
    await asyncio.sleep(0.2)
    await poller.stop()
    assert good.count >= 5
    assert store.section("boom").status is Status.error


async def test_poller_shuts_down_cleanly():
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    poller = Poller([Counter("a", 0.01)], store)
    await poller.start()
    await asyncio.sleep(0.05)
    await poller.stop()
    assert all(t.done() for t in poller._tasks) or not poller._tasks


async def test_history_records_gpu_and_container_metrics(tmp_path):
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    hist = HistoryStore(tmp_path / "h.db")
    poller = Poller([], store, hist)
    poller._record(
        Envelope(
            status=Status.ok,
            data={
                "devices": [{"utilization_percent": 55.0}],
                "memory": {"total_bytes": 100, "used_bytes": 40, "gpu_reserved_bytes": 20},
            },
        ),
        "gpu",
    )
    poller._record(Envelope(status=Status.ok, data={"running": 3}), "containers")
    assert hist.series("gpu.utilization")[0]["value"] == 55.0
    assert hist.series("memory.used_percent")[0]["value"] == 40.0
    assert hist.series("gpu.memory_percent")[0]["value"] == 20.0
    assert hist.series("containers.running")[0]["value"] == 3.0
    hist.close()


async def test_history_ignores_errored_collectors(tmp_path):
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    hist = HistoryStore(tmp_path / "h.db")
    poller = Poller([], store, hist)
    poller._record(Envelope(status=Status.error, data={"devices": []}), "gpu")
    assert hist.series("gpu.utilization") == []
    hist.close()


class Slow(Collector):
    """Stands in for `containers`, whose first reading takes seconds."""

    name = "source"
    interval = 5.0

    async def collect(self):
        await asyncio.sleep(0.3)
        return {"items": [1, 2, 3]}


class Dependent(Collector):
    name = "dependent"
    interval = 5.0
    depends_on = ("source",)

    def __init__(self, store):
        super().__init__()
        self._store = store

    async def collect(self):
        env = self._store.section("source")
        return {"seen": (env.data or {}).get("items", []) if env else []}


async def test_dependent_collector_waits_for_its_source():
    """Live regression: `services` classified a vLLM port as generic `http` because it ran
    before `containers` had reported. A fixed startup delay cannot fix this — how long
    `containers` takes depends on how many containers are running."""
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    poller = Poller([Slow(), Dependent(store)], store)
    await poller.start()
    await asyncio.sleep(0.6)
    await poller.stop()
    assert store.section("dependent").data == {"seen": [1, 2, 3]}, (
        "the dependent collector ran before its source had populated the store"
    )


async def test_dependent_collector_starts_anyway_if_its_source_never_reports():
    """A permanently-unavailable dependency must not wedge the dependent collector."""
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    dependent = Dependent(store)
    poller = Poller([dependent], store)
    await poller._await_dependencies(dependent, limit=0.5)
    assert store.section("source") is None  # never arrived; we returned regardless


async def test_sse_stream_ends_when_the_app_shuts_down():
    """Live regression: a long-lived SSE response held uvicorn open in "waiting for
    connections to close" until systemd's stop timeout expired and SIGKILLed the service —
    every restart took 90 seconds and ended in a kill."""
    import asyncio as _asyncio

    from dgxctl.api.routes import stream

    class FakeRequest:
        def __init__(self, app):
            self.app = app
            self.client = type("C", (), {"host": "127.0.0.1"})()

        async def is_disconnected(self):
            return False

    class FakeState:
        pass

    store = SnapshotStore(NodeInfo(id="local", name="local"))
    app = type("App", (), {})()
    app.state = FakeState()
    app.state.store = store
    app.state.shutting_down = _asyncio.Event()

    class FakeAuth:
        class tickets:
            @staticmethod
            def consume(_):
                return True

        @staticmethod
        def check_allowlist(_):
            return True, "local"

    app.state.auth = FakeAuth()

    response = await stream(FakeRequest(app), ticket="anything")
    agen = response.body_iterator
    first = await agen.__anext__()
    assert "event: snapshot" in first

    app.state.shutting_down.set()
    with pytest.raises(StopAsyncIteration):
        await _asyncio.wait_for(agen.__anext__(), timeout=3.0)
    assert store.subscriber_count == 0, "the subscriber must be released on shutdown"


def test_shutdown_signal_is_chained_not_replaced():
    """uvicorn installs its own SIGTERM handler with signal.signal. Replacing it would stop
    the server from ever shutting down; ours must run first and then delegate."""
    import signal as _signal

    from dgxctl.main import _install_shutdown_signal

    called = []

    def uvicorn_handler(signum, frame):
        called.append(signum)

    original = _signal.getsignal(_signal.SIGTERM)
    _signal.signal(_signal.SIGTERM, uvicorn_handler)
    try:

        async def run():
            event = asyncio.Event()
            restore = _install_shutdown_signal(event)
            handler = _signal.getsignal(_signal.SIGTERM)
            assert handler is not uvicorn_handler, "our handler must be installed"
            handler(_signal.SIGTERM, None)  # simulate the signal
            await asyncio.sleep(0)
            assert event.is_set(), "our flag must be set"
            assert called == [_signal.SIGTERM], "uvicorn's handler must still run"
            restore()
            assert _signal.getsignal(_signal.SIGTERM) is uvicorn_handler

        asyncio.run(run())
    finally:
        _signal.signal(_signal.SIGTERM, original)
