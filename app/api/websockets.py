import asyncio
import contextlib
import json
import logging
import uuid

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.redis import get_redis
from app.core.security import ALGORITHM, is_token_blacklisted
from app.domains.identity.models import User
from app.domains.identity.schemas import TokenPayload

logger = logging.getLogger(__name__)

router = APIRouter()

REALTIME_CHANNEL = "infrascope:realtime"
WS_UNAUTHORIZED_CLOSE_CODE = 4401


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


async def _authenticate_ws_token(token: str | None) -> User | None:
    """Same validation as get_current_user (app.api.deps), adapted for a
    WebSocket handshake: no request-scoped session/Depends chain available,
    and failures return None to close the socket rather than raising
    HTTPException.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        return None
    if token_data.type != "access":
        return None
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        return None
    try:
        user_id = uuid.UUID(token_data.sub) if token_data.sub else None
    except ValueError:
        return None
    if user_id is None:
        return None
    with Session(engine) as session:
        user = session.get(User, user_id)
    if not user or not user.is_active:
        return None
    return user


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)):
    # Browsers can't set a custom Authorization header on a WebSocket
    # handshake, so the access token travels as a query parameter instead.
    user = await _authenticate_ws_token(token)
    if user is None:
        await websocket.close(code=WS_UNAUTHORIZED_CLOSE_CODE)
        return

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
