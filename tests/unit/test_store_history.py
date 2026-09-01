from __future__ import annotations

import time

from dgxctl.history import HistoryStore
from dgxctl.schemas import Envelope, NodeInfo, Status
from dgxctl.store import SnapshotStore


def node() -> NodeInfo:
    return NodeInfo(id="local", name="local")


async def test_reads_are_last_known_never_recollect():
    store = SnapshotStore(node())
    await store.put("gpu", Envelope(status=Status.ok, data={"x": 1}))
    assert store.snapshot().sections["gpu"].data == {"x": 1}
    assert store.section("gpu").data == {"x": 1}


async def test_subscriber_drops_oldest_and_never_blocks_writer():
    store = SnapshotStore(node())
    async with store.subscribe() as q:
        for i in range(50):  # a subscriber that never drains
            await store.put("gpu", Envelope(data={"i": i}))
        assert q.qsize() == 1
        version = await q.get()
        assert version == store.version, "the newest version survives, not a backlog"


async def test_subscriber_removed_on_exit():
    store = SnapshotStore(node())
    async with store.subscribe():
        assert store.subscriber_count == 1
    assert store.subscriber_count == 0


async def test_multi_node_sections_are_isolated():
    store = SnapshotStore(node())
    remote = NodeInfo(id="spark-2", name="spark-2", kind="remote")
    await store.put_node(remote)
    await store.put("gpu", Envelope(data={"host": "local"}))
    await store.put_many({"gpu": Envelope(data={"host": "remote"})}, node_id="spark-2")
    assert store.snapshot().sections["gpu"].data == {"host": "local"}
    assert store.snapshot("spark-2").sections["gpu"].data == {"host": "remote"}
    assert {n.id for n in store.nodes()} == {"local", "spark-2"}


def test_history_applies_pragmas_on_every_connection(tmp_path):
    h = HistoryStore(tmp_path / "h.db")
    mode = h._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    assert h._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    h.close()


def test_history_prune_respects_retention(tmp_path):
    h = HistoryStore(tmp_path / "h.db", window_minutes=1)
    now = time.time()
    h.record("gpu.utilization", 10, ts=now - 3600)  # outside the window
    h.record("gpu.utilization", 20, ts=now)
    assert h.prune() == 1
    series = h.series("gpu.utilization")
    assert [p["value"] for p in series] == [20]
    h.close()


def test_history_enforces_size_ceiling(tmp_path):
    h = HistoryStore(tmp_path / "h.db", window_minutes=600, max_bytes=32 * 1024)
    now = time.time()
    for i in range(4000):
        h.record("m", float(i), ts=now - i)
    before = (tmp_path / "h.db").stat().st_size
    h.prune()
    rows = h._conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    assert rows < 4000, f"ceiling not enforced (size was {before})"
    h.close()


def test_each_test_gets_its_own_database_file(tmp_path):
    """`:memory:?cache=shared` would be ONE process-wide DB. Unique files, always."""
    a = HistoryStore(tmp_path / "a.db")
    b = HistoryStore(tmp_path / "b.db")
    a.record("m", 1.0)
    assert a.series("m") and not b.series("m")
    a.close()
    b.close()
