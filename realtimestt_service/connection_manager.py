import asyncio
import json
import logging
from typing import Mapping

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, logger: logging.Logger | None = None):
        self.rooms: dict[str, set[WebSocket]] = {}
        self.lock = asyncio.Lock()
        self.logger = logger or logging.getLogger(__name__)

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        async with self.lock:
            if session_id not in self.rooms:
                self.rooms[session_id] = set()
            self.rooms[session_id].add(ws)
            self.logger.info(
                "Client joined session %s. Total: %s",
                session_id,
                len(self.rooms[session_id]),
            )

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        async with self.lock:
            if session_id in self.rooms:
                self.rooms[session_id].discard(ws)
                if not self.rooms[session_id]:
                    del self.rooms[session_id]
        self.logger.info("Client left session %s.", session_id)

    async def broadcast(self, event: Mapping[str, object]) -> None:
        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return

        async with self.lock:
            target_sockets = list(self.rooms.get(session_id, ()))

        if not target_sockets:
            return

        message = json.dumps(event)
        dead_sockets = []
        for ws in target_sockets:
            try:
                await ws.send_text(message)
            except Exception:
                dead_sockets.append(ws)

        if dead_sockets:
            async with self.lock:
                if session_id in self.rooms:
                    for ws in dead_sockets:
                        self.rooms[session_id].discard(ws)
                    if not self.rooms[session_id]:
                        del self.rooms[session_id]
