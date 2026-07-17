import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter()

REALTIME_CHANNEL = "infrascope:realtime"


class ConnectionManager:
    """Fans local realtime events out to WebSocket clients on this process only.

    Cross-process delivery (multiple uvicorn workers, or events published by
    other services such as polling-service) is handled by RedisRelay below,
    which republishes into this manager after receiving from Redis Pub/Sub.
    """

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

    async def broadcast_local(self, message: dict):
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


class RedisRelay:
    """Subscribes to the shared Redis channel and fans messages into this
    process's ConnectionManager. Runs as a background task on backend lifespan.
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def start(self):
        self._stopped = False
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self):
        backoff = 1.0
        while not self._stopped:
            try:
                redis = await get_redis()
                pubsub = redis.pubsub()
                await pubsub.subscribe(REALTIME_CHANNEL)
                backoff = 1.0
                async for message in pubsub.listen():
                    if self._stopped:
                        break
                    if message.get("type") != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                    except (TypeError, ValueError):
                        continue
                    await manager.broadcast_local(data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Realtime Redis relay error, retrying: %s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


relay = RedisRelay()


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

    Publishes to Redis so the event reaches every backend worker/process
    (including polling-service, which runs as a separate container) rather
    than only the in-process ConnectionManager.
    """
    message = {"event": event_type, "id": item_id, "payload": payload or {}}
    try:
        redis = await get_redis()
        await redis.publish(REALTIME_CHANNEL, json.dumps(message))
    except Exception as exc:
        logger.warning("Realtime broadcast publish failed: %s", exc)
