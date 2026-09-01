"""The SPA catch-all serves files and is UNAUTHENTICATED (SDD-150).

These drive the ASGI app directly. An HTTP client normalises `..` out of the path before it
is sent, so a test written with TestClient passes against a vulnerable server — which is
exactly why the original bug survived review.
"""

from __future__ import annotations

import pytest

from dgxctl.config import Settings
from dgxctl.main import create_app


@pytest.fixture
def app_with_ui(tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("INDEX")
    (web / "assets" / "app.js").write_text("APP")
    monkeypatch.setattr("dgxctl.main._web_dist", lambda: web)
    (tmp_path / "SECRET.txt").write_text("TOP-SECRET-CONTENTS")
    return create_app(Settings(), start_poller=False), tmp_path


async def raw_get(app, path: str) -> tuple[int, bytes]:
    """Send `path` verbatim, the way a raw socket or a non-normalising proxy would."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 5555),
        "server": ("127.0.0.1", 8770),
    }
    body, status = b"", None

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        nonlocal body, status
        if msg["type"] == "http.response.start":
            status = msg["status"]
        elif msg["type"] == "http.response.body":
            body += msg.get("body", b"")

    await app(scope, receive, send)
    return status, body


@pytest.mark.parametrize(
    "path",
    [
        "/../SECRET.txt",
        "/../../SECRET.txt",
        "/" + "../" * 8 + "SECRET.txt",
        "/assets/../../SECRET.txt",
        "/%2e%2e/SECRET.txt",
        "/..%2fSECRET.txt",
    ],
)
async def test_dot_dot_traversal_is_refused(app_with_ui, path):
    app, _ = app_with_ui
    _status, body = await raw_get(app, path)
    assert b"TOP-SECRET" not in body, f"{path} escaped the web root"


@pytest.mark.parametrize("target", ["/etc/passwd", "/etc/hosts"])
async def test_absolute_path_injection_is_refused(app_with_ui, target):
    """`Path("/srv/web") / "/etc/passwd"` does not join — it SUBSTITUTES, discarding the
    base. `GET //etc/passwd` therefore read arbitrary files before this was fixed."""
    app, _ = app_with_ui
    _status, body = await raw_get(app, "/" + target)
    assert b"root:" not in body and b"localhost" not in body, f"{target} was served"


async def test_the_services_own_token_cannot_be_read(app_with_ui, tmp_path):
    """The worst case: the file read was unauthenticated, so reading the API token turned it
    into a complete authentication bypass, control actions included."""
    from dgxctl.auth import generate_token
    from dgxctl.config import Settings as S

    token_path = S().token_path
    secret = generate_token(token_path)
    app, _ = app_with_ui
    for path in (f"/{token_path}", f"//{token_path}", "/../" * 12 + str(token_path)):
        _status, body = await raw_get(app, path)
        assert secret.encode() not in body, f"{path} leaked the API token"


async def test_legitimate_assets_are_still_served(app_with_ui):
    app, _ = app_with_ui
    status, body = await raw_get(app, "/assets/app.js")
    assert status == 200 and body == b"APP"


async def test_unknown_paths_still_fall_back_to_the_spa(app_with_ui):
    app, _ = app_with_ui
    status, body = await raw_get(app, "/gpu")
    assert status == 200 and body == b"INDEX"


async def test_api_paths_are_not_swallowed_by_the_spa(app_with_ui):
    app, _ = app_with_ui
    status, body = await raw_get(app, "/api/nope")
    assert status == 404 and b"INDEX" not in body


def test_process_log_names_reject_separators():
    """Defence in depth: an entry id names a catalog entry, never a path."""
    from dgxctl.processes import safe_log_name

    for bad in ["../etc/passwd", "a/b", "..", "a\\b", "", "x/../y"]:
        with pytest.raises(ValueError):
            safe_log_name(bad)
    assert safe_log_name("jupyterlab") == "jupyterlab"
