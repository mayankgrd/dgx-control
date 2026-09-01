from __future__ import annotations

import asyncio

from dgxctl.collectors.base import Collector
from dgxctl.collectors.containers import safe_image
from dgxctl.docker_client import get_client, get_error
from dgxctl.schemas import ImageInfo, ImageSection


class ImageCollector(Collector):
    name = "images"
    interval = 60.0
    timeout = 30.0

    async def available(self) -> bool:
        if await asyncio.to_thread(get_client) is None:
            self.mark_unavailable(f"Docker not reachable ({get_error()})")
            return False
        return True

    async def collect(self) -> dict:
        return (await asyncio.to_thread(self._collect_sync)).model_dump()

    def _collect_sync(self) -> ImageSection:
        client = get_client()
        in_use = set()
        for c in client.containers.list(all=True):
            img = c.attrs.get("Image")
            if img:
                in_use.add(img)
            image = safe_image(c)
            in_use.update(getattr(image, "tags", None) or [])
        section = ImageSection()
        for img in client.images.list(all=False):
            tags = img.tags or []
            size = img.attrs.get("Size", 0) or 0
            created = img.attrs.get("Created")
            if not tags:
                section.images.append(
                    ImageInfo(
                        id=img.id,
                        repository="<none>",
                        tag="<none>",
                        size_bytes=size,
                        created_at=created,
                        dangling=True,
                        in_use=img.id in in_use,
                    )
                )
            for t in tags:
                repo, _, tag = t.rpartition(":")
                section.images.append(
                    ImageInfo(
                        id=img.id,
                        repository=repo or t,
                        tag=tag or "latest",
                        size_bytes=size,
                        created_at=created,
                        in_use=t in in_use or img.id in in_use,
                    )
                )
        # An image's size is counted once even when it carries several tags.
        seen: set[str] = set()
        for i in section.images:
            if i.id not in seen:
                seen.add(i.id)
                section.total_bytes += i.size_bytes
        section.images.sort(key=lambda i: -i.size_bytes)
        return section
