"""The PowerShell InfraScope hands an endpoint to install RustDesk silently.

The script runs *on* the endpoint, as SYSTEM, and pulls everything it needs back
from InfraScope: its own config (id, password, options), the installer, and the
place to report the result. Nothing is pushed from the server - a Linux box
remote-executing on domain workstations is indistinguishable from lateral
movement and Kaspersky blocks it on this fleet. The trigger is whatever already
reaches the machine (a KSC "run script" task, a GPO startup script, a one-off
`schtasks /S <host> /RU SYSTEM`); InfraScope owns everything else.

Two things about the install are deliberate and easy to get wrong:

* **MSI, not `rustdesk.exe --silent-install`.** `--silent-install` never returns
  (the installer becomes the running app), so a script has to poll for the
  service and can never see a failure. `msiexec /qn` exits with a real code, and
  `CREATESTARTMENUSHORTCUTS=N CREATEDESKTOPSHORTCUTS=N INSTALLPRINTER=N` means no
  shortcuts and no phantom printer ever appear in front of the cashier.

* **Password before lockdown.** `disable-change-permanent-password=Y` makes
  `rustdesk.exe --password` a no-op, so the config is written in two passes: the
  working options first, the password, then the same file again with the locks.

Every deploy report also carries the endpoint's own registry `EditionID`
("Professional", "Enterprise", "Core" for Home). `block_outgoing` (the
AppLocker step below) does nothing on Windows Home - AppIDSvc doesn't exist
there - and self-reporting from the machine that's already running as SYSTEM
is the only way to see that without opening a new remote-query surface.
"""

from __future__ import annotations

from app.core.config import settings

# `[options]` written on the first pass. `allow-logon-screen-password` is what
# lets an engineer in when the store PC sits at the lock screen - without it a
# locked machine refuses the permanent password. See docs/rustdesk-v2-plan.md.
BASE_OPTIONS: dict[str, str] = {
    "enable-check-update": "N",
    "enable-lan-discovery": "N",
    "direct-server": "N",
    "allow-logon-screen-password": "Y",
    "remove-preset-password-warning": "Y",
    "hide-help-cards": "Y",
}

# added when the device wants the client kept out of the user's way
HIDDEN_OPTIONS: dict[str, str] = {
    "hide-tray": "Y",
    "hide-stop-service": "Y",
    "allow-hide-cm": "Y",
    "hide-security-settings": "Y",
    "hide-network-settings": "Y",
    "hide-server-settings": "Y",
}

# added when the device is unattended (password, no on-screen "Accept")
UNATTENDED_OPTIONS: dict[str, str] = {
    "approve-mode": "password",
    "verification-method": "use-permanent-password",
}

# second pass only - these block `--password` and `--id`, so they go on last
LOCK_OPTIONS: dict[str, str] = {
    "disable-change-permanent-password": "Y",
    "disable-change-id": "Y",
}


def client_options(*, hidden: bool, unattended: bool) -> dict[str, str]:
    """The `[options]` block for a device, before the write-lock pass."""
    options = dict(BASE_OPTIONS)
    if hidden:
        options.update(HIDDEN_OPTIONS)
    if unattended:
        options.update(UNATTENDED_OPTIONS)
    return options


def public_url() -> str:
    """Base URL an endpoint uses to reach this API."""
    return settings.RUSTDESK_PUBLIC_URL.rstrip("/")


def deploy_command(api_prefix: str = "/api/v1") -> str:
    """The single line an operator pastes into KSC / GPO / schtasks.

    nginx hard-redirects plain HTTP to HTTPS (`return 301 https://...`), and
    that HTTPS is a self-signed cert with no public CA behind it (LAN-only
    server, no public IP) - Windows PowerShell 5.1's WebClient rejects it by
    default with a generic "unable to create a secure channel" error that
    gives no hint it's a cert problem, not a network one. Verified live
    against a real fleet machine (VNA-MGR-15) before this fix was added: the
    trigger died before the downloaded script ever got a chance to run, so no
    log, no report - just silence. TLS1.2 fixes the protocol half of that.

    The cert half used to be `ServerCertificateValidationCallback = {$true}` -
    unconditional trust, so anything able to answer on 443 as this host's
    address (ARP/DNS spoofing on the LAN) could hand the endpoint arbitrary
    PowerShell to run as SYSTEM. Pinned to RUSTDESK_TLS_FINGERPRINT instead:
    the callback checks the presented cert's own SHA1 thumbprint, not the
    chain - same trust model as `curl -k`'s cousin `curl --pinnedpubkey`,
    appropriate for a cert with no CA behind it in the first place. Empty
    fingerprint falls back to normal validation (fails safe against this
    self-signed cert, doesn't silently reopen the bypass).

    Everything is wrapped in one try/catch that logs locally on failure - this
    line runs *before* the downloaded script's own logging exists, so without
    this a failure here is invisible everywhere (no local log, and nothing to
    report to InfraScope, since reporting needs this same HTTP call to work).
    Verified live on VNA-MGR-04: its PowerShell hosts .NET CLR 2.0, which
    predates TLS 1.1/1.2 support in System.Net.ServicePointManager entirely -
    `SecurityProtocolType.Tls12` isn't a valid enum member there, so the very
    first line throws. No amount of registry/GPO tweaking fixes that; the
    fix is upgrading PowerShell/WMF on that machine, or - since it needs no
    outbound HTTPS call at all - the offline rustdesk-ksc package instead.
    The catch block detects this exact failure shape and says so.
    """
    url = f"{public_url()}{api_prefix}/remote-access/deploy/bootstrap.ps1"
    # Pin the exact cert, don't just skip the chain check - an empty fingerprint
    # means "not configured", which falls back to normal (strict) validation
    # rather than trusting whatever's presented.
    cert_check = (
        (
            "[Net.ServicePointManager]::ServerCertificateValidationCallback="
            "{param($se,$ce,$ch,$er) $ce.GetCertHashString() -eq "
            f"'{settings.RUSTDESK_TLS_FINGERPRINT}'}};"
        )
        if settings.RUSTDESK_TLS_FINGERPRINT
        else ""
    )
    return (
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
        '"$ErrorActionPreference=\'Stop\'; try{'
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
        f"{cert_check}"
        "$c=New-Object Net.WebClient; "
        f"$c.Headers.Add('X-InfraScope-Deploy-Token','{settings.RUSTDESK_DEPLOY_TOKEN}'); "
        f"iex $c.DownloadString('{url}')"
        "}catch{"
        "$d='C:\\ProgramData\\InfraScope'; $null=New-Item -ItemType Directory -Force -Path $d;"
        "$m=$_.Exception.Message; $hint='';"
        "if($m -match 'SecurityProtocolType'){"
        "$hint=' -- PowerShell/.NET here is too old for TLS1.2 (CLR '+[Environment]::Version+"
        "'); use the offline rustdesk-ksc package instead, it makes no outbound HTTPS call'};"
        "Add-Content (Join-Path $d 'rustdesk-configure.log') "
        "((Get-Date -Format o)+'  BOOTSTRAP FAILED before config fetch: '+$m+$hint)"
        '}"'
    )


def render_bootstrap(api_prefix: str = "/api/v1") -> str:
    """Render the endpoint script. Values are baked in; the per-machine config is
    fetched at run time so a password rotation needs no new script."""
    base = f"{public_url()}{api_prefix}/remote-access/deploy"
    return _TEMPLATE.replace("@@BASE@@", base).replace("@@TOKEN@@", settings.RUSTDESK_DEPLOY_TOKEN)


# `@@BASE@@` / `@@TOKEN@@` rather than str.format: the script is full of braces.
_TEMPLATE = r"""
# InfraScope - silent RustDesk rollout. Runs as SYSTEM on the endpoint.
# Generated by InfraScope; do not edit on the machine - edit the device row.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# nginx serves this over a self-signed cert (LAN-only, no public IP behind
# it) - the deploy-command wrapper already sets this same bypass before
# fetching this file, so this line is only load-bearing if the script is
# ever run standalone (saved to disk, invoked without that wrapper).
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

$Base    = '@@BASE@@'
$Token   = '@@TOKEN@@'
$LogDir  = 'C:\ProgramData\InfraScope'
$Log     = Join-Path $LogDir 'rustdesk-configure.log'
$null    = New-Item -ItemType Directory -Force -Path $LogDir
function Log($m) { Add-Content $Log ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m) }

$Headers = @{ 'X-InfraScope-Deploy-Token' = $Token }
$Host_   = $env:COMPUTERNAME
$Rid     = ''
$Version = ''

# Registry EditionID is locale-independent ("Professional", "Enterprise",
# "Core" for Home, ...) - the OS Caption is only for display and can be
# localized ("Windows 10 Домашняя"). Both are read locally, no remote query:
# InfraScope has no other channel to learn this without a new remote-access
# surface, which is exactly what this pull-based rollout was built to avoid.
$edKey = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -EA SilentlyContinue
$OsEdition = if ($edKey) { "$($edKey.EditionID)" } else { '' }
$OsCaption = try { (Get-CimInstance Win32_OperatingSystem -EA Stop).Caption } catch { if ($edKey) { "$($edKey.ProductName)" } else { '' } }

function Report($state, $detail) {
    try {
        $body = @{ hostname = $Host_; rustdesk_id = $Rid; version = $Version;
                   state = $state; detail = "$detail"; os_edition = $OsEdition;
                   os_caption = $OsCaption } | ConvertTo-Json -Compress
        # UTF-8 bytes, not the string: Windows PowerShell 5.1 encodes a string body as
        # ISO-8859-1, so a localized error text ("Отказано в доступе") reached the server
        # as "????????" and the failure could not be read.
        Invoke-RestMethod -Uri "$Base/report" -Method Post -Headers $Headers `
            -ContentType 'application/json; charset=utf-8' `
            -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 30 | Out-Null
    } catch { Log "report failed: $($_.Exception.Message)" }
}

try {
    Log "=== deploy start on $Host_ (edition=$OsEdition) ==="

    # ---- 1. our own config -------------------------------------------------
    $cfgBody = @{ hostname = $Host_ } | ConvertTo-Json -Compress
    $cfg = Invoke-RestMethod -Uri "$Base/config" -Method Post -Headers $Headers `
        -ContentType 'application/json' -Body $cfgBody -TimeoutSec 30
    $Rid = $cfg.rustdesk_id
    Log "config: id=$Rid server=$($cfg.id_server) installer=$($cfg.installer_filename)"

    $exe = Join-Path $env:ProgramFiles 'RustDesk\rustdesk.exe'

    # ---- 2. install (skip when the wanted version is already there) --------
    $installed = $null
    try { $installed = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk\' -EA Stop).Version } catch { }
    if ($installed) { $Version = $installed }

    if (-not (Test-Path $exe) -or ($installed -ne $cfg.installer_version)) {
        $pkg = Join-Path $env:TEMP $cfg.installer_filename
        Log "downloading $($cfg.installer_filename) (have '$installed', want '$($cfg.installer_version)')"
        Invoke-WebRequest -Uri "$Base/installer" -Headers $Headers -OutFile $pkg -UseBasicParsing -TimeoutSec 900

        if ($cfg.installer_sha256) {
            $have = (Get-FileHash $pkg -Algorithm SHA256).Hash.ToLower()
            if ($have -ne $cfg.installer_sha256.ToLower()) {
                throw "installer checksum mismatch: got $have, expected $($cfg.installer_sha256)"
            }
        }

        if ($cfg.installer_filename -like '*.msi') {
            # /qn is genuinely silent and returns; the three properties keep the
            # Start Menu, the desktop and the printer list untouched.
            $msiLog = Join-Path $LogDir 'rustdesk-msi.log'
            $msiArgs = @('/i', "`"$pkg`"", '/qn', 'CREATESTARTMENUSHORTCUTS=N',
                      'CREATEDESKTOPSHORTCUTS=N', 'INSTALLPRINTER=N', '/l*v', "`"$msiLog`"")
            $p = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
            if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "msiexec exit $($p.ExitCode), see $msiLog" }
        } else {
            # legacy .exe path: --silent-install never returns, so no -Wait
            Start-Process $pkg -ArgumentList '--silent-install' | Out-Null
            $deadline = (Get-Date).AddMinutes(5)
            while (-not (Test-Path $exe) -and (Get-Date) -lt $deadline) { Start-Sleep 5 }
            if (-not (Test-Path $exe)) { throw 'silent install did not produce rustdesk.exe' }
        }
        Remove-Item $pkg -Force -EA SilentlyContinue
        try { $Version = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk\' -EA Stop).Version } catch { }
        Log "installed version=$Version"
    } else {
        Log "already at $installed - skipping install"
    }
    if (-not (Test-Path $exe)) { throw "RustDesk not present at $exe after install" }
    Report 'installed' ''

    # ---- 3. service --------------------------------------------------------
    if (-not (Get-Service RustDesk -EA SilentlyContinue)) {
        Start-Process $exe -ArgumentList '--install-service' -Wait
        Start-Sleep 5
    }
    function Stop-RD {
        $s = Get-Service RustDesk -EA SilentlyContinue
        if ($s -and $s.Status -ne 'Stopped') {
            try { Stop-Service RustDesk -Force -EA Stop } catch { & sc.exe stop RustDesk | Out-Null }
        }
        Start-Sleep 2
        Get-Process rustdesk -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
        Start-Sleep 2
    }

    # The SYSTEM service reads its config from the systemprofile directory; the
    # LocalService one can hold stale rs-ny.rustdesk.com defaults. Write both.
    $cfgDirs = @(
        (Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config'),
        (Join-Path $env:WINDIR 'System32\config\systemprofile\AppData\Roaming\RustDesk\config')
    )

    function Write-Config([hashtable]$opts) {
        $lines = @("rendezvous_server = '$($cfg.id_server)'", 'nat_type = 1', 'serial = 0', '', '[options]')
        $lines += "custom-rendezvous-server = '$($cfg.id_server)'"
        $lines += "relay-server = '$($cfg.relay_server)'"
        $lines += "api-server = '$($cfg.api_server)'"
        $lines += "key = '$($cfg.key)'"
        foreach ($k in ($opts.Keys | Sort-Object)) { $lines += "$k = '$($opts[$k])'" }
        $toml = ($lines -join "`r`n") + "`r`n"
        foreach ($d in $cfgDirs) {
            $null = New-Item -ItemType Directory -Force -Path $d
            Set-Content (Join-Path $d 'RustDesk2.toml') $toml -Encoding UTF8
            # keep everything except the id line, then put our id back on top
            $idf = Join-Path $d 'RustDesk.toml'
            $keep = @()
            if (Test-Path $idf) { $keep = Get-Content $idf | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' } }
            Set-Content $idf (@("id = '$Rid'") + $keep) -Encoding UTF8
        }
    }

    # ---- 4. first pass: working config, no write locks ---------------------
    $opts = @{}
    foreach ($p in $cfg.options.PSObject.Properties) { $opts[$p.Name] = $p.Value }
    Stop-RD
    Write-Config $opts
    try { Start-Service RustDesk } catch { & sc.exe start RustDesk | Out-Null }
    Start-Sleep 6
    Log 'server + id written'

    # ---- 5. permanent password (must precede the locks) --------------------
    if ($cfg.permanent_password) {
        & $exe --password $cfg.permanent_password
        # a flat 5s sleep was a race on slow/loaded hardware - caught live on
        # VNA-MGR-04 right after an MSI install: the password had actually
        # landed, just a few seconds after this check already gave up and
        # reported "failed". Poll instead of a single fixed wait.
        $ok = $false
        $deadline = (Get-Date).AddSeconds(30)
        while (-not $ok -and (Get-Date) -lt $deadline) {
            Start-Sleep 2
            foreach ($d in $cfgDirs) {
                $rd = Join-Path $d 'RustDesk.toml'
                if ((Get-Content $rd -EA SilentlyContinue) -match "^\s*password\s*=\s*'.+'") { $ok = $true }
            }
        }
        if ($ok) { Log 'password set + verified' }
        else { throw 'password did not persist to RustDesk.toml' }
    }

    # ---- 6. second pass: same config plus the write locks ------------------
    if ($cfg.lock_options) {
        foreach ($p in $cfg.lock_options.PSObject.Properties) { $opts[$p.Name] = $p.Value }
        Write-Config $opts
        try { Restart-Service RustDesk -EA Stop } catch { }
        Log 'config locked'
    }

    # ---- 7. keep it out of the user's way ----------------------------------
    if ($cfg.hidden) {
        $links = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs\RustDesk.lnk",
                   "$env:PUBLIC\Desktop\RustDesk.lnk")
        Get-ChildItem 'C:\Users' -Directory -EA SilentlyContinue | ForEach-Object {
            $links += "$($_.FullName)\Desktop\RustDesk.lnk"
            $links += "$($_.FullName)\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\RustDesk.lnk"
        }
        foreach ($l in $links) { if (Test-Path $l) { Remove-Item $l -Force -EA SilentlyContinue } }
        Log 'shortcuts removed'
    }

    if ($cfg.block_outgoing) {
        # AppLocker: non-admins cannot start rustdesk.exe interactively. The
        # SYSTEM service instance is unaffected, so incoming sessions still work.
        # Rule Id must be a real GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx, hex
        # only) - Set-AppLockerPolicy validates the XML against that schema and
        # rejects the whole policy on a bad one. Caught live on VNA-MGR-15: the
        # earlier "...infrascope01" id has letters outside a-f, so every prior
        # rollout (this script and the offline rustdesk-ksc/configure.ps1) that
        # asked for block_outgoing silently never got it - "AppLocker step
        # skipped" in the log, with no indication it was a fixable bug.
        try {
            Set-Service AppIDSvc -StartupType Automatic -EA SilentlyContinue
            Start-Service AppIDSvc -EA SilentlyContinue
            $xml = @"
<AppLockerPolicy Version="1">
  <RuleCollection Type="Exe" EnforcementMode="Enabled">
    <FilePathRule Id="e1f7a1a0-0000-4000-8000-000000000001" Name="InfraScope: allow RustDesk for admins" Description="" UserOrGroupSid="S-1-5-32-544" Action="Allow">
      <Conditions><FilePathCondition Path="%PROGRAMFILES%\RustDesk\*"/></Conditions>
    </FilePathRule>
    <FilePathRule Id="e1f7a1a0-0000-4000-8000-000000000002" Name="InfraScope: deny RustDesk for users" Description="" UserOrGroupSid="S-1-1-0" Action="Deny">
      <Conditions><FilePathCondition Path="%PROGRAMFILES%\RustDesk\*"/></Conditions>
    </FilePathRule>
    <FilePathRule Id="e1f7a1a0-0000-4000-8000-000000000003" Name="(default) allow everything else" Description="" UserOrGroupSid="S-1-1-0" Action="Allow">
      <Conditions><FilePathCondition Path="*"/></Conditions>
    </FilePathRule>
  </RuleCollection>
</AppLockerPolicy>
"@
            $tmp = Join-Path $LogDir 'rustdesk-applocker.xml'
            Set-Content $tmp $xml -Encoding UTF8
            Set-AppLockerPolicy -XmlPolicy $tmp -Merge -EA Stop
            Log 'AppLocker deny rule applied'
        } catch { Log "AppLocker step skipped: $($_.Exception.Message)" }
    }

    Report 'configured' ''
    Log '=== deploy done ==='
} catch {
    $msg = $_.Exception.Message
    Log "FAILED: $msg"
    Report 'failed' $msg
    exit 1
}
"""
