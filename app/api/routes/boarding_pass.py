from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_active_superuser
from app.api.routes._service_errors import to_http_error
from app.domains.integrations.schemas import BoardingPassRequest
from app.services.boarding_pass import BoardingPassService

router = APIRouter(tags=["boarding-pass"])
boarding_pass_service = BoardingPassService()


@router.post("/export", dependencies=[Depends(get_current_active_superuser)])
def export_boarding_pass(payload: BoardingPassRequest) -> StreamingResponse:
    try:
        generated = boarding_pass_service.generate_file(payload)
    except Exception as exc:
        raise to_http_error(exc, operation="сформировать boarding pass") from exc

    return StreamingResponse(
        io.BytesIO(generated.content),
        media_type=generated.content_type,
        headers={"Content-Disposition": f'attachment; filename="{generated.filename}"'},
    )
