"""Spec S1-S5. The auth surface is the only thing between this service and a shared network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dgxctl.auth import AuthError, check_bind_guard, generate_token
from dgxctl.config import Settings, config_dir
from dgxctl.main import create_app

TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def app_with_token(tmp_path):
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "token").write_text(TOKEN)
    (path / "token").chmod(0o600)
    settings = Settings(host="127.0.0.1", port=8770)
    return create_app(settings, start_poller=False)


@pytest.fixture
def client(app_with_token):
    return TestClient(app_with_token)


def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def collect_routes(app):
    """Every route the app can serve.

    This walks the router objects because FastAPI wraps included routers, AND the app's own
    routes. The earlier version did only the former, so the app-level SPA catch-all was
    invisible to this sweep — and that is precisely the route that turned out to serve
    arbitrary files without authentication. A sweep that cannot see a route cannot vouch
    for it.
    """
    from dgxctl.api.routes import public_router, router

    out = []
    for r in list(router.routes) + list(public_router.routes) + list(app.routes):
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", None)
        if not methods or not path:
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((method, path))
    return sorted(set(out))


# Routes that are public by design. Everything else must demand a token.
PUBLIC_BY_DESIGN = {
    "/api/health",  # liveness only, no host data (spec S1)
    "/api/stream",  # gated by a single-use ticket instead
    "/{full_path:path}",  # the built UI; constrained by tests/integration/
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def concrete(path: str) -> str:
    return (
        path.replace("{name}", "gpu")
        .replace("{verb}", "stop")
        .replace("{entry_id}", "jupyter")
        .replace("{pid}", "999999")
        .replace("{full_path:path}", "")
    )


def test_route_table_is_not_empty(app_with_token):
    assert len(collect_routes(app_with_token)) >= 12


@pytest.mark.parametrize("method,path", collect_routes(create_app(Settings(), start_poller=False)))
def test_every_route_requires_auth(client, method, path):
    """A newly added unauthenticated route fails HERE, before it reaches a network."""
    url = concrete(path)
    if path in PUBLIC_BY_DESIGN:
        # Public routes must still be proven harmless. /{full_path:path} serves the UI and is
        # covered by tests/integration/test_path_traversal.py; health must leak nothing.
        if path == "/api/health":
            assert client.get(url).status_code == 200, "health must stay public"
        return
    resp = client.request(method, url, params={"metric": "x", "ticket": "bogus"})
    assert resp.status_code in (401, 403), (
        f"{method} {path} returned {resp.status_code} without a token — "
        f"every route except /api/health must be authenticated"
    )


def test_health_leaks_no_host_data(client):
    body = client.get("/api/health").json()
    assert set(body) == {"status", "version", "uptime_seconds"}
    text = str(body).lower()
    for leak in ("gpu", "container", "hostname", "memory", "tailscale", "path", "/home"):
        assert leak not in text


def test_wrong_token_is_401_with_a_generic_body(client):
    resp = client.get("/api/snapshot", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert TOKEN not in resp.text
    assert resp.json()["detail"] == "authentication required"


def test_valid_token_is_accepted(client):
    assert client.get("/api/snapshot", headers=auth_headers()).status_code == 200


def test_token_never_appears_in_any_response(client):
    for path in ("/api/config", "/api/health", "/api/nodes", "/api/catalog"):
        resp = client.get(path, headers=auth_headers())
        assert TOKEN not in resp.text, f"{path} leaked the token"


def test_effective_config_reports_token_presence_not_value(client):
    body = client.get("/api/config", headers=auth_headers()).json()
    assert body["token_configured"] is True
    assert "token" not in str(body).replace("token_configured", "")


# --- the bind guard (spec S3) ----------------------------------------------


def test_bind_guard_refuses_nonloopback_without_a_token():
    settings = Settings(host="0.0.0.0", port=8770)
    assert not settings.token_path.exists()
    with pytest.raises(AuthError) as exc:
        check_bind_guard(settings)
    assert "dgxctl token --init" in str(exc.value)


def test_bind_guard_allows_nonloopback_with_a_token():
    generate_token(Settings().token_path)
    check_bind_guard(Settings(host="0.0.0.0"))


def test_bind_guard_allows_loopback_without_a_token():
    check_bind_guard(Settings(host="127.0.0.1"))


def test_create_app_refuses_to_build_on_an_unguarded_bind():
    """The guard runs before uvicorn ever binds a socket."""
    with pytest.raises(AuthError):
        create_app(Settings(host="0.0.0.0"), start_poller=False)


def test_token_file_with_loose_permissions_is_refused():
    from dgxctl.auth import read_token

    path = Settings().token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("secret")
    path.chmod(0o644)
    with pytest.raises(AuthError, match="0600"):
        read_token(path)


def test_generated_token_is_0600_and_random():
    path = Settings().token_path
    a = generate_token(path)
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert len(a) >= 32
    assert generate_token(path) == a  # idempotent
    assert generate_token(path, force=True) != a  # rotation actually rotates


# --- SSE ticketing (architecture section 6) --------------------------------


def test_sse_requires_a_ticket_and_rejects_the_long_lived_token(client):
    """A token in a URL lands in logs, proxies and browser history. Never accept one."""
    assert client.get("/api/stream", params={"ticket": TOKEN}).status_code == 401
    assert client.get("/api/stream").status_code == 422  # ticket is required


def test_stream_ticket_is_single_use(client):
    ticket = client.post("/api/stream-ticket", headers=auth_headers()).json()["ticket"]
    from dgxctl.auth import TicketStore

    store = client.app.state.auth.tickets
    assert isinstance(store, TicketStore)
    assert store.consume(ticket) is True
    assert store.consume(ticket) is False, "a ticket must not be reusable"


def test_stream_ticket_expires():
    from dgxctl.auth import TicketStore

    store = TicketStore(ttl=-1)
    assert store.consume(store.issue()) is False


def test_stream_ticket_requires_auth_to_obtain(client):
    assert client.post("/api/stream-ticket").status_code == 401


# --- control gate (spec S5) -------------------------------------------------


def test_control_actions_are_disabled_by_default(client):
    resp = client.post("/api/actions/container/anything/stop", headers=auth_headers())
    assert resp.status_code == 403
    assert "control_enabled" in resp.json()["detail"]


def test_control_actions_still_require_a_token_when_enabled(tmp_path):
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "token").write_text(TOKEN)
    (path / "token").chmod(0o600)
    app = create_app(Settings(control_enabled=True), start_poller=False)
    c = TestClient(app)
    assert c.post("/api/actions/process/999999/kill").status_code == 401


def test_no_destructive_route_exists(app_with_token):
    """Reversible actions only: nothing removes a container, image or volume."""
    paths = " ".join(p for _, p in collect_routes(app_with_token))
    for word in ("remove", "delete", "prune", "rm", "destroy"):
        assert word not in paths.lower()
    assert not any(m == "DELETE" for m, _ in collect_routes(app_with_token))


def test_the_route_sweep_actually_sees_the_app_level_routes():
    """Guard on the guard. The sweep previously walked only the routers, so the SPA
    catch-all — the one route that turned out to serve arbitrary files unauthenticated —
    was never examined."""
    app = create_app(Settings(), start_poller=False)
    paths = {p for _m, p in collect_routes(app)}
    assert "/{full_path:path}" in paths, "the SPA catch-all must be visible to this sweep"
    assert "/api/snapshot" in paths, "router routes must still be visible"


def test_files_written_by_dgxctl_are_not_world_readable(tmp_path, monkeypatch):
    """config.toml can hold a peer instance's API token and decides the bind address; the
    action log records who asked for what. A stock Ubuntu umask of 002 would make both
    group-writable and world-readable."""
    import stat

    from dgxctl.actions.runner import ActionRunner
    from dgxctl.history import HistoryStore
    from dgxctl.onboarding import render_config, write_config

    cfg = tmp_path / "config.toml"
    write_config(cfg, render_config("127.0.0.1", 8770, "n", control=False))
    runner = ActionRunner(Settings(), log_path=tmp_path / "actions.jsonl")
    hist = HistoryStore(tmp_path / "history.db")
    hist.close()

    for path in (cfg, runner.log_path, tmp_path / "history.db"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert not mode & (stat.S_IRWXG | stat.S_IRWXO), (
            f"{path.name} is {oct(mode)}; must not be group- or world-accessible"
        )
