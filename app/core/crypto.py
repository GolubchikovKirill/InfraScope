"""Transparent at-rest encryption for sensitive columns (e.g. switch SSH passwords).

Uses Fernet (symmetric, authenticated) via SQLAlchemy's TypeDecorator so callers
keep reading/writing plain Python strings; encryption happens only at the
DB boundary. Encrypted values are tagged with a prefix so legacy plaintext
rows written before this was introduced are recognized and passed through
unchanged until the next write re-encrypts them.
"""

from __future__ import annotations

import logging

# cryptography is not a direct project dependency; it ships as a transitive
# dependency of paramiko (already pinned in uv.lock).
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logger = logging.getLogger(__name__)

_ENCRYPTED_PREFIX = "enc:v1:"


def _build_fernet() -> MultiFernet | None:
    raw = (settings.CREDENTIALS_ENCRYPTION_KEYS or "").strip()
    if not raw:
        return None
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        return None
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError):
        logger.error("CREDENTIALS_ENCRYPTION_KEYS is set but invalid; storing secrets as plaintext")
        return None


_fernet = _build_fernet()


def encrypt_secret(value: str) -> str:
    """Encrypt for storage. No-op (plaintext) if no encryption key is configured."""
    if not value or _fernet is None:
        return value
    if value.startswith(_ENCRYPTED_PREFIX):
        return value  # already encrypted (e.g. re-saving an unchanged value)
    token = _fernet.encrypt(value.encode()).decode()
    return _ENCRYPTED_PREFIX + token


def decrypt_secret(value: str) -> str:
    """Decrypt a stored value. Passes through legacy/plaintext values unchanged."""
    if not value or not value.startswith(_ENCRYPTED_PREFIX):
        return value
    if _fernet is None:
        logger.warning("Encrypted secret present but CREDENTIALS_ENCRYPTION_KEYS is not configured")
        return value
    token = value[len(_ENCRYPTED_PREFIX) :]
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt stored secret (wrong/rotated key?); returning raw value")
        return value


class EncryptedString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return decrypt_secret(value)
