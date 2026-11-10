"""Prepare the read-only WinRM channel on one managed deployment target."""
from __future__ import annotations

import base64
import ipaddress
import socket
import time
import uuid

from app.core.config import settings
from app.services.hostname_resolver import resolve_hostname


def _listening(address: str) -> bool:
    try:
        with socket.create_connection((address, settings.WINRM_PORT), timeout=3):
            return True
    except ConnectionRefusedError:
        return False


def ensure_winrm(hostname: str) -> None:
    """Enable only a refused HTTP listener; auth failures never trigger changes."""
    if not settings.WINRM_AUTO_ENABLE:
        return
    address = resolve_hostname(hostname, dns_search_suffixes=settings.DNS_SEARCH_SUFFIXES,
                               dns_server=settings.DNS_SERVER) or hostname
    if _listening(address):
        return
    if not settings.hardware_writes_allowed:
        raise RuntimeError("Изменения Windows отключены настройками этого экземпляра InfraScope.")
    if settings.WINRM_USE_SSL or settings.WINRM_PORT != 5985:
        raise RuntimeError("Автоподготовка поддерживает HTTP WinRM 5985; HTTPS требует готового сертификата.")
    source = str(ipaddress.ip_address(settings.WINRM_BOOTSTRAP_SOURCE_IP))
    account = settings.WINRM_ADMIN_USERNAME
    if "\\" in account:
        domain, username = account.split("\\", 1)
    elif "@" in account:
        username, domain = account.split("@", 1)
    else:
        domain, username = "", account
    # COM firewall API and Enable-PSRemoting are available on Windows 7/PS2.
    script = (
        "$ErrorActionPreference='Stop'; try { Enable-PSRemoting -Force } finally { "
        "$fw=New-Object -ComObject HNetCfg.FwPolicy2; "
        "foreach($rule in $fw.Rules) { if($rule.Direction -eq 1 -and "
        "($rule.LocalPorts -eq '5985') -and $rule.Enabled) {"
        f"$rule.RemoteAddresses='{source}'"
        "} } }"
    )
    command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
    command += base64.b64encode(script.encode("utf-16-le")).decode()
    _start_bootstrap(address, username, domain, command)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if _listening(address):
            return
        time.sleep(2)
    raise RuntimeError("WinRM не открыл порт после настройки. Проверьте GPO и firewall на машине.")


def _scheduled_command(command: str) -> str:
    # Windows 7 rejects local WSMan configuration from a network logon even
    # with an elevated administrator token. Run a short-lived SYSTEM task.
    # Use the Scheduler COM API: schtasks /TR is limited to 261 characters.
    task_name = "InfraScope-WinRM-" + uuid.uuid4().hex
    cleanup = (
        "$s=New-Object -ComObject Schedule.Service;$s.Connect();"
        f"$s.GetFolder('\\').DeleteTask('{task_name}',0)"
    )
    original = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")
    action = "try {" + original + "} finally {" + cleanup + "}"
    arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
    arguments += base64.b64encode(action.encode("utf-16-le")).decode()
    register = (
        "$ErrorActionPreference='Stop';$s=New-Object -ComObject Schedule.Service;$s.Connect();"
        "$t=$s.NewTask(0);$t.Principal.UserId='SYSTEM';$t.Principal.LogonType=5;"
        "$t.Principal.RunLevel=1;$t.Settings.ExecutionTimeLimit='PT2M';"
        "$t.Settings.DisallowStartIfOnBatteries=$false;$t.Settings.StopIfGoingOnBatteries=$false;"
        "$a=$t.Actions.Create(0);$a.Path='powershell.exe';"
        f"$a.Arguments='{arguments}';"
        f"$s.GetFolder('\\').RegisterTaskDefinition('{task_name}',$t,6,'SYSTEM',$null,5).Run($null)"
    )
    command = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
    command += base64.b64encode(register.encode("utf-16-le")).decode()
    return command


def _start_bootstrap(address: str, username: str, domain: str, command: str) -> None:
    from impacket.dcerpc.v5.dcom import wmi
    from impacket.dcerpc.v5.dcomrt import DCOMConnection
    from impacket.dcerpc.v5.dtypes import NULL

    command = _scheduled_command(command)
    connection = DCOMConnection(address, username, settings.WINRM_ADMIN_PASSWORD, domain, oxidResolver=True)
    try:
        interface = connection.CoCreateInstanceEx(wmi.CLSID_WbemLevel1Login, wmi.IID_IWbemLevel1Login)
        login = wmi.IWbemLevel1Login(interface)
        services = login.NTLMLogin("//./root/cimv2", NULL, NULL)
        login.RemRelease()
        process, _ = services.GetObject("Win32_Process")
        result = process.Create(command, "C:\\", None)
        if result.getProperties()["ReturnValue"]["value"] != 0:
            raise RuntimeError("WMI отклонил запуск настройки WinRM.")
    finally:
        connection.disconnect()
