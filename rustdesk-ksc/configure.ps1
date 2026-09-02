<#
    configure.ps1 - RustDesk post-install step, run ON the endpoint by Kaspersky
    Security Center (Application -> Installation package -> "Run after install").

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

# ---- server + id config -------------------------------------------------
$toml = @"
rendezvous_server = '$idServer'
nat_type = 1
serial = 0

[options]
custom-rendezvous-server = '$idServer'
relay-server = '$relay'
api-server = '$apiServer'
key = '$key'
enable-check-update = 'N'
"@
if ($hidden)     { $toml += "hide-tray = 'Y'`r`nallow-hide-cm = 'Y'`r`n" }
if ($unattended) { $toml += "approve-mode = 'password'`r`nverification-method = 'use-permanent-password'`r`n" }

$cfgFiles = @(
    (Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk2.toml'),
    (Join-Path $env:WINDIR 'System32\config\systemprofile\AppData\Roaming\RustDesk\config\RustDesk2.toml')
)
Stop-RD
foreach ($t in $cfgFiles) {
    $idf = $t -replace 'RustDesk2\.toml$', 'RustDesk.toml'
    $lines = @()
    if (Test-Path $idf) { $lines = Get-Content $idf | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' } }
    $lines = @("id = '$rid'") + $lines
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $idf)
    Set-Content $idf $lines -Encoding UTF8
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $t)
    Set-Content $t $toml -Encoding UTF8
}
try { Start-Service RustDesk } catch { & sc.exe start RustDesk | Out-Null }
Start-Sleep 6
Log "server + id written"

# ---- permanent password ----------------------------------------------
if ($unattended -and $pw) {
    & $exe --password $pw
    Start-Sleep 5
    $rdToml = Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk.toml'
    if ((Get-Content $rdToml -EA SilentlyContinue) -match "^\s*password\s*=\s*'.+'") {
        Log "password set + verified"
    } else {
        Log "WARN: password did not persist to RustDesk.toml - set it manually (elevated): `"$exe`" --password <pw>"
    }
}

# ---- lockdown -------------------------------------------------------
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
    try {
        Set-Service AppIDSvc -StartupType Automatic -EA SilentlyContinue
        Start-Service AppIDSvc -EA SilentlyContinue
        $xml = @"
<AppLockerPolicy Version="1">
  <RuleCollection Type="Exe" EnforcementMode="Enabled">
    <FilePathRule Id="e1f7a1a0-0000-0000-0000-infrascope01" Name="InfraScope: allow RustDesk for admins" Description="" UserOrGroupSid="S-1-5-32-544" Action="Allow">
      <Conditions><FilePathCondition Path="%PROGRAMFILES%\RustDesk\*"/></Conditions>
    </FilePathRule>
    <FilePathRule Id="e1f7a1a0-0000-0000-0000-infrascope02" Name="InfraScope: deny RustDesk for users" Description="" UserOrGroupSid="S-1-1-0" Action="Deny">
      <Conditions><FilePathCondition Path="%PROGRAMFILES%\RustDesk\*"/></Conditions>
    </FilePathRule>
    <FilePathRule Id="e1f7a1a0-0000-0000-0000-infrascope03" Name="(default) allow everything else" Description="" UserOrGroupSid="S-1-1-0" Action="Allow">
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
