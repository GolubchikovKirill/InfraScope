from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

IntegrationErrorKind = Literal["validation", "integration", "timeout", "config", "unknown"] | None


@dataclass(frozen=True)
class IntegrationServiceResult:
    target: Literal["duty_free", "duty_paid"] | None
    ok: bool
    message: str
    status_code: int | None = None
    request_id: str | None = None
    payload: dict[str, Any] | None = None
    error_kind: IntegrationErrorKind = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
