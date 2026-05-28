from __future__ import annotations

import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "TestPassword123!")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

from app.api import deps
from app.core.limiter import limiter as app_limiter
from app.core.security import get_password_hash
from app.main import app
from app.models import User

TEST_DB_PATH = Path(tempfile.gettempdir()) / "test_infrascope.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture(autouse=True)
def _clean_db():
    SQLModel.metadata.drop_all(engine, checkfirst=True)
    SQLModel.metadata.create_all(engine, checkfirst=True)
    yield
    SQLModel.metadata.drop_all(engine, checkfirst=True)


@pytest.fixture
def db_session():
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db_session, monkeypatch: pytest.MonkeyPatch):
    blacklisted_jtis: set[str] = set()

    async def _is_blacklisted(jti: str) -> bool:
        return jti in blacklisted_jtis

    async def _blacklist_token(jti: str, _ttl: int) -> None:
        blacklisted_jtis.add(jti)

    monkeypatch.setattr(deps, "is_token_blacklisted", _is_blacklisted)
    from app.api.routes import auth as auth_routes

    monkeypatch.setattr(auth_routes, "blacklist_token", _blacklist_token)
    monkeypatch.setattr(auth_routes, "is_token_blacklisted", _is_blacklisted)

    def _fake_check_request_limit(request, _endpoint, _in_middleware=True):
        request.state.view_rate_limit = None
        return None

    monkeypatch.setattr(app_limiter, "_check_request_limit", _fake_check_request_limit)

    def override_get_db():
        yield db_session

    app.dependency_overrides[deps.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db_session):
    user = User(
        email="admin@example.com",
        hashed_password=get_password_hash("Pass1234"),
        full_name="Admin",
        is_superuser=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def regular_user(db_session):
    user = User(
        email="user@example.com",
        hashed_password=get_password_hash("Pass1234"),
        full_name="User",
        is_superuser=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_token(client: TestClient, admin_user: User):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Pass1234"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def user_token(client: TestClient, regular_user: User):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": "Pass1234"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]
