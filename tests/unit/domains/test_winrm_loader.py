import base64

from app.core.config import settings
from app.domains.remote_access import deploy_script


def test_loader_fits_windows_command_limit_and_preserves_powershell_variables(monkeypatch):
    monkeypatch.setattr(settings, "RUSTDESK_DEPLOY_TOKEN", "test-$value-'quoted'")
    script = deploy_script.winrm_bootstrap()
    assert not script.startswith("powershell.exe")
    assert "$script=$client.DownloadString(" in script
    assert "Invoke-Expression $script" in script
    assert "'test-$value-''quoted'''" in script
    assert len(base64.b64encode(script.encode("utf-16-le"))) < 8000
    assert "Write-Error $_" not in script
    assert "[Enum]::ToObject([Net.SecurityProtocolType],3072)" in script
    assert "IsDefined" not in script


def test_all_generated_entrypoints_select_tls12_without_named_enum():
    for script in (deploy_script.winrm_bootstrap(), deploy_script.deploy_command(), deploy_script.render_bootstrap()):
        assert "[Enum]::ToObject([Net.SecurityProtocolType],3072)" in script
        assert "[Net.SecurityProtocolType]::Tls12" not in script


def test_online_bootstrap_is_powershell2_compatible_and_reports_failures():
    import re
    script = deploy_script.render_bootstrap()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    for pattern in [r"ConvertTo-Json", r"ConvertFrom-Json", r"Invoke-RestMethod", r"Invoke-WebRequest",
                    r"Get-FileHash", r"Get-CimInstance", r"\[pscustomobject\]", r"\s-Directory\b"]:
        assert not re.search(pattern, code)
    assert "JavaScriptSerializer" in code and "ComputeHash" in code
    assert "$sha.Clear()" in code and "$sha.Dispose()" not in code
    assert "legacy = [bool]$Legacy" in code
    assert "'/norestart'" in code
    assert "Write-Output $msg" in code
    assert "os_caption = [string]$OsCaption" in code
    assert "version = [string]$Version" in code
    assert "$cfg.block_outgoing -and $canApplyAppLocker" in code
    assert "-WindowStyle Hidden" in code


def test_old_professional_is_not_reported_as_applocker_supported():
    from app.domains.remote_access.service.devices import classify_applocker_support
    assert classify_applocker_support("Professional", "Microsoft Windows 7 Professional") is False
    assert classify_applocker_support("Enterprise", "Microsoft Windows 7 Enterprise") is True
    assert classify_applocker_support("Professional", "Windows 10 Pro") is True
