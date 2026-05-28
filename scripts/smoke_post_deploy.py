from __future__ import annotations

import os
import sys

import httpx


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "https://localhost/api/v1").rstrip("/")
    verify_tls = _env_bool("SMOKE_VERIFY_TLS", False)

    with httpx.Client(timeout=30.0, verify=verify_tls) as client:
        ready = client.get("https://localhost/ready")
        ready.raise_for_status()
        health = client.get("https://localhost/health")
        health.raise_for_status()

        if not _env_bool("SMOKE_RUN_AUTH", True):
            print("Skipped auth smoke (SMOKE_RUN_AUTH=false).")
            print("Post-deploy smoke passed.")
            return 0

        email = _require_env("SMOKE_ADMIN_EMAIL")
        password = _require_env("SMOKE_ADMIN_PASSWORD")

        login_response = client.post(
            f"{base_url}/auth/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        login_response.raise_for_status()
        token = login_response.json()["access_token"]

        if _env_bool("SMOKE_RUN_BOARDING", True):
            boarding_response = client.post(
                f"{base_url}/boarding-pass/export",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "format": "aztec",
                    "raw_data": "M1SMOKE/POSTDEPLOY EBR123 SVOLEDSU1234032Y12A001",
                },
            )
            boarding_response.raise_for_status()
            if not boarding_response.content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("boarding-pass smoke returned non-PNG payload")

        print("Post-deploy smoke passed.")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - smoke script
        print(f"Post-deploy smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
