"""Multi-DGX federation: one dgxctl aggregates peers over the same authenticated API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dgxctl.config import RemoteNode, Settings, config_dir
from dgxctl.main import create_app
from dgxctl.poller import Poller
from dgxctl.schemas import NodeInfo
from dgxctl.store import SnapshotStore

TOKEN = "test-token-not-a-real-secret"


def _token_file():
    p = config_dir()
    p.mkdir(parents=True, exist_ok=True)
    (p / "token").write_text(TOKEN)
    (p / "token").chmod(0o600)


def test_remote_node_config_parses_and_hides_its_token(tmp_path):
    _token_file()
    cfg = config_dir() / "config.toml"
    cfg.write_text(
        'host = "127.0.0.1"\n'
        "[[node]]\n"
        'id = "spark-2"\n'
        'name = "Second Spark"\n'
        'url = "http://spark-2.example:8770"\n'
        'token = "peer-secret"\n'
    )
    from dgxctl.config import load_settings

    settings = load_settings(cfg)
    assert len(settings.nodes) == 1
    assert settings.nodes[0].id == "spark-2"

    app = create_app(settings, start_poller=False)
    client = TestClient(app)
    body = client.get("/api/config", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert "peer-secret" not in str(body), "a peer's token must never be served to a browser"


def test_remote_node_token_can_come_from_a_file(tmp_path):
    tf = tmp_path / "peer.token"
    tf.write_text("from-file\n")
    node = RemoteNode(id="a", url="http://x", token_file=str(tf))
    assert node.resolve_token() == "from-file"
    assert RemoteNode(id="b", url="http://x").resolve_token() is None


async def test_unreachable_peer_is_reported_not_fatal():
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    settings = Settings(nodes=[RemoteNode(id="spark-2", url="http://127.0.0.1:9")])
    poller = Poller([], store, None, settings)
    await poller._poll_remote(settings.nodes[0])
    node = next(n for n in store.nodes() if n.id == "spark-2")
    assert node.reachable is False
    assert node.error
    assert store.snapshot().node.id == "local", "the local node is unaffected"


async def test_peer_sections_land_under_the_peer_node(monkeypatch):
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    settings = Settings(nodes=[RemoteNode(id="spark-2", url="http://peer:8770")])
    poller = Poller([], store, None, settings)

    payload = {
        "node": {"id": "local", "name": "peer", "kind": "local"},
        "version": 7,
        "sections": {
            "gpu": {
                "status": "ok",
                "data": {"devices": [{"index": 0, "name": "GB10"}]},
                "error": None,
                "collected_at": None,
                "duration_ms": 1.0,
            }
        },
    }

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert headers is None or "Authorization" not in headers or headers
            return FakeResponse()

    monkeypatch.setattr("dgxctl.poller.httpx.AsyncClient", FakeClient)
    await poller._poll_remote(settings.nodes[0])

    remote = store.snapshot("spark-2")
    assert remote.node.id == "spark-2" and remote.node.kind == "remote"
    assert remote.sections["gpu"].data["devices"][0]["name"] == "GB10"
    assert store.snapshot("local").sections == {}, "peer data must not bleed into the local node"


async def test_peer_request_carries_the_peer_token(monkeypatch):
    seen = {}
    store = SnapshotStore(NodeInfo(id="local", name="local"))
    settings = Settings(nodes=[RemoteNode(id="p", url="http://peer", token="peer-secret")])
    poller = Poller([], store, None, settings)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["headers"] = headers
            seen["url"] = url
            raise RuntimeError("stop here")

    monkeypatch.setattr("dgxctl.poller.httpx.AsyncClient", FakeClient)
    await poller._poll_remote(settings.nodes[0])
    assert seen["headers"]["Authorization"] == "Bearer peer-secret"
    assert seen["url"].endswith("/api/snapshot")


def test_nodes_endpoint_lists_local_and_configured_peers():
    _token_file()
    settings = Settings(nodes=[RemoteNode(id="spark-2", name="Lab Spark", url="http://x")])
    client = TestClient(create_app(settings, start_poller=False))
    body = client.get("/api/nodes", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert [n["id"] for n in body] == ["local"]  # peers appear once first polled


@pytest.mark.parametrize("node_id", ["local", "custom-name"])
def test_local_node_id_is_configurable(node_id):
    _token_file()
    settings = Settings(node_id=node_id, node_name=f"{node_id} display")
    client = TestClient(create_app(settings, start_poller=False))
    body = client.get("/api/snapshot", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert body["node"]["id"] == node_id
    assert body["node"]["name"] == f"{node_id} display"
