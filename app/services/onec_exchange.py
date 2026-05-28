from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.services.contracts import IntegrationServiceResult


class OneCExchangeService:
    async def _post_with_retries(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        json_body: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        retries = max(1, settings.INTERNAL_HTTP_RETRIES)
        backoff = max(0.0, settings.INTERNAL_HTTP_RETRY_BACKOFF_SECONDS)
        last_exc: httpx.HTTPError | None = None
        for attempt in range(1, retries + 1):
            try:
                return await client.post(url, json=json_body, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= retries:
                    raise
                await asyncio.sleep(backoff * attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError("unreachable")

    def _resolve_target_settings(self, target: str) -> tuple[str, str]:
        target_to_url = {
            "duty_free": settings.ONEC_DUTY_FREE_API_URL or settings.ONEC_EXCHANGE_API_URL,
            "duty_paid": settings.ONEC_DUTY_PAID_API_URL or settings.ONEC_EXCHANGE_API_URL,
        }
        target_to_token = {
            "duty_free": settings.ONEC_DUTY_FREE_API_TOKEN or settings.ONEC_EXCHANGE_API_TOKEN,
            "duty_paid": settings.ONEC_DUTY_PAID_API_TOKEN or settings.ONEC_EXCHANGE_API_TOKEN,
        }
        return target_to_url.get(target, ""), target_to_token.get(target, "")

    def _build_missing_url_message(self, *, target: str) -> str:
        target_human = "Duty Free" if target == "duty_free" else "Duty Paid"
        ib_connection = (
            settings.ONEC_DUTY_FREE_IB_CONNECTION if target == "duty_free" else settings.ONEC_DUTY_PAID_IB_CONNECTION
        )
        ib_domain = settings.ONEC_DUTY_FREE_DOMAIN if target == "duty_free" else settings.ONEC_DUTY_PAID_DOMAIN
        terminal_server = (
            settings.ONEC_DUTY_FREE_TERMINAL_SERVER
            if target == "duty_free"
            else settings.ONEC_DUTY_PAID_TERMINAL_SERVER
        )
        ib_hint = f" Текущая база 1С: {ib_connection}." if ib_connection else ""
        domain_hint = f" Домен подключения: {ib_domain}." if ib_domain else ""
        terminal_hint = f" Терминальный сервер: {terminal_server}." if terminal_server else ""
        return (
            f"Не настроен URL API 1С для {target_human}. "
            "Укажите ONEC_DUTY_*_API_URL в .env (HTTP endpoint сервиса обмена в 1С)."
            f"{ib_hint}{domain_hint}{terminal_hint}"
        )

    async def exchange_product_docs_by_barcode(
        self,
        *,
        target: str = "duty_free",
        barcode: str,
        cash_register_hostnames: list[str] | None = None,
        cash_register_targets: list[dict[str, str | None]] | None = None,
        source: str = "infrascope",
    ) -> IntegrationServiceResult:
        api_url, api_token = self._resolve_target_settings(target)

        if not api_url:
            return IntegrationServiceResult(
                target=target,
                ok=False,
                message=self._build_missing_url_message(target=target),
                status_code=None,
                request_id=None,
                payload=None,
                error_kind="config",
            )

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        base_body = {
            "barcode": barcode,
            "source": source,
            "target": target,
        }

        try:
            async with httpx.AsyncClient(timeout=settings.ONEC_EXCHANGE_TIMEOUT_SECONDS) as client:
                if cash_register_targets:
                    total = len(cash_register_targets)
                    success = 0
                    failed = 0
                    errors: list[dict[str, Any]] = []
                    request_ids: list[str] = []
                    last_status_code: int | None = None
                    last_payload: dict[str, Any] | None = None

                    # Sequential dispatch: one cash register at a time.
                    for entry in cash_register_targets:
                        body = dict(base_body)
                        body["cash_register"] = entry
                        hostname = entry.get("hostname")
                        body["cash_register_hostnames"] = [hostname] if hostname else []

                        response = await self._post_with_retries(
                            client,
                            url=api_url,
                            json_body=body,
                            headers=headers,
                        )
                        request_id = response.headers.get("X-Request-ID") or response.headers.get("x-request-id")
                        if request_id:
                            request_ids.append(request_id)

                        content_type = response.headers.get("content-type", "")
                        payload: dict[str, Any] | None = None
                        if "application/json" in content_type.lower():
                            parsed = response.json()
                            payload = parsed if isinstance(parsed, dict) else {"value": parsed}

                        last_status_code = response.status_code
                        last_payload = payload

                        if response.is_success:
                            success += 1
                        else:
                            failed += 1
                            errors.append(
                                {
                                    "cash_register": entry,
                                    "status_code": response.status_code,
                                    "detail": payload.get("detail") if isinstance(payload, dict) else None,
                                }
                            )

                    return IntegrationServiceResult(
                        target=target,
                        ok=failed == 0,
                        message=(
                            f"Очередь выгрузки завершена: успешно {success} из {total}."
                            if failed == 0
                            else f"Очередь выгрузки завершена с ошибками: успешно {success}, ошибок {failed}, всего {total}."
                        ),
                        status_code=last_status_code,
                        request_id=request_ids[-1] if request_ids else None,
                        payload={
                            "total": total,
                            "success": success,
                            "failed": failed,
                            "request_ids": request_ids,
                            "errors": errors,
                            "last_response": last_payload,
                        },
                        error_kind=None if failed == 0 else "integration",
                    )

                body = dict(base_body)
                body["cash_register_hostnames"] = cash_register_hostnames or []
                response = await self._post_with_retries(
                    client,
                    url=api_url,
                    json_body=body,
                    headers=headers,
                )
                request_id = response.headers.get("X-Request-ID") or response.headers.get("x-request-id")
                content_type = response.headers.get("content-type", "")
                payload: dict[str, Any] | None = None
                if "application/json" in content_type.lower():
                    parsed = response.json()
                    payload = parsed if isinstance(parsed, dict) else {"value": parsed}

                if response.is_success:
                    return IntegrationServiceResult(
                        target=target,
                        ok=True,
                        message="Обмен с 1С выполнен успешно.",
                        status_code=response.status_code,
                        request_id=request_id,
                        payload=payload,
                        error_kind=None,
                    )

                detail = payload.get("detail") if isinstance(payload, dict) else None
                return IntegrationServiceResult(
                    target=target,
                    ok=False,
                    message=f"1С вернула ошибку ({response.status_code})" + (f": {detail}" if detail else ""),
                    status_code=response.status_code,
                    request_id=request_id,
                    payload=payload,
                    error_kind="integration",
                )
        except httpx.HTTPError as exc:
            return IntegrationServiceResult(
                target=target,
                ok=False,
                message=f"Не удалось выполнить запрос к 1С: {exc}",
                status_code=None,
                request_id=None,
                payload=None,
                error_kind="timeout",
            )


_default_service = OneCExchangeService()


async def exchange_product_docs_by_barcode(
    *,
    target: str = "duty_free",
    barcode: str,
    cash_register_hostnames: list[str] | None = None,
    cash_register_targets: list[dict[str, str | None]] | None = None,
    source: str = "infrascope",
) -> IntegrationServiceResult:
    return await _default_service.exchange_product_docs_by_barcode(
        target=target,
        barcode=barcode,
        cash_register_hostnames=cash_register_hostnames,
        cash_register_targets=cash_register_targets,
        source=source,
    )
