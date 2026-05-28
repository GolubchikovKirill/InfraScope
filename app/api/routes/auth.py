import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app import crud
from app.api.deps import CurrentUser, SessionDep, TokenDep
from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import (
    ALGORITHM,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    is_token_blacklisted,
)
from app.domains.identity.models import User
from app.domains.identity.schemas import Token, TokenPayload, UserPublic
from app.observability.metrics import auth_events_total

router = APIRouter(tags=["auth"])


def _decode_token_payload(raw_token: str, expected_type: str) -> tuple[dict, TokenPayload]:
    payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    token_data = TokenPayload(**payload)
    if token_data.type != expected_type:
        raise HTTPException(status_code=401, detail=f"Invalid {expected_type} token")
    return payload, token_data


def _parse_subject_user_id(token_data: TokenPayload) -> uuid.UUID | None:
    if not token_data.sub:
        return None
    try:
        return uuid.UUID(token_data.sub)
    except ValueError:
        return None


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
    )


async def _blacklist_payload(payload: dict) -> None:
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    ttl = int(exp - datetime.now(UTC).timestamp())
    if ttl > 0:
        await blacklist_token(jti, ttl)


@router.post("/login")
@limiter.limit("5/minute")
def login_access_token(
    request: Request,
    response: Response,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """OAuth2 compatible token login, get an access token for future requests."""
    user: User | None = crud.authenticate(session=session, email=form_data.username, password=form_data.password)
    if not user:
        auth_events_total.labels(result="failure", reason="invalid_credentials").inc()
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        auth_events_total.labels(result="failure", reason="inactive_user").inc()
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    auth_events_total.labels(result="success", reason="login").inc()

    # pyrefly: ignore [bad-argument-type]
    refresh_token = create_refresh_token(user.id)
    _set_refresh_cookie(response, refresh_token)

    return Token(access_token=create_access_token(user.id, expires_delta=access_token_expires))


@router.post("/refresh")
async def refresh_access_token(
    request: Request,
    response: Response,
    session: SessionDep,
) -> Token:
    """Refresh access token using the refresh_token cookie."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    try:
        payload, token_data = _decode_token_payload(refresh_token, "refresh")
    except (jwt.InvalidTokenError, ValidationError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(str(jti)):
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")
    user_id = _parse_subject_user_id(token_data)

    user = session.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    await _blacklist_payload(payload)
    new_refresh_token = create_refresh_token(user.id)
    _set_refresh_cookie(response, new_refresh_token)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(access_token=create_access_token(user.id, expires_delta=access_token_expires))


@router.post("/logout")
async def logout(request: Request, response: Response, token: TokenDep) -> dict:
    """Invalidate the current access token."""
    response.delete_cookie("refresh_token", path="/")
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            refresh_payload, _ = _decode_token_payload(refresh_token, "refresh")
        except (HTTPException, jwt.InvalidTokenError, ValidationError):
            auth_events_total.labels(result="success", reason="logout_invalid_refresh").inc()
        else:
            await _blacklist_payload(refresh_payload)
    try:
        payload, _ = _decode_token_payload(token, "access")
    except (HTTPException, jwt.InvalidTokenError, ValidationError):
        auth_events_total.labels(result="success", reason="logout_invalid_token").inc()
        return {"message": "ok"}
    await _blacklist_payload(payload)
    auth_events_total.labels(result="success", reason="logout").inc()
    return {"message": "ok"}


@router.post("/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> UserPublic:
    """Test access token validity."""
    return current_user
