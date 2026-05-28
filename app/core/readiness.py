from __future__ import annotations

from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import Session


def check_database(engine) -> bool:
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).one()
        return True
    except Exception:
        return False


async def check_redis(get_redis) -> bool:
    try:
        redis = await get_redis()
        await redis.ping()
        return True
    except Exception:
        return False


def build_readiness_response(checks: dict[str, bool]) -> dict | JSONResponse:
    if all(checks.values()):
        return {"status": "ready", "checks": checks}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "checks": checks},
    )
