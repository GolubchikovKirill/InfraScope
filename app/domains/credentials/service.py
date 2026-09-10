"""Credential vault CRUD and the password generator.

No external systems here - just the `credential` table and a pure generator
function. The generator is the source of truth for the "Пароли" tab; the
frontend has a mirror of the same logic for an instant preview.
"""

from __future__ import annotations

import math
import secrets
import string
import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.domains.credentials.models import Credential
from app.domains.credentials.schemas import (
    CredentialCreate,
    CredentialUpdate,
    PasswordGenerateRequest,
)
from app.services.event_log import write_event_log

# no quotes, backslash, space or pipe: those are the characters that turn a
# pasted password into a shell/TOML/CSV quoting bug (same reasoning as
# remote_access.service._PW_ALPHABET, which drops symbols entirely).
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/"
# visually confusable in most fonts
AMBIGUOUS = "Il1O0o5S2Z8B"

_CLASSES = (
    ("uppercase", string.ascii_uppercase),
    ("lowercase", string.ascii_lowercase),
    ("digits", string.digits),
    ("symbols", SYMBOLS),
)


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# password generator                                                         #
# --------------------------------------------------------------------------- #
def generate_password(req: PasswordGenerateRequest) -> tuple[str, float]:
    """Return (password, entropy_bits) or raise ValueError on impossible options."""
    banned = set(req.exclude_chars)
    if req.exclude_ambiguous:
        banned |= set(AMBIGUOUS)

    pools: list[str] = []
    for name, chars in _CLASSES:
        if not getattr(req, name):
            continue
        pool = [c for c in chars if c not in banned]
        if pool:
            pools.append("".join(pool))

    if not pools:
        raise ValueError("no character classes available after applying exclusions")
    if req.min_of_each and req.length < len(pools):
        raise ValueError(
            f"length {req.length} is too short to include one of each of the "
            f"{len(pools)} selected character classes"
        )

    combined = "".join(pools)
    rng = secrets.SystemRandom()

    if req.min_of_each:
        chars = [secrets.choice(pool) for pool in pools]
        chars += [secrets.choice(combined) for _ in range(req.length - len(pools))]
        rng.shuffle(chars)
    else:
        chars = [secrets.choice(combined) for _ in range(req.length)]

    password = "".join(chars)
    entropy_bits = req.length * math.log2(len(combined))
    return password, entropy_bits


def default_password(length: int = 20) -> str:
    password, _ = generate_password(PasswordGenerateRequest(length=length))
    return password


# --------------------------------------------------------------------------- #
# CRUD                                                                        #
# --------------------------------------------------------------------------- #
def list_credentials(
    session: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    location: str | None = None,
    skip: int = 0,
    limit: int = 500,
) -> tuple[list[Credential], int]:
    stmt = select(Credential)
    count_stmt = select(func.count()).select_from(Credential)
    if q:
        like = f"%{q.strip()}%"
        cond = (
            Credential.title.ilike(like)  # type: ignore[attr-defined]
            | Credential.host.ilike(like)  # type: ignore[attr-defined]
            | Credential.username.ilike(like)  # type: ignore[attr-defined]
            | Credential.tags.ilike(like)  # type: ignore[attr-defined]
        )
        stmt, count_stmt = stmt.where(cond), count_stmt.where(cond)
    if category:
        stmt, count_stmt = stmt.where(Credential.category == category), count_stmt.where(
            Credential.category == category
        )
    if location:
        stmt, count_stmt = stmt.where(Credential.location == location), count_stmt.where(
            Credential.location == location
        )
    rows = session.exec(
        stmt.order_by(Credential.title).offset(skip).limit(limit)
    ).all()
    return list(rows), session.exec(count_stmt).one()


def create_credential(
    session: Session, payload: CredentialCreate, *, user_id: uuid.UUID | None
) -> Credential:
    cred = Credential(
        title=payload.title,
        category=payload.category,
        username=payload.username,
        secret=payload.secret,
        host=payload.host,
        location=payload.location,
        url=payload.url,
        notes=payload.notes,
        tags=payload.tags,
        secret_rotated_at=_now(),
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


def update_credential(
    session: Session,
    cred: Credential,
    payload: CredentialUpdate,
    *,
    user_id: uuid.UUID | None,
) -> Credential:
    changes = payload.model_dump(exclude_unset=True)
    new_secret = changes.pop("secret", None)
    for field, value in changes.items():
        setattr(cred, field, value)
    if new_secret:  # blank / omitted leaves the stored secret alone
        cred.secret = new_secret
        cred.secret_rotated_at = _now()
    cred.updated_by_id = user_id
    cred.updated_at = _now()
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


def delete_credential(session: Session, cred: Credential) -> None:
    session.delete(cred)
    session.commit()


def reveal_secret(session: Session, cred: Credential, *, actor: str) -> None:
    """Audit that `actor` looked at this secret. Caller reads cred.secret itself."""
    write_event_log(
        session,
        event_type="credential.revealed",
        category="credentials",
        severity="info",
        message=f"{actor}: раскрыт секрет «{cred.title}»",
        device_name=cred.host or None,
    )
    session.commit()
