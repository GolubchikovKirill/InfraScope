import logging
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session

from app.api.main import api_router
from app.api.websockets import relay as realtime_relay
from app.core.config import settings
from app.core.db import engine, init_db
from app.core.http import request_context_headers_middleware, security_headers_middleware
from app.core.limiter import limiter
from app.core.readiness import build_readiness_response, check_database, check_redis
from app.core.redis import close_redis, get_redis
from app.observability.tracing import setup_tracing
from app.services.event_log import write_event_log

logging.basicConfig(level=logging.INFO)
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger("app")
_UNHANDLED_EXCEPTION_TTL_SECONDS = 60.0
_recent_unhandled_exceptions: dict[str, float] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _init_db_sync():
        with Session(engine) as session:
            init_db(session)

    await run_in_threadpool(_init_db_sync)
    await realtime_relay.start()
    yield
    await realtime_relay.stop()
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)
setup_tracing(app, service_name="backend")

# Expose Prometheus metrics for service monitoring and alerting.
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics", "/health"],
)
instrumentator.add(metrics.requests())
instrumentator.add(metrics.latency())
instrumentator.add(metrics.request_size())
instrumentator.add(metrics.response_size())
instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Слишком много попыток. Повторите позже.",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "request_id": getattr(request.state, "request_id", None)},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": jsonable_encoder(exc.errors()),
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    def _log_unhandled_exception():
        exception_key = f"{request.method}:{request.url.path}:{exc.__class__.__name__}:{exc}"
        now = monotonic()
        previous = _recent_unhandled_exceptions.get(exception_key)
        if previous is not None and (now - previous) < _UNHANDLED_EXCEPTION_TTL_SECONDS:
            return
        _recent_unhandled_exceptions[exception_key] = now
        try:
            with Session(engine) as session:
                write_event_log(
                    session,
                    severity="error",
                    category="system",
                    event_type="unhandled_exception",
                    message=f"{request.method} {request.url.path}: {exc}",
                )
                session.commit()
        except Exception:
            # Never fail the exception handler itself.
            logger.exception("Failed to persist unhandled exception")

    await run_in_threadpool(_log_unhandled_exception)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": getattr(request.state, "request_id", None)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.BACKEND_TRUSTED_HOSTS)
app.middleware("http")(request_context_headers_middleware)
if settings.ENABLE_SECURITY_HEADERS:
    app.middleware("http")(security_headers_middleware)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check():
    """Readiness probe for orchestrators and load balancers."""
    checks = {
        "database": check_database(engine),
        "redis": await check_redis(get_redis),
    }
    return build_readiness_response(checks)
