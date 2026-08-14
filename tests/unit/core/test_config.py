from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_settings(secret_key: str) -> Settings:
    return Settings(
        ENVIRONMENT="production",
        SECRET_KEY=secret_key,
        FIRST_SUPERUSER_PASSWORD="TestPassword123!",
    )


def test_production_rejects_a_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        _production_settings("short-secret")


def test_production_accepts_a_32_byte_jwt_secret() -> None:
    settings = _production_settings("a" * 32)

    assert settings.SECRET_KEY == "a" * 32
