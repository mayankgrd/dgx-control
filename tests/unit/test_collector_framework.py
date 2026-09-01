from __future__ import annotations

import asyncio

import pytest

from dgxctl.collectors.base import Collector, CommandError, run_cmd
from dgxctl.schemas import Status


class Boom(Collector):
    name = "boom"

    async def collect(self):
        raise RuntimeError("kaboom")


class Slow(Collector):
    name = "slow"
    timeout = 0.05

    async def collect(self):
        await asyncio.sleep(5)


class Flaky(Collector):
    name = "flaky"

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def collect(self):
        self.calls += 1
        if self.calls == 1:
            return {"value": 1}
        raise RuntimeError("now broken")


class Missing(Collector):
    name = "missing"

    def __init__(self):
        super().__init__()
        self.collected = 0

    async def available(self):
        self.mark_unavailable("no such data source here")
        return False

    async def collect(self):
        self.collected += 1
        return {}


async def test_exception_becomes_error_envelope():
    env = await Boom().run()
    assert env.status is Status.error
    assert "kaboom" in env.error


async def test_timeout_becomes_error_envelope():
    env = await asyncio.wait_for(Slow().run(), timeout=2)
    assert env.status is Status.error
    assert "timed out" in env.error


async def test_error_retains_last_good_data():
    c = Flaky()
    first = await c.run()
    assert first.status is Status.ok and first.data == {"value": 1}
    second = await c.run()
    assert second.status is Status.error
    assert second.data == {"value": 1}, "stale-but-labelled beats a blank panel"
    assert "now broken" in second.error


async def test_unavailable_never_collects_again():
    c = Missing()
    for _ in range(3):
        env = await c.run()
        assert env.status is Status.unavailable
    assert c.collected == 0


def test_run_cmd_rejects_shell_strings():
    """Spec S8: no shell string interpolation, anywhere."""
    with pytest.raises(TypeError):
        run_cmd("echo hello")  # type: ignore[arg-type]


def test_run_cmd_reports_missing_binary():
    with pytest.raises(CommandError, match="not found"):
        run_cmd(["definitely-not-a-real-binary-xyz"])


def test_run_cmd_reports_nonzero_exit():
    with pytest.raises(CommandError, match="exited"):
        run_cmd(["sh", "-c", "exit 3"])


# --- regressions found on real hardware (SDD-053 live verification) ------------


def test_sdd053_container_with_a_deleted_image_does_not_fail_the_collector():
    """Live regression: `container.image` raises ImageNotFound when the image is gone.

    `getattr(c, "image", None)` does NOT protect against this — the default applies only
    to AttributeError, never to a property that raises.
    """
    from dgxctl.collectors.containers import _image_name, safe_image

    class Raising:
        @property
        def image(self):
            raise RuntimeError("404 Client Error: ImageNotFound")

    assert safe_image(Raising()) is None
    assert _image_name(Raising(), {"Image": "sha256:abc"}) == "sha256:abc"
    assert _image_name(Raising(), {}) == "?"


def test_sdd053_unreadable_directory_does_not_fail_the_pyenv_walk(tmp_path):
    """Live regression: is_dir() raises PermissionError on unreadable dirs under $HOME."""
    import os

    from dgxctl.collectors.pyenvs import PyEnvCollector

    good = tmp_path / "venv"
    (good / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    (good / "pyvenv.cfg").write_text("version = 3.12.3\n")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inner").mkdir()
    os.chmod(blocked, 0o000)
    try:
        found: list = []
        PyEnvCollector(roots=[str(tmp_path)])._walk(tmp_path, 0, found)
        assert good in found, "the readable env must still be discovered"
    finally:
        os.chmod(blocked, 0o755)
