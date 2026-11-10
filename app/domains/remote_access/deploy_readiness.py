"""Local prerequisites for a network installation. Never returns credentials."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings


def installation_checks(*, legacy: bool = False) -> dict[str, bool]:
    filename = settings.RUSTDESK_LEGACY_INSTALLER_FILENAME if legacy else settings.RUSTDESK_INSTALLER_FILENAME
    expected = settings.RUSTDESK_LEGACY_INSTALLER_SHA256 if legacy else settings.RUSTDESK_INSTALLER_SHA256
    package = Path(settings.RUSTDESK_PACKAGE_DIR) / Path(filename).name
    checksum_matches = False
    if package.is_file() and expected:
        try:
            with package.open("rb") as stream:
                checksum_matches = hashlib.file_digest(stream, "sha256").hexdigest().lower() == expected.lower()
        except OSError:
            checksum_matches = False
    return {
        "winrm_credentials": bool(settings.WINRM_ADMIN_USERNAME and settings.WINRM_ADMIN_PASSWORD),
        "deploy_token": bool(settings.RUSTDESK_DEPLOY_TOKEN.strip()),
        "https_url": settings.RUSTDESK_PUBLIC_URL.startswith("https://"),
        "server_key": bool(settings.RUSTDESK_KEY.strip()),
        "installer_present": package.is_file(),
        "installer_checksum": checksum_matches,
    }
