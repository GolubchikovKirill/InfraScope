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
