"""Credential vault - stored infrastructure logins + a password generator.

Superuser-only end to end (list included): the tab holds plaintext-equivalent
secrets and there is no per-entry ACL. Every secret reveal is written to the
event log with the operator's identity.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.api.routes._service_errors import not_found
from app.domains.credentials import service
from app.domains.credentials.models import Credential
from app.domains.credentials.schemas import (
    CredentialCreate,
    CredentialPublic,
    CredentialSecret,
    CredentialsPublic,
    CredentialUpdate,
    PasswordGenerateRequest,
    PasswordGenerateResponse,
)
from app.domains.shared.schemas import Message

router = APIRouter(tags=["credentials"], dependencies=[Depends(get_current_active_superuser)])


def _to_public(cred: Credential) -> CredentialPublic:
    data = CredentialPublic.model_validate(cred)
    data.has_secret = bool(cred.secret)
    return data


@router.post("/generate-password", response_model=PasswordGenerateResponse)
def generate_password(payload: PasswordGenerateRequest) -> PasswordGenerateResponse:
    try:
        password, entropy = service.generate_password(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PasswordGenerateResponse(password=password, entropy_bits=entropy)


@router.get("", response_model=CredentialsPublic)
def list_credentials(
    session: SessionDep,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    location: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> CredentialsPublic:
    rows, count = service.list_credentials(
        session, q=q, category=category, location=location, skip=skip, limit=limit
    )
    return CredentialsPublic(data=[_to_public(r) for r in rows], count=count)


@router.post("", response_model=CredentialPublic)
def create_credential(
    payload: CredentialCreate, session: SessionDep, current_user: CurrentUser
) -> CredentialPublic:
    cred = service.create_credential(session, payload, user_id=current_user.id)
    return _to_public(cred)


@router.get("/{credential_id}", response_model=CredentialPublic)
def get_credential(credential_id: uuid.UUID, session: SessionDep) -> CredentialPublic:
    cred = session.get(Credential, credential_id)
    if not cred:
        raise not_found("Credential not found")
    return _to_public(cred)


@router.patch("/{credential_id}", response_model=CredentialPublic)
def update_credential(
    credential_id: uuid.UUID,
    payload: CredentialUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> CredentialPublic:
    cred = session.get(Credential, credential_id)
    if not cred:
        raise not_found("Credential not found")
    cred = service.update_credential(session, cred, payload, user_id=current_user.id)
    return _to_public(cred)


@router.delete("/{credential_id}", response_model=Message)
def delete_credential(credential_id: uuid.UUID, session: SessionDep) -> Message:
    cred = session.get(Credential, credential_id)
    if not cred:
        raise not_found("Credential not found")
    title = cred.title
    service.delete_credential(session, cred)
    return Message(message=f"«{title}»: удалено")


@router.post("/{credential_id}/reveal", response_model=CredentialSecret)
def reveal_credential(
    credential_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> CredentialSecret:
    cred = session.get(Credential, credential_id)
    if not cred:
        raise not_found("Credential not found")
    # read the decrypted values before the audit-log commit expires the row
    payload = CredentialSecret(id=cred.id, secret=cred.secret, notes=cred.notes)
    service.reveal_secret(session, cred, actor=current_user.email or str(current_user.id))
    return payload
