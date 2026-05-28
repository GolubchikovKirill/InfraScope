import uuid as _uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

ALGORITHM = "HS256"

_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    type=Type.ID,
)


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "jti": str(_uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str | int) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "jti": str(_uuid.uuid4()),
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    await r.setex(f"jwt:blacklist:{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str) -> bool:
    from app.core.redis import get_redis

    r = await get_redis()
    return await r.exists(f"jwt:blacklist:{jti}") > 0


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Support legacy bcrypt hashes during migration
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        import bcrypt

        if bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8")):
            return True
        return False
    try:
        return _ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Check if password hash needs upgrading (bcrypt -> argon2id)."""
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        return True
    return _ph.check_needs_rehash(hashed_password)


def get_password_hash(password: str) -> str:
    return _ph.hash(password)
