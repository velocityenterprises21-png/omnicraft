"""Per-user WebSocket hub for live job progress."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("omnicraft.ws")


class ConnectionHub:
    def __init__(self) -> None:
        self._peers: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._peers[user_id].add(ws)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._peers[user_id].discard(ws)
            if not self._peers[user_id]:
                self._peers.pop(user_id, None)

    async def publish(self, user_id: str, message: dict[str, Any]) -> None:
        peers = list(self._peers.get(user_id, ()))
        if not peers:
            return
        payload = json.dumps(message, default=str)
        dead = []
        for ws in peers:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for user_id in list(self._peers.keys()):
            await self.publish(user_id, message)

    @property
    def connection_count(self) -> int:
        return sum(len(v) for v in self._peers.values())


hub = ConnectionHub()
