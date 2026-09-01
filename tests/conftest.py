from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Never touch the real home during tests.

    HOME is redirected too, not just the dgxctl dirs. Onboarding writes a symlink into
    ~/.local/bin and can append to shell files; a test that ran against the real home once
    repointed a developer's `dgxctl` at an ephemeral uv build venv and left it dangling.
    Tests do not get to modify the machine they run on.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("DGXCTL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DGXCTL_STATE_DIR", str(tmp_path / "state"))
    for k in list(os.environ):
        if k.startswith("DGXCTL_") and k not in ("DGXCTL_CONFIG_DIR", "DGXCTL_STATE_DIR"):
            monkeypatch.delenv(k, raising=False)
    yield
