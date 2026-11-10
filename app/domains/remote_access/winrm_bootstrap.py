"""Prepare the read-only WinRM channel on one managed deployment target."""
from __future__ import annotations

import base64
import ipaddress
import socket
import time

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
    if not settings.ALLOW_HARDWARE_WRITES:
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
        "$ErrorActionPreference='Stop'; Enable-PSRemoting -Force; "
        "$fw=New-Object -ComObject HNetCfg.FwPolicy2; "
        "foreach($rule in $fw.Rules) { if($rule.Direction -eq 1 -and "
        "($rule.LocalPorts -eq '5985') -and $rule.Enabled) {"
        f"$rule.RemoteAddresses='{source}'"
        "} }"
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


def _start_bootstrap(address: str, username: str, domain: str, command: str) -> None:
    from impacket.dcerpc.v5.dcom import wmi
    from impacket.dcerpc.v5.dcomrt import DCOMConnection
    from impacket.dcerpc.v5.dtypes import NULL

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
