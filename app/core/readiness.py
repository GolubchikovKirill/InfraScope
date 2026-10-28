from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session

logger = logging.getLogger(__name__)


def check_database(engine) -> bool:
    try:
        with Session(engine) as session:
            session.execute(text("SELECT 1")).one()
    except Exception as exc:
        logger.warning("Readiness: database check failed: %s", exc)
        return False
    else:
        return True


async def check_redis(get_redis) -> bool:
    try:
        redis = await get_redis()
        await redis.ping()
    except Exception as exc:
        logger.warning("Readiness: redis check failed: %s", exc)
        return False
    else:
        return True


def build_readiness_response(checks: dict[str, bool]) -> dict | JSONResponse:
    if all(checks.values()):
        return {"status": "ready", "checks": checks}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "checks": checks},
    )
