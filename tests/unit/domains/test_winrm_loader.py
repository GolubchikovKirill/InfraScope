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
