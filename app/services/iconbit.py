"""Client for Iconbit media player HTTP API (port 8081).

Supports two firmware variants:
  New firmware: GET /now returns currently playing track (HTML).
  Old firmware: GET /status.xml returns XML with <state>, <file>, <position>, <duration>.

Common endpoints:
  GET /play, /play?file=X, /play?url=X – start playback
  GET /stop – stop playback
  GET /delete?file=X – delete a file
  POST / (multipart) – upload file (old fw)
  POST /upload (multipart) – upload file (new fw)
  GET /send?key=X&arg=Y – remote control (old fw)
  GET /screen.png – live screenshot (old fw)
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.observability.metrics import media_player_ops_total

logger = logging.getLogger(__name__)

ICONBIT_PORT = 8081
TIMEOUT = 8

AUTH_CREDS = ("admin", "admin")
_FIRMWARE_HINTS: dict[str, str] = {}
_WARN_COOLDOWN_SECONDS = 600.0
_WARN_LAST_SEEN: dict[str, float] = {}


def _log_warning_with_cooldown(key: str, message: str, *args) -> None:
    now = time.monotonic()
    last = _WARN_LAST_SEEN.get(key, 0.0)
    if now - last >= _WARN_COOLDOWN_SECONDS:
        _WARN_LAST_SEEN[key] = now
        logger.warning(message, *args)


@dataclass
class IconbitStatus:
    now_playing: str | None = None
    is_playing: bool = False
    state: str | None = None  # "playing", "paused", "idle"
    position: int | None = None  # seconds
    duration: int | None = None  # seconds
    files: list[str] = field(default_factory=list)
    free_space: str | None = None


def _base_url(ip: str) -> str:
    return f"http://{ip}:{ICONBIT_PORT}"


def _get(url: str, **kwargs) -> httpx.Response | None:
    try:
        resp = httpx.get(url, auth=AUTH_CREDS, timeout=TIMEOUT, follow_redirects=True, **kwargs)
        media_player_ops_total.labels(
            operation="iconbit_http_get",
            result="success" if resp.status_code < 500 else "error",
        ).inc()
        return resp
    except Exception as e:
        media_player_ops_total.labels(operation="iconbit_http_get", result="error").inc()
        if "Connection refused" in str(e):
            host = urlparse(url).hostname or url
            _log_warning_with_cooldown(f"iconbit_conn_refused:{host}", "Iconbit GET %s failed: %s", url, e)
        else:
            logger.warning("Iconbit GET %s failed: %s", url, e)
        return None


def _post(url: str, **kwargs) -> httpx.Response | None:
    try:
        resp = httpx.post(url, auth=AUTH_CREDS, follow_redirects=True, **kwargs)
        media_player_ops_total.labels(
            operation="iconbit_http_post",
            result="success" if resp.status_code < 500 else "error",
        ).inc()
        return resp
    except Exception as e:
        media_player_ops_total.labels(operation="iconbit_http_post", result="error").inc()
        logger.warning("Iconbit POST %s failed: %s", url, e)
        return None


def _parse_status_xml(text: str) -> dict | None:
    """Parse /status.xml response."""
    try:
        root = ET.fromstring(text)
        return {
            "state": (root.findtext("state") or "").strip().lower(),
            "file": (root.findtext("file") or "").strip(),
            "position": int(root.findtext("position") or 0),
            "duration": int(root.findtext("duration") or 0),
        }
    except Exception:
        return None


def _parse_now_html(text: str) -> str | None:
    """Extract track name from /now HTML response."""
    match = re.search(r"<b>(.*?)</b>", text, re.IGNORECASE | re.DOTALL)
    if match:
        track = match.group(1).strip()
        if track and track.lower() not in ("", "none", "нет", "nothing", "-"):
            return track
    clean = re.sub(r"<[^>]+>", "", text).strip()
    if clean and len(clean) < 200 and clean.lower() not in ("", "none", "нет"):
        return clean
    return None


def _parse_free_space(html: str) -> str | None:
    """Extract free space from main page HTML."""
    m = re.search(r"[Дд]оступно\s+(\d+[\.,]?\d*\s*[GMKT]B)\s*/\s*(\d+[\.,]?\d*\s*[GMKT]B)", html, re.IGNORECASE)
    if m:
        return f"{m.group(1)} / {m.group(2)}"
    m = re.search(r"(\d+[\.,]?\d*\s*[GMKT]B)\s*/\s*(\d+[\.,]?\d*\s*[GMKT]B)", html, re.IGNORECASE)
    if m:
        return f"{m.group(1)} / {m.group(2)}"
    m = re.search(r"(\d+[\.,]?\d*\s*[GMKT]B)\s+available", html, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def get_status(ip: str) -> IconbitStatus:
    """Fetch current playback status and file list."""
    status = IconbitStatus()
    base = _base_url(ip)

    # 1. Main page — file list and free space
    main_resp = _get(base)
    if main_resp is None:
        # Device is unreachable right now; avoid retry storm on other endpoints.
        return status
    if main_resp and main_resp.status_code == 200:
        html = main_resp.text
        file_matches = re.findall(r'delete\?file=([^"&\']+)', html, re.IGNORECASE)
        status.files = [f.strip() for f in file_matches if f.strip()]
        status.free_space = _parse_free_space(html)

    # Probe preferred endpoint first based on cached firmware hint.
    # This avoids repeated status.xml=404 for new firmware and speeds up polling.
    hint = _FIRMWARE_HINTS.get(ip)
    prefer_now = hint == "new"
    endpoint_order = ["now", "status.xml"] if prefer_now else ["status.xml", "now"]

    for endpoint in endpoint_order:
        if endpoint == "status.xml":
            xml_resp = _get(f"{base}/status.xml")
            if not xml_resp:
                continue
            if xml_resp.status_code == 200:
                parsed = _parse_status_xml(xml_resp.text)
                if parsed:
                    _FIRMWARE_HINTS[ip] = "old"
                    status.state = parsed["state"]
                    status.is_playing = parsed["state"] in ("playing", "paused")
                    if parsed["file"]:
                        status.now_playing = parsed["file"]
                    status.position = parsed["position"]
                    status.duration = parsed["duration"]
                    return status
            # New firmware commonly returns 404 on /status.xml.
            if xml_resp.status_code == 404:
                _FIRMWARE_HINTS[ip] = "new"
                continue
        else:
            now_resp = _get(f"{base}/now")
            if not now_resp:
                continue
            if now_resp.status_code == 200:
                _FIRMWARE_HINTS[ip] = "new"
                track = _parse_now_html(now_resp.text)
                if track:
                    status.now_playing = track
                    status.is_playing = True
                    status.state = "playing"
                return status

    return status


def play(ip: str) -> bool:
    resp = _get(f"{_base_url(ip)}/play")
    return resp is not None and resp.status_code in (200, 302)


def stop(ip: str) -> bool:
    resp = _get(f"{_base_url(ip)}/stop")
    return resp is not None and resp.status_code in (200, 302)


def play_file(ip: str, filename: str) -> bool:
    # Old fw: /play?file=X, New fw: /playlink?link=X — try both
    resp = _get(f"{_base_url(ip)}/play", params={"file": filename})
    if resp and resp.status_code in (200, 302):
        return True
    resp = _get(f"{_base_url(ip)}/playlink", params={"link": filename})
    return resp is not None and resp.status_code in (200, 302)


def delete_file(ip: str, filename: str) -> bool:
    resp = _get(f"{_base_url(ip)}/delete", params={"file": filename})
    return resp is not None and resp.status_code in (200, 302)


def upload_file(ip: str, filename: str, content: bytes) -> bool:
    # Old fw: POST to /, New fw: POST to /upload
    resp = _post(f"{_base_url(ip)}/", files={"file": (filename, content)}, timeout=60)
    if resp and resp.status_code in (200, 302):
        return True
    resp = _post(f"{_base_url(ip)}/upload", files={"file": (filename, content)}, timeout=60)
    return resp is not None and resp.status_code in (200, 302)


def delete_all_files(ip: str) -> bool:
    """Delete all files from the device."""
    status = get_status(ip)
    ok = True
    for f in status.files:
        if not delete_file(ip, f):
            ok = False
    return ok
