"""Registering with NVIDIA Sync (SDD-105). This writes another application's config file,
so every test here is about not damaging it."""

from __future__ import annotations

import json

import pytest

from dgxctl.nvidia_sync import SyncError, read_entries, register, unregister

# The real shape, captured from a live DGX Spark.
EXISTING = [
    {
        "id": "1465486800000190732214fe75c988ccc82",
        "port": "1234",
        "name": "lmstudio",
        "scriptContent": "",
        "autoOpen": True,
        "url": "http://localhost:1234/",
        "interactive": False,
        "shown": True,
    }
]


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "custom.json"
    p.write_text(json.dumps(EXISTING))
    return p


def test_register_preserves_entries_it_did_not_create(cfg):
    register("DGX Control", 8770, path=cfg)
    names = [e["name"] for e in json.loads(cfg.read_text())]
    assert "lmstudio" in names, "someone else's tool must survive registration"
    assert "DGX Control" in names


def test_registered_entry_matches_syncs_own_shape(cfg):
    entry, _ = register("DGX Control", 8770, path=cfg)
    assert set(entry) == set(EXISTING[0]), "field set must match what Sync writes itself"
    assert entry["url"] == "http://localhost:8770/"
    assert entry["port"] == "8770", "Sync stores the port as a string"
    assert isinstance(entry["id"], str) and len(entry["id"]) > 20


def test_register_is_idempotent_by_name(cfg):
    first, _ = register("DGX Control", 8770, path=cfg)
    second, _ = register("DGX Control", 9999, path=cfg)
    entries = json.loads(cfg.read_text())
    assert len([e for e in entries if e["name"] == "DGX Control"]) == 1
    assert second["id"] == first["id"], "re-registering must not churn the id"
    assert second["port"] == "9999"


def test_a_backup_is_written_before_any_modification(cfg):
    _, backup = register("DGX Control", 8770, path=cfg)
    assert backup.exists()
    assert json.loads(backup.read_text()) == EXISTING


def test_url_path_is_honoured(cfg):
    entry, _ = register("DGX Control", 8770, url_path="/gpu", path=cfg)
    assert entry["url"] == "http://localhost:8770/gpu"
    entry, _ = register("Other", 8771, url_path="gpu", path=cfg)
    assert entry["url"] == "http://localhost:8771/gpu", "a missing leading slash is tolerated"


def test_unregister_removes_only_the_named_entry(cfg):
    register("DGX Control", 8770, path=cfg)
    removed, _ = unregister("DGX Control", path=cfg)
    assert removed
    assert [e["name"] for e in json.loads(cfg.read_text())] == ["lmstudio"]


def test_unregister_reports_a_miss_without_writing(cfg):
    before = cfg.read_text()
    removed, backup = unregister("nothing-here", path=cfg)
    assert removed is False and backup is None
    assert cfg.read_text() == before


def test_missing_config_is_reported_never_created(tmp_path):
    """Sync not installed: say so, and do not fabricate its config file."""
    missing = tmp_path / "custom.json"
    with pytest.raises(SyncError, match="not found"):
        read_entries(missing)
    with pytest.raises(SyncError):
        register("DGX Control", 8770, path=missing)
    assert not missing.exists()


def test_malformed_config_is_refused_without_writing(tmp_path):
    """Never clobber a file we could not parse — it is not ours to rewrite."""
    bad = tmp_path / "custom.json"
    bad.write_text("{ this is not json")
    with pytest.raises(SyncError, match="not valid JSON"):
        register("DGX Control", 8770, path=bad)
    assert bad.read_text() == "{ this is not json"


def test_non_array_config_is_refused(tmp_path):
    bad = tmp_path / "custom.json"
    bad.write_text('{"tools": []}')
    with pytest.raises(SyncError, match="JSON array"):
        register("DGX Control", 8770, path=bad)


def test_empty_config_file_is_usable(tmp_path):
    empty = tmp_path / "custom.json"
    empty.write_text("")
    entry, _ = register("DGX Control", 8770, path=empty)
    assert entry["name"] == "DGX Control"


def test_registration_is_never_triggered_by_starting_the_server():
    """Spec R13.2: explicit only. The server must not import or call this on startup."""
    import inspect

    from dgxctl import main

    source = inspect.getsource(main)
    assert "nvidia_sync" not in source, "the app factory must not touch NVIDIA Sync's config"
