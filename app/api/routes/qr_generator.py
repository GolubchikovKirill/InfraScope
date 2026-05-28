from __future__ import annotations

import datetime
import io
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_active_superuser
from app.api.routes._service_errors import ServiceTimeoutError, to_http_error
from app.core.config import settings
from app.domains.integrations.schemas import QRGeneratorRequest
from app.services.qr_generator import QrExportService, QRGeneratorParams

router = APIRouter(tags=["qr-generator"])
qr_export_service = QrExportService()


def _qr_database_for_mode(db_mode: str) -> tuple[str, str]:
    if db_mode == "duty_paid":
        return (
            settings.QR_SQL_DUTY_PAID_SERVER,
            settings.QR_SQL_DUTY_PAID_DATABASE or settings.QR_SQL_DATABASE,
        )
    return (
        settings.QR_SQL_DUTY_FREE_SERVER,
        settings.QR_SQL_DUTY_FREE_DATABASE or settings.QR_SQL_DATABASE,
    )


@router.post("/export", dependencies=[Depends(get_current_active_superuser)])
def export_qr_docs(payload: QRGeneratorRequest) -> StreamingResponse:
    both_databases = payload.db_mode == "both"
    server, database = _qr_database_for_mode(payload.db_mode)
    try:
        params = QRGeneratorParams(
            server=server,
            database=database,
            sql_login=settings.QR_SQL_LOGIN,
            sql_password=settings.QR_SQL_PASSWORD,
            airport_code=payload.airport_code,
            surnames=payload.surnames,
            add_login=payload.add_login,
            both_databases=both_databases,
        )
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(qr_export_service.generate_zip, params)
        try:
            zip_bytes = future.result(timeout=settings.QR_SQL_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    except FuturesTimeoutError as exc:
        raise to_http_error(
            ServiceTimeoutError(
                "Выгрузка QR превысила таймаут SQL. Проверьте доступность MSSQL и уменьшите объем выборки."
            ),
            operation="сформировать выгрузку",
        ) from exc
    except Exception as exc:
        raise to_http_error(exc, operation="сформировать выгрузку") from exc

    filename = f"qr_export_{datetime.date.today().isoformat()}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
