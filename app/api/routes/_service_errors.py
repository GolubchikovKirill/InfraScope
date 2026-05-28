from __future__ import annotations

from fastapi import HTTPException


class ServiceError(Exception):
    status_code: int = 502

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ServiceValidationError(ServiceError):
    status_code = 400


class ServiceTimeoutError(ServiceError):
    status_code = 504


class ServiceIntegrationError(ServiceError):
    status_code = 502


def to_http_error(exc: Exception, *, operation: str) -> HTTPException:
    if isinstance(exc, ServiceError):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=f"Не удалось {operation}: {exc}")
