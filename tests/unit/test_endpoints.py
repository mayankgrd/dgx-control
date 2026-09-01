"""Access endpoints: turning "it exists" into "here is how you use it" (SDD-103)."""

from __future__ import annotations

import json
import os

from dgxctl import endpoints


def _write_runtime(tmp_path, pid: int, port: int, token: str | None = "tok123"):
    d = tmp_path / "runtime"
    d.mkdir(exist_ok=True)
    (d / f"jpserver-{pid}.json").write_text(
        json.dumps(
            {
                "base_url": "/",
                "hostname": "localhost",
                "password": False,
                "pid": pid,
                "port": port,
                "root_dir": "/home/user/jupyterlab",
                "secure": False,
                "token": token,
                "url": f"http://localhost:{port}/",
                "version": "2.17.0",
            }
        )
    )
    return d


def test_jupyter_token_is_read_from_the_runtime_file(tmp_path, monkeypatch):
    d = _write_runtime(tmp_path, os.getpid(), 11002)
    monkeypatch.setattr(endpoints, "JUPYTER_RUNTIME_DIRS", (str(d),))
    servers = endpoints.jupyter_servers()
    assert servers[11002]["token"] == "tok123"

    access = endpoints.describe("jupyter", 11002)
    assert access["auth_query"] == "?token=tok123"
    assert access["auth_hint"] is None


def test_a_runtime_file_for_a_dead_pid_is_ignored(tmp_path, monkeypatch):
    """Jupyter leaves its runtime json behind when it dies. A stale file would otherwise
    produce a confident link to nothing."""
    dead = 999_999
    while os.path.exists(f"/proc/{dead}"):
        dead += 1
    d = _write_runtime(tmp_path, dead, 11002)
    monkeypatch.setattr(endpoints, "JUPYTER_RUNTIME_DIRS", (str(d),))
    assert endpoints.jupyter_servers() == {}
    access = endpoints.describe("jupyter", 11002)
    assert access["auth_query"] is None
    assert "jupyter lab list" in access["auth_hint"]


def test_no_credential_yields_a_hint_not_a_broken_link(tmp_path, monkeypatch):
    d = _write_runtime(tmp_path, os.getpid(), 11002, token=None)
    monkeypatch.setattr(endpoints, "JUPYTER_RUNTIME_DIRS", (str(d),))
    access = endpoints.describe("jupyter", 11002)
    assert access["auth_query"] is None
    assert access["auth_hint"], "a service we cannot authenticate must say how to get in"


def test_corrupt_runtime_file_is_skipped(tmp_path, monkeypatch):
    d = tmp_path / "runtime"
    d.mkdir()
    (d / "jpserver-1.json").write_text("{ not json")
    monkeypatch.setattr(endpoints, "JUPYTER_RUNTIME_DIRS", (str(d),))
    assert endpoints.jupyter_servers() == {}


def test_openai_services_expose_a_base_url_path():
    """base_url is a PATH. Composing a full URL server-side produced "…/docs/v1" — the
    server does not know the origin the viewer used."""
    access = endpoints.describe("vllm", 8010, ["qwen3.6-35b"])
    assert access["base_url"] == "/v1"
    assert access["path"] == "/docs", "the browsable page is the docs page, not /v1"
    assert access["auth_query"] is None, "a local vLLM needs no token"


def test_hermes_explains_its_401_rather_than_looking_broken():
    access = endpoints.describe("hermes", 41375)
    assert "401" in access["auth_hint"]
    assert access["auth_query"] is None


def test_ssh_is_not_presented_as_a_web_service():
    assert "SSH client" in endpoints.describe("ssh", 22)["auth_hint"]


def test_unknown_kind_yields_a_plain_root_path():
    access = endpoints.describe("http", 9000)
    assert access == {"auth_query": None, "auth_hint": None, "base_url": None, "path": "/"}


def test_tunnel_command_is_correct_and_copyable():
    assert endpoints.tunnel_command(8888, "dgx") == "ssh -N -L 8888:127.0.0.1:8888 dgx"
