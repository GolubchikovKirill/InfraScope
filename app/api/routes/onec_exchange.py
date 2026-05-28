from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_superuser
from app.domains.integrations.schemas import OneCExchangeByBarcodeRequest, OneCExchangeByBarcodeResponse
from app.domains.operations.models import CashRegister
from app.services.onec_exchange import OneCExchangeService

router = APIRouter(tags=["1c-exchange"])
onec_exchange_service = OneCExchangeService()


def _resolve_cash_register_targets(
    session: SessionDep,
    identifiers: list[str],
    identifier_kind: str,
) -> list[dict[str, str | None]]:
    if not identifiers:
        return []
    allowed_fields = {
        "hostname": CashRegister.hostname,
        "kkm_number": CashRegister.kkm_number,
        "serial_number": CashRegister.serial_number,
        "inventory_number": CashRegister.inventory_number,
        "cash_number": CashRegister.cash_number,
    }
    column = allowed_fields.get(identifier_kind)
    if column is None:
        return []

    values = [item.strip() for item in identifiers if item.strip()]
    if not values:
        return []

    rows = session.exec(select(CashRegister).where(column.in_(values))).all()
    by_key: dict[str, CashRegister] = {}
    for row in rows:
        key_value = getattr(row, identifier_kind)
        if key_value and key_value not in by_key:
            by_key[key_value] = row

    resolved: list[dict[str, str | None]] = []
    for value in values:
        row = by_key.get(value)
        if row is None:
            resolved.append(
                {
                    "identifier_kind": identifier_kind,
                    "identifier_value": value,
                    "hostname": None,
                    "kkm_number": None,
                    "serial_number": None,
                    "inventory_number": None,
                    "cash_number": None,
                }
            )
            continue
        resolved.append(
            {
                "identifier_kind": identifier_kind,
                "identifier_value": value,
                "hostname": row.hostname,
                "kkm_number": row.kkm_number,
                "serial_number": row.serial_number,
                "inventory_number": row.inventory_number,
                "cash_number": row.cash_number,
            }
        )
    return resolved


@router.post(
    "/by-barcode",
    response_model=OneCExchangeByBarcodeResponse,
    dependencies=[Depends(get_current_active_superuser)],
)
async def run_exchange_by_barcode(
    payload: OneCExchangeByBarcodeRequest,
    session: SessionDep,
) -> OneCExchangeByBarcodeResponse:
    resolved_targets = _resolve_cash_register_targets(
        session,
        payload.cash_register_identifiers,
        payload.cash_register_identifier_kind,
    )
    result = await onec_exchange_service.exchange_product_docs_by_barcode(
        target=payload.target,
        barcode=payload.barcode,
        cash_register_hostnames=payload.cash_register_hostnames,
        cash_register_targets=resolved_targets,
        source=payload.source,
    )
    result_payload = result.to_dict() if hasattr(result, "to_dict") else result
    return OneCExchangeByBarcodeResponse(**result_payload)
