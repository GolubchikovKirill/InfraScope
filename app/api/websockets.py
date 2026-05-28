import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        text_data = json.dumps(message)
        async with self.lock:
            subs = list(self.active_connections)
        for connection in subs:
            try:
                await connection.send_text(text_data)
            except Exception as e:
                logger.debug("WebSocket send error: %s", e)
                await self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
        await manager.disconnect(websocket)


async def broadcast_event(event_type: str, item_id: str, payload: dict | None = None):
    """
    Called by background tasks and endpoints to push real-time updates to clients.
    event_type examples: "printer_updated", "switch_updated", "cash_register_updated", "computer_updated"
    """
    message = {"event": event_type, "id": item_id, "payload": payload or {}}
    await manager.broadcast(message)
