from __future__ import annotations

import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "TestPassword123!")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-bytes")
# TestClient talks to host "testserver", which the settings default allows but a
# real .env sitting in the repo root does not - without this every request dies
# in TrustedHostMiddleware as "Invalid host header", surfacing as a confusing
# HTTP 400 from the login fixture rather than anything about hosts.
os.environ.setdefault("BACKEND_TRUSTED_HOSTS", '["testserver","localhost","127.0.0.1"]')
# The repo-root .env is a developer's real config (Kafka, tracing, ...). Left
# to pydantic-settings it leaks into the suite: KAFKA_ENABLED=true made every
# poll test block on a real broker connection and OTEL_ENABLED=true kept an
# exporter thread retrying against a collector that isn't there. Real env vars
# outrank .env, so pin the external integrations off here.
os.environ.setdefault("KAFKA_ENABLED", "false")
os.environ.setdefault("OTEL_ENABLED", "false")
# Likewise the internal-service switches: with the developer's .env they send
# poll/discovery requests to http://polling-service:8011 & co., which do not
# exist here (-> 504 after a connect timeout). Tests that cover the proxied
# path opt in per test via monkeypatch.
os.environ.setdefault("POLLING_SERVICE_ENABLED", "false")
os.environ.setdefault("DISCOVERY_SERVICE_ENABLED", "false")
os.environ.setdefault("NETWORK_CONTROL_SERVICE_ENABLED", "false")
os.environ.setdefault("MEDIA_SERVICE_ENABLED", "false")

from app.api import deps
from app.core.limiter import limiter as app_limiter
from app.core.security import get_password_hash
from app.main import app
from app.models import User

TEST_DB_DIR = Path(tempfile.gettempdir()) / f"infrascope-test-db-{uuid4().hex}"
TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_PATH = TEST_DB_DIR / "test_infrascope.db"
# CI (and anyone who wants production parity) points TEST_DATABASE_URL at a
# throwaway PostgreSQL; everything else keeps the fast, zero-setup SQLite file.
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{TEST_DB_PATH}"
_IS_SQLITE = TEST_DB_URL.startswith("sqlite")
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False} if _IS_SQLITE else {})


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Settings a developer's real .env must not decide for the suite.

    An unset media client token means "no auth" for the media service, which
    its tests rely on; production .env files always set one. Set on the
    settings object rather than via the environment because an empty env var
    does not reliably beat a value coming from .env.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "MEDIA_CLIENT_TOKEN", "")
    # MAC re-discovery ping-sweeps SCAN_SUBNET (read from settings in some
    # places and straight from os.environ in others) - with the developer's
    # real subnets a single poll test spent ~17 s pinging a live network.
    monkeypatch.setattr(settings, "SCAN_SUBNET", "")
    monkeypatch.setenv("SCAN_SUBNET", "")


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    """In-memory Redis for every test.

    .env points at the compose hostname "redis", which does not exist on a dev
    machine or in CI, so every cache invalidation / realtime publish inside a
    request waited out a connect timeout (single integration tests took
    40-50 s) - and, worse, nothing ever exercised the Redis-backed locks and
    rate limits for real. fakeredis implements the commands this app uses,
    including Lua eval and pub/sub. One fresh server per test, shared between
    the async and sync clients so they see the same keys.
    """
    import fakeredis
    import fakeredis.aioredis
    import redis
    import redis.asyncio

    server = fakeredis.FakeServer()

    def _async_from_url(url, **kwargs):
        return fakeredis.aioredis.FakeRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    def _sync_from_url(cls, url, **kwargs):
        return fakeredis.FakeRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    monkeypatch.setattr(redis.asyncio, "from_url", _async_from_url)
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(_sync_from_url))
    monkeypatch.setattr("app.core.redis._pool", None, raising=False)
    yield
    monkeypatch.setattr("app.core.redis._pool", None, raising=False)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db_on_exit():
    yield
    engine.dispose()
    shutil.rmtree(TEST_DB_DIR, ignore_errors=True)


@pytest.fixture
def _clean_db():
    # Not autouse: recreating every table cost ~0.6 s per test, and most unit
    # tests never touch the database. db_session pulls this in, and every
    # DB-backed fixture (client, tokens, users) goes through db_session.
    SQLModel.metadata.drop_all(engine, checkfirst=True)
    SQLModel.metadata.create_all(engine, checkfirst=True)
    yield
    SQLModel.metadata.drop_all(engine, checkfirst=True)


@pytest.fixture
def db_session(_clean_db):
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(db_session, monkeypatch: pytest.MonkeyPatch):
    blacklisted_jtis: set[str] = set()

    async def _is_blacklisted(jti: str) -> bool:
        return jti in blacklisted_jtis

    async def _blacklist_token(jti: str, _ttl: int) -> None:
        blacklisted_jtis.add(jti)

    # get_db is overridden below, but background work and the unhandled-error
    # logger open their own Session(engine). Those must hit the test database
    # too, not the production engine (host "db"), which does not exist here.
    monkeypatch.setattr(deps, "engine", engine)
    monkeypatch.setattr("app.main.engine", engine)

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
