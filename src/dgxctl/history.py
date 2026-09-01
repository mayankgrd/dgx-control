"""Bounded SQLite time series. Every connection gets WAL + busy_timeout."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    ts REAL NOT NULL, node TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_lookup ON metrics(node, metric, ts);
"""


def connect(path: Path) -> sqlite3.Connection:
    # check_same_thread=False because reads are dispatched via asyncio.to_thread; every
    # access is serialised by HistoryStore._lock, and WAL handles the rest.
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    return conn


class HistoryStore:
    def __init__(self, path: Path, window_minutes: int = 60, max_bytes: int = 64 * 1024 * 1024):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.window_seconds = window_minutes * 60
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._conn = connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)

    def record(self, metric: str, value: float, node: str = "local", ts: float | None = None):
        with self._lock:
            self._record(metric, value, node, ts)

    def _record(self, metric: str, value: float, node: str = "local", ts: float | None = None):
        self._conn.execute(
            "INSERT INTO metrics(ts, node, metric, value) VALUES (?,?,?,?)",
            (ts if ts is not None else time.time(), node, metric, float(value)),
        )
        self._conn.commit()

    def record_many(self, items: dict[str, float], node: str = "local", ts: float | None = None):
        now = ts if ts is not None else time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO metrics(ts, node, metric, value) VALUES (?,?,?,?)",
                [(now, node, k, float(v)) for k, v in items.items() if v is not None],
            )
            self._conn.commit()

    def series(self, metric: str, window_seconds: float | None = None, node: str = "local"):
        cutoff = time.time() - (window_seconds or self.window_seconds)
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, value FROM metrics WHERE node=? AND metric=? AND ts>=? ORDER BY ts",
                (node, metric, cutoff),
            ).fetchall()
        return [{"ts": r[0], "value": r[1]} for r in rows]

    def prune(self) -> int:
        with self._lock:
            return self._prune()

    def _prune(self) -> int:
        cutoff = time.time() - self.window_seconds
        cur = self._conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        self._conn.commit()
        deleted = cur.rowcount or 0
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            # Over ceiling: drop the oldest half of what remains, then reclaim.
            self._conn.execute(
                "DELETE FROM metrics WHERE rowid IN "
                "(SELECT rowid FROM metrics ORDER BY ts LIMIT (SELECT COUNT(*)/2 FROM metrics))"
            )
            self._conn.commit()
            self._conn.execute("PRAGMA incremental_vacuum")
            self._conn.commit()
        return deleted

    def close(self) -> None:
        with self._lock:
            self._conn.close()
