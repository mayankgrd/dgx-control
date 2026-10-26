"""Docker root size without root (SDD-173).

`du` on /var/lib/docker fails for any non-root user, but the Docker API already reports the same
totals. Asking for privilege to learn something available without it would violate R17.5.
"""

from __future__ import annotations

from dgxctl.collectors import disk as disk_mod
from dgxctl.collectors.base import CommandError
from dgxctl.collectors.disk import DiskCollector


class FakeDocker:
    def info(self):
        return {"DockerRootDir": "/var/lib/docker"}

    def df(self):
        return {
            "Images": [{"Size": 100, "Containers": 1}, {"Size": 50, "Containers": 0}],
            "Containers": [{"SizeRw": 7}],
            "Volumes": [{"UsageData": {"Size": 20}}],
            "BuildCache": [{"Size": 30}],
        }


def denied(path):
    raise CommandError(f"du exited 1: du: cannot read directory '{path}': Permission denied")


def setup(monkeypatch, tmp_path, du=denied):
    monkeypatch.setattr(disk_mod, "get_client", lambda: FakeDocker())
    monkeypatch.setattr(disk_mod.Path, "exists", lambda self: True)
    c = DiskCollector(roots=[str(tmp_path / "other")])
    monkeypatch.setattr(c, "_du", du)
    return c


def by_path(section, path):
    return next(r for r in section.sized_roots if r.path == path)


def test_unreadable_docker_root_uses_the_docker_api_total(monkeypatch, tmp_path):
    section = setup(monkeypatch, tmp_path)._collect_sync()
    root = by_path(section, "/var/lib/docker")
    assert root.error is None, "permission denied should not surface when the API has the answer"
    assert root.size_bytes == 100 + 50 + 7 + 20 + 30


def test_the_fallback_is_labelled(monkeypatch, tmp_path):
    root = by_path(setup(monkeypatch, tmp_path)._collect_sync(), "/var/lib/docker")
    assert root.source == "docker-api"
    assert root.note and "Docker API" in root.note


def test_other_unreadable_roots_still_report_their_error(monkeypatch, tmp_path):
    section = setup(monkeypatch, tmp_path)._collect_sync()
    other = by_path(section, str(tmp_path / "other"))
    assert other.error == "permission denied"
    assert other.size_bytes is None


def test_a_readable_docker_root_still_uses_du(monkeypatch, tmp_path):
    section = setup(monkeypatch, tmp_path, du=lambda p: 12345)._collect_sync()
    root = by_path(section, "/var/lib/docker")
    assert root.size_bytes == 12345 and root.source == "du"


def test_a_long_path_does_not_truncate_away_the_reason():
    """Found by the test above: cutting at 120 characters from the front dropped
    "Permission denied" whenever the path was long."""
    from dgxctl.collectors.disk import short_error

    long_path = "/home/user/" + "x" * 200
    msg = f"du exited 1: du: cannot read directory '{long_path}': Permission denied"
    assert short_error(CommandError(msg)) == "permission denied"
    other = short_error(CommandError("du exited 1: " + "y" * 300 + " No such file or directory"))
    assert other.endswith("No such file or directory") and len(other) <= 120
