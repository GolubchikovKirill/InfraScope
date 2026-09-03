<#
    configure.ps1 - RustDesk post-install step for the OFFLINE rollout path,
    run ON the endpoint by Kaspersky Security Center ("Run after install").

    Prefer the online path when the machine can reach InfraScope over HTTP: it
    fetches the same config at run time and reports the result back, so a
    password rotation needs no new package. See docs/rustdesk-ksc-deployment.md.
    This script exists for machines that cannot.

    Points an already-installed RustDesk at the self-hosted server, sets the
    hostname-based ID, applies the permanent password, and (optionally) the
    lockdown (hide tray + strip shortcuts + AppLocker deny non-admin launch).

    Config comes from rustdesk-ksc.json placed next to this script inside the KSC
    package, OR from -Param overrides. InfraScope renders the per-machine values:
    GET /api/v1/remote-access/devices/{id}/package  ->  those keys 1:1.

    Idempotent: safe to run on every KSC deployment / repair.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'rustdesk-ksc.json'),
    [string]$RustdeskId,          # overrides config; default = hostname sanitised to [A-Za-z0-9_]
    [string]$Password,            # overrides config
    [switch]$NoLockdown
)

$ErrorActionPreference = 'Stop'
$logDir = 'C:\ProgramData\InfraScope'
$null = New-Item -ItemType Directory -Force -Path $logDir
$log = Join-Path $logDir 'rustdesk-configure.log'
function Log($m) { Add-Content $log ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m) }

$cfg = @{}
if (Test-Path $ConfigPath) { $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json }

$idServer   = $cfg.id_server
$relay      = if ($cfg.relay_server) { $cfg.relay_server } else { $cfg.id_server }
$apiServer  = if ($cfg.api_server) { $cfg.api_server } else { "http://$($cfg.id_server):21114" }
$key        = $cfg.key
$rid        = if ($RustdeskId) { $RustdeskId } elseif ($cfg.rustdesk_id) { $cfg.rustdesk_id } else {
                 -join ([char[]]$env:COMPUTERNAME | ForEach-Object { if ($_ -match '[A-Za-z0-9]') { $_ } else { '_' } }) }
$pw         = if ($Password) { $Password } else { $cfg.permanent_password }
$hidden     = [bool]($cfg.hidden)
$block      = [bool]($cfg.block_outgoing)
$unattended = if ($null -ne $cfg.unattended) { [bool]$cfg.unattended } else { $true }

if (-not $idServer -or -not $key) { throw "config incomplete: need id_server and key (got '$idServer')" }
Log "=== configure: id=$rid server=$idServer hidden=$hidden block=$block ==="

$exe = 'C:\Program Files\RustDesk\rustdesk.exe'
if (-not (Test-Path $exe)) { throw "RustDesk not installed at $exe - the KSC package must install it first" }
if (-not (Get-Service RustDesk -EA SilentlyContinue)) {
    Start-Process $exe -ArgumentList '--install-service' -Wait; Start-Sleep 3
}

function Stop-RD {
    $s = Get-Service RustDesk -EA SilentlyContinue
    if ($s -and $s.Status -ne 'Stopped') { try { Stop-Service RustDesk -Force -EA Stop } catch { & sc.exe stop RustDesk | Out-Null } }
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

# `[options]` keys, mirroring app/domains/remote_access/deploy_script.py.
# allow-logon-screen-password is what lets an engineer in when the store PC sits
# at the lock screen; without it a locked machine refuses the permanent password.
function Write-Config([bool]$WithLocks) {
    $lines = @("rendezvous_server = '$idServer'", 'nat_type = 1', 'serial = 0', '', '[options]')
    $lines += "custom-rendezvous-server = '$idServer'"
    $lines += "relay-server = '$relay'"
    $lines += "api-server = '$apiServer'"
    $lines += "key = '$key'"
    $lines += "enable-check-update = 'N'"
    $lines += "enable-lan-discovery = 'N'"
    $lines += "direct-server = 'N'"
    $lines += "allow-logon-screen-password = 'Y'"
    $lines += "remove-preset-password-warning = 'Y'"
    $lines += "hide-help-cards = 'Y'"
    if ($hidden) {
        $lines += "hide-tray = 'Y'"
        $lines += "hide-stop-service = 'Y'"
        $lines += "allow-hide-cm = 'Y'"
        $lines += "hide-security-settings = 'Y'"
        $lines += "hide-network-settings = 'Y'"
        $lines += "hide-server-settings = 'Y'"
    }
    if ($unattended) {
        $lines += "approve-mode = 'password'"
        $lines += "verification-method = 'use-permanent-password'"
    }
    # These block `--password` and `--id`, so they only go on the second pass.
    if ($WithLocks) {
        $lines += "disable-change-permanent-password = 'Y'"
        $lines += "disable-change-id = 'Y'"
    }
    $toml = ($lines -join "`r`n") + "`r`n"
    foreach ($d in $cfgDirs) {
        $null = New-Item -ItemType Directory -Force -Path $d
        Set-Content (Join-Path $d 'RustDesk2.toml') $toml -Encoding UTF8
        $idf = Join-Path $d 'RustDesk.toml'
        $keep = @()
        if (Test-Path $idf) { $keep = Get-Content $idf | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' } }
        Set-Content $idf (@("id = '$rid'") + $keep) -Encoding UTF8
    }
}

# ---- pass 1: working config, no write locks -----------------------------
Stop-RD
Write-Config $false
try { Start-Service RustDesk } catch { & sc.exe start RustDesk | Out-Null }
Start-Sleep 6
Log "server + id written"

# ---- permanent password (must precede the locks) ------------------------
$passwordOk = $false
if ($unattended -and $pw) {
    & $exe --password $pw
    Start-Sleep 5
    foreach ($d in $cfgDirs) {
        $rdToml = Join-Path $d 'RustDesk.toml'
        if ((Get-Content $rdToml -EA SilentlyContinue) -match "^\s*password\s*=\s*'.+'") { $passwordOk = $true }
    }
    if ($passwordOk) {
        Log "password set + verified"
    } else {
        Log "WARN: password did not persist to RustDesk.toml - set it manually (elevated): `"$exe`" --password <pw>"
    }
}

# ---- pass 2: same config plus the write locks ---------------------------
# Skipped when the password never landed, or the machine would be left both
# unreachable (no password) and unfixable (locked).
if ($unattended -and $passwordOk) {
    Write-Config $true
    try { Restart-Service RustDesk -EA Stop } catch { }
    Log "config locked"
}

# ---- lockdown -----------------------------------------------------------
if (-not $NoLockdown -and $hidden) {
    foreach ($lnk in @(
        "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\RustDesk.lnk",
        "$env:PUBLIC\Desktop\RustDesk.lnk")) { if (Test-Path $lnk) { Remove-Item $lnk -Force -EA SilentlyContinue } }
    Get-ChildItem 'C:\Users' -Directory -EA SilentlyContinue | ForEach-Object {
        foreach ($lnk in @(
            "$($_.FullName)\Desktop\RustDesk.lnk",
            "$($_.FullName)\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\RustDesk.lnk")) {
            if (Test-Path $lnk) { Remove-Item $lnk -Force -EA SilentlyContinue }
        }
    }
    Log "shortcuts removed"
}
if (-not $NoLockdown -and $block) {
    # AppLocker: deny interactive rustdesk.exe for Everyone, allow back for BUILTIN\Administrators.
    # The service instance (SYSTEM) is unaffected. Needs the Application Identity service.
    # Rule Id must be a real GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx, hex only) -
    # Set-AppLockerPolicy validates the XML against that schema and rejects the
    # whole policy on a bad one. The previous "...infrascope01" id has letters
    # outside a-f, so block_outgoing silently never applied on any machine this
    # ran on - caught live on VNA-MGR-15 via app/domains/remote_access/deploy_script.py.
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
        $tmp = Join-Path $logDir 'rustdesk-applocker.xml'; Set-Content $tmp $xml -Encoding UTF8
        Set-AppLockerPolicy -XmlPolicy $tmp -Merge -EA Stop
        Log "AppLocker deny rule applied"
    } catch { Log "AppLocker step skipped: $($_.Exception.Message)" }
}
Log "=== configure done ==="
