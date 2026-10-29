"""Runs one PowerShell command on a managed device over WinRM.

This is how the server itself rolls software out to the fleet, replacing a
Windows admin host running the push kit over the `C$` admin share + WMI/DCOM
(see `push_jobs.py`'s module docstring for why that path existed at all).
WinRM is the sanctioned remote-administration protocol for Windows - the
rough equivalent of SSH, and what Ansible uses for the same job - so unlike
SMB admin-share + WMI/DCOM execution it is not the signature EDR correlates
with lateral movement. It still has to be turned on explicitly on each
target (off by default on a workgroup/domain machine); see
`rustdesk-push/Enable-WinRM-GPO.ps1`.

One fleet-wide service account (`WINRM_ADMIN_USERNAME` / `WINRM_ADMIN_PASSWORD`),
the same shape as the RustDesk console's own service account - not a secret
per device. `run_powershell` is deliberately generic (any script, any exit
code): RustDesk is its first caller (`push_jobs.py`), not its only one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
import winrm
from winrm.exceptions import WinRMError

from app.core.config import settings

logger = logging.getLogger(__name__)

# requests raises these for a host that is unreachable, refuses the port, or never
# answers; winrm.exceptions.WinRMError covers an authenticated-but-rejected request
# (bad creds, WinRM not enabled, wrong auth type). Together: everything short of the
# remote script's own exit code.
_CONNECTION_ERRORS = (WinRMError, requests.exceptions.RequestException)


class WinRMNotConfiguredError(RuntimeError):
    """WINRM_ADMIN_USERNAME / WINRM_ADMIN_PASSWORD are not set."""


@dataclass
class WinRMResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    # short text for the push job's `detail` column: stdout tail on success,
    # stderr/stdout tail or the connection error on failure
    detail: str


def _short(exc: Exception) -> str:
    return str(exc).splitlines()[0][:300]


def _session(hostname: str) -> winrm.Session:
    if not settings.WINRM_ADMIN_USERNAME or not settings.WINRM_ADMIN_PASSWORD:
        raise WinRMNotConfiguredError("WINRM_ADMIN_USERNAME / WINRM_ADMIN_PASSWORD are not set")
    scheme = "https" if settings.WINRM_USE_SSL else "http"
    endpoint = f"{scheme}://{hostname}:{settings.WINRM_PORT}/wsman"
    return winrm.Session(
        endpoint,
        auth=(settings.WINRM_ADMIN_USERNAME, settings.WINRM_ADMIN_PASSWORD),
        transport=settings.WINRM_TRANSPORT,
        # The fleet has no internal CA for WinRM listeners; HTTP+NTLM (the default
        # here) encrypts the message itself, same trust model paramiko's SSH use
        # elsewhere in this app relies on key/password auth rather than a CA chain.
        server_cert_validation="ignore" if not settings.WINRM_USE_SSL else "validate",
        operation_timeout_sec=settings.WINRM_OPERATION_TIMEOUT_SECONDS,
        read_timeout_sec=settings.WINRM_OPERATION_TIMEOUT_SECONDS + 10,
    )


def run_powershell(hostname: str, script: str) -> WinRMResult:
    """Run `script` on `hostname` and wait for it to exit.

    pywinrm polls the remote shell until the command finishes, so this blocks for
    as long as the script runs - minutes for a real install, not just a connect
    timeout. Never raises for anything the *target* did (bad exit code, stderr
    output); only `WinRMNotConfiguredError` escapes, everything else comes back as a
    `WinRMResult(ok=False, ...)` so a caller queuing many devices can keep going.
    """
    try:
        session = _session(hostname)
        result = session.run_ps(script)
    except WinRMNotConfiguredError:
        raise
    except _CONNECTION_ERRORS as exc:
        logger.info("WinRM call to %s could not connect: %s", hostname, exc)
        return WinRMResult(ok=False, exit_code=None, stdout="", stderr=str(exc), detail=f"WinRM недоступен: {_short(exc)}")
    stdout = (result.std_out or b"").decode("utf-8", "replace").strip()
    stderr = (result.std_err or b"").decode("utf-8", "replace").strip()
    ok = result.status_code == 0
    tail = (stdout if ok else (stderr or stdout))[-800:]
    detail = tail or f"exit code {result.status_code}"
    return WinRMResult(ok=ok, exit_code=result.status_code, stdout=stdout, stderr=stderr, detail=detail)


# Dry-run probe: reach the machine, say what is already on it, install nothing.
_PROBE_SCRIPT = (
    "$os = Get-CimInstance Win32_OperatingSystem; "
    "$svc = Get-Service RustDesk -ErrorAction SilentlyContinue; "
    "Write-Output ($os.Caption + ' (' + $os.Version + ') | RustDesk service: ' + "
    "$(if ($svc) { $svc.Status } else { 'absent' }))"
)


def probe(hostname: str) -> WinRMResult:
    """Can this host be reached over WinRM, and what is on it already."""
    return run_powershell(hostname, _PROBE_SCRIPT)
