from __future__ import annotations

import os
import sys

import httpx


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for live boarding pass smoke")
    return value


def main() -> int:
    base_url = _require_env("SMOKE_BASE_URL").rstrip("/")
    email = _require_env("SMOKE_ADMIN_EMAIL")
    password = _require_env("SMOKE_ADMIN_PASSWORD")

    with httpx.Client(timeout=30.0) as client:
        login_response = client.post(
            f"{base_url}/auth/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        login_response.raise_for_status()
        token = login_response.json()["access_token"]

        export_response = client.post(
            f"{base_url}/boarding-pass/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "format": "aztec",
                "raw_data": "M1SMOKE/BOARDING EBR123 SVOLEDSU1234032Y12A001",
            },
        )
        export_response.raise_for_status()

    content_type = export_response.headers.get("content-type", "")
    disposition = export_response.headers.get("content-disposition", "")
    if not content_type.startswith("image/png"):
        raise RuntimeError(f"unexpected content-type: {content_type}")
    if "boarding_pass_aztec_" not in disposition:
        raise RuntimeError(f"unexpected content-disposition: {disposition}")
    if not export_response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("response is not a PNG file")

    print("Boarding pass live smoke passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - smoke script
        print(f"Boarding pass live smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
