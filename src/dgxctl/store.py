"""In-memory snapshot store with drop-oldest subscriber fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dgxctl.schemas import Envelope, NodeInfo, Snapshot


class SnapshotStore:
    """Poller tasks write; request handlers read. A slow reader never blocks a writer."""

    def __init__(self, node: NodeInfo) -> None:
        self._nodes: dict[str, NodeInfo] = {node.id: node}
        self._sections: dict[str, dict[str, Envelope]] = {node.id: {}}
        self._version = 0
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[int]] = set()
        self.local_id = node.id

    @property
    def version(self) -> int:
        return self._version

    async def put(self, section: str, envelope: Envelope, node_id: str | None = None) -> None:
        node_id = node_id or self.local_id
        async with self._lock:
            self._sections.setdefault(node_id, {})[section] = envelope
            self._version += 1
            version = self._version
        self._notify(version)

    async def put_node(self, node: NodeInfo) -> None:
        async with self._lock:
            self._nodes[node.id] = node
            self._version += 1
            version = self._version
        self._notify(version)

    async def put_many(self, sections: dict[str, Envelope], node_id: str) -> None:
        async with self._lock:
            self._sections.setdefault(node_id, {}).update(sections)
            self._version += 1
            version = self._version
        self._notify(version)

    def _notify(self, version: int) -> None:
        for q in list(self._subscribers):
            if q.full():  # drop-oldest: the newest version is all that matters
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(version)
            except asyncio.QueueFull:
                pass

    def nodes(self) -> list[NodeInfo]:
        return list(self._nodes.values())

    def snapshot(self, node_id: str | None = None) -> Snapshot:
        node_id = node_id or self.local_id
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(node_id)
        return Snapshot(
            node=node, version=self._version, sections=dict(self._sections.get(node_id, {}))
        )

    def section(self, name: str, node_id: str | None = None) -> Envelope | None:
        node_id = node_id or self.local_id
        return self._sections.get(node_id, {}).get(name)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[int]]:
        q: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
