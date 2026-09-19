"""Credential vault API: superuser-only, audited reveal, password generator."""

from sqlmodel import select

from app.domains.credentials.models import Credential
from app.domains.operations.models import EventLog

BASE = "/api/v1/credentials"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make(client, token, **over):
    payload = {
        "title": "Switch VNA core",
        "category": "switch",
        "username": "admin",
        "secret": "s3cr3t-p@ss",
        "host": "10.10.1.1",
        "location": "VNA",
        **over,
    }
    resp = client.post(BASE, json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_crud_roundtrip_as_superuser(client, admin_token, db_session):
    created = _make(client, admin_token, tags="core,mikrotik")
    cid = created["id"]
    assert created["has_secret"] is True
    assert "secret" not in created  # list/detail never carry the plaintext

    listed = client.get(BASE, headers=_auth(admin_token)).json()
    assert listed["count"] == 1
    assert listed["data"][0]["id"] == cid

    patched = client.patch(
        f"{BASE}/{cid}", json={"username": "root"}, headers=_auth(admin_token)
    ).json()
    assert patched["username"] == "root"

    gone = client.delete(f"{BASE}/{cid}", headers=_auth(admin_token))
    assert gone.status_code == 200
    assert db_session.exec(select(Credential)).all() == []


def test_reveal_returns_secret_and_writes_audit_log(client, admin_token, db_session):
    cid = _make(client, admin_token, secret="reveal-me-123")["id"]

    resp = client.post(f"{BASE}/{cid}/reveal", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["secret"] == "reveal-me-123"

    events = db_session.exec(
        select(EventLog).where(EventLog.category == "credentials")
    ).all()
    assert len(events) == 1
    assert events[0].event_type == "credential.revealed"
    assert "admin@example.com" in events[0].message


def test_regular_user_is_forbidden_everywhere(client, user_token):
    h = _auth(user_token)
    assert client.get(BASE, headers=h).status_code == 403
    assert client.post(BASE, json={}, headers=h).status_code == 403
    assert client.post(f"{BASE}/generate-password", json={}, headers=h).status_code == 403
    assert (
        client.post(
            f"{BASE}/00000000-0000-0000-0000-000000000000/reveal", headers=h
        ).status_code
        == 403
    )


def test_generate_password_endpoint_respects_options(client, admin_token):
    resp = client.post(
        f"{BASE}/generate-password",
        json={"length": 32, "symbols": False, "uppercase": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    pw = body["password"]
    assert len(pw) == 32
    assert pw.islower() or pw.isalnum()  # no symbols, no uppercase
    assert not any(c.isupper() for c in pw)
    assert body["entropy_bits"] > 0


def test_generate_password_impossible_options_return_422(client, admin_token):
    resp = client.post(
        f"{BASE}/generate-password",
        json={
            "length": 12,
            "uppercase": False,
            "lowercase": False,
            "digits": False,
            "symbols": False,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422
