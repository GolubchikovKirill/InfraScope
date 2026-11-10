"""Local prerequisites for a network installation. Never returns credentials."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.config import settings


def installation_checks() -> dict[str, bool]:
    package = Path(settings.RUSTDESK_PACKAGE_DIR) / Path(settings.RUSTDESK_INSTALLER_FILENAME).name
    checksum_matches = False
    if package.is_file() and settings.RUSTDESK_INSTALLER_SHA256:
        try:
            with package.open("rb") as stream:
                checksum_matches = hashlib.file_digest(stream, "sha256").hexdigest().lower() == settings.RUSTDESK_INSTALLER_SHA256.lower()
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
