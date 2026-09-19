"""Static guards for the operator-side RustDesk push tooling (rustdesk-ksc/).

The scripts are PowerShell and cannot run in CI, so these tests pin the two
properties that matter and are easy to break by accident:

* nothing in the rollout may reboot a machine or need a reboot (installing WMF /
  Windows updates is exactly what forced reboots on tills before);
* the endpoint script must stay valid PowerShell 2.0 - Windows 7 tills have no WMF 5.1.
"""

from __future__ import annotations

import re
from pathlib import Path

KSC = Path(__file__).resolve().parents[3] / "rustdesk-ksc"
ENDPOINT = (KSC / "endpoint" / "Install-RustDesk.ps1").read_text(encoding="utf-8")
PUSH = (KSC / "Push-RustDesk.ps1").read_text(encoding="utf-8")


def _code(text: str) -> str:
    """Script text without comment-only lines and block comments."""
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


REBOOT_PATTERNS = [
    r"Restart-Computer",
    r"Stop-Computer",
    r"shutdown(\.exe)?\s",
    r"/forcerestart",
    r"\bwusa(\.exe)?\b",
    r"KB3191566",
    r"Install-WindowsUpdate",
]

# constructs missing from Windows PowerShell 2.0 (Windows 7 without WMF 5.1)
PS3_ONLY = [
    r"ConvertFrom-Json",
    r"ConvertTo-Json",
    r"Invoke-RestMethod",
    r"Invoke-WebRequest",
    r"Get-FileHash",
    r"Get-CimInstance",
    r"New-CimSession",
    r"\[pscustomobject\]",
    r"\[ordered\]",
    r"\$PSScriptRoot",
    r"Get-Content[^\n|]*-Raw",
    r"::new\(",
]


def test_no_script_reboots_the_machine_or_installs_updates() -> None:
    for name, text in (("Install-RustDesk.ps1", ENDPOINT), ("Push-RustDesk.ps1", PUSH)):
        code = _code(text)
        for pattern in REBOOT_PATTERNS:
            assert not re.search(pattern, code, flags=re.I), f"{name} must not contain {pattern!r}"


def test_endpoint_script_stays_powershell_2_compatible() -> None:
    code = _code(ENDPOINT)
    for pattern in PS3_ONLY:
        assert not re.search(pattern, code), f"Install-RustDesk.ps1 must not use {pattern!r} (PowerShell 2.0)"


def test_msi_install_never_restarts_and_accepts_3010() -> None:
    assert "/norestart" in ENDPOINT
    assert "$p.ExitCode -ne 0 -and $p.ExitCode -ne 3010" in ENDPOINT


def test_endpoint_picks_the_installer_by_os_and_refuses_xp() -> None:
    assert "$legacy = ($major -lt 10) -or (-not $is64)" in ENDPOINT
    assert "if ($major -lt 6) { Done 3" in ENDPOINT
    assert "--silent-install" in ENDPOINT and "--install-service" in ENDPOINT


def test_endpoint_registers_the_service_when_the_msi_leaves_none() -> None:
    # an MSI over an existing install can leave the files without the service
    assert "service missing after install, registering" in ENDPOINT


def test_profiles_are_only_the_three_flags() -> None:
    assert "hidden = true" not in PUSH.lower()  # no hard-coded profile in the script text
    assert "-Profile" in PUSH and "'client'" in PUSH and "'admin'" in PUSH
    assert "unattended" in PUSH and "hidden" in PUSH and "block_outgoing" in PUSH


def test_push_skips_xp_and_uses_dcom_not_winrm() -> None:
    assert "Windows XP: RustDesk is not supported" in PUSH
    assert "-Protocol Dcom" in PUSH
    assert "Enter-PSSession" not in PUSH and "Invoke-Command" not in PUSH
