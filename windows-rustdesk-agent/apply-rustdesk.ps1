<#
    apply-rustdesk.ps1 - runs ON the target as SYSTEM (pushed + invoked by the
    InfraScope deploy agent). Reads C:\ProgramData\InfraScope\rustdesk\job.json.

    Does: silent install (if missing) -> service -> RustDesk2.toml (self-host
    server + key + hostname ID + covert flags) -> lockdown (strip shortcuts,
    AppLocker deny non-admin interactive launch). Does NOT set the permanent
    password - the agent does that over CIM in an admin context afterwards,
    because RustDesk only persists it from an elevated interactive session.
#>
$ErrorActionPreference = 'Stop'
$dir = 'C:\ProgramData\InfraScope\rustdesk'
$log = Join-Path $dir 'apply.log'
function Log($m) { Add-Content $log ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m) }
$j = Get-Content (Join-Path $dir 'job.json') -Raw | ConvertFrom-Json
Log "=== apply start: action=$($j.action) id=$($j.rustdesk_id) ==="

$exe = 'C:\Program Files\RustDesk\rustdesk.exe'
function Stop-RD {
    $s = Get-Service RustDesk -EA SilentlyContinue
    if ($s -and $s.Status -ne 'Stopped') { try { Stop-Service RustDesk -Force -EA Stop } catch { & sc.exe stop RustDesk | Out-Null } }
    Start-Sleep 2
    Get-Process rustdesk -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
}

if ($j.action -eq 'uninstall') {
    if (Test-Path $exe) { Start-Process $exe -ArgumentList '--uninstall'; Start-Sleep 20 }
    Log 'uninstalled'; return
}

# ---- install ------------------------------------------------------------
if (-not (Test-Path $exe) -and $j.action -ne 'set_lockdown') {
    $src = Join-Path $dir $j.installer
    if (-not (Test-Path $src)) { throw "installer missing: $src" }
    Log "installing $($j.installer)"
    Start-Process -FilePath $src -ArgumentList '--silent-install'
    for ($i = 0; $i -lt 60 -and -not ((Test-Path $exe) -and (Get-Service RustDesk -EA SilentlyContinue)); $i++) { Start-Sleep 3 }
    if (-not (Test-Path $exe)) { throw 'install did not complete' }
    Start-Sleep 10
}
if (-not (Get-Service RustDesk -EA SilentlyContinue)) { Start-Process $exe -ArgumentList '--install-service' -Wait; Start-Sleep 3 }

# ---- config -----------------------------------------------------------
if ($j.action -ne 'set_lockdown') {
    $toml = @"
rendezvous_server = '$($j.id_server)'
nat_type = 1
serial = 0

[options]
custom-rendezvous-server = '$($j.id_server)'
relay-server = '$($j.relay_server)'
api-server = 'http://$($j.id_server):21114'
key = '$($j.key)'
enable-check-update = 'N'
"@
    if ($j.hidden)     { $toml += "hide-tray = 'Y'`r`nallow-hide-cm = 'Y'`r`n" }
    if ($j.unattended) { $toml += "approve-mode = 'password'`r`nverification-method = 'use-permanent-password'`r`n" }

    $cfg = @(
        (Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk2.toml'),
        (Join-Path $env:WINDIR 'System32\config\systemprofile\AppData\Roaming\RustDesk\config\RustDesk2.toml')
    )
    Stop-RD
    foreach ($t in $cfg) {
        $idf = $t -replace 'RustDesk2\.toml$', 'RustDesk.toml'
        $lines = @()
        if (Test-Path $idf) { $lines = Get-Content $idf | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' } }
        if ($j.rustdesk_id) { $lines = @("id = '$($j.rustdesk_id)'") + $lines }
        $null = New-Item -ItemType Directory -Force -Path (Split-Path $idf)
        Set-Content $idf $lines -Encoding UTF8
        $null = New-Item -ItemType Directory -Force -Path (Split-Path $t)
        Set-Content $t $toml -Encoding UTF8
    }
    try { Start-Service RustDesk } catch { & sc.exe start RustDesk | Out-Null }
    Start-Sleep 6
    Log "config written (id=$($j.rustdesk_id) hidden=$($j.hidden) unattended=$($j.unattended))"
}

# ---- lockdown -------------------------------------------------------
if ($j.hidden) {
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
    Log 'shortcuts removed'
}
if ($j.block_outgoing) {
    # AppLocker EXE deny for Everyone, allowed back only for BUILTIN\Administrators.
    # Blocks a store user from launching rustdesk.exe interactively (=no outgoing);
    # the service instance is unaffected (runs as SYSTEM, not via AppLocker user rules
    # for interactive launch). Requires the Application Identity service (set to auto).
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
        $tmp = Join-Path $dir 'applocker.xml'; Set-Content $tmp $xml -Encoding UTF8
        Set-AppLockerPolicy -XmlPolicy $tmp -Merge -EA Stop
        Log 'AppLocker deny rule applied (non-admin interactive rustdesk.exe blocked)'
    } catch { Log "AppLocker step skipped: $($_.Exception.Message)" }
}
Log "=== apply done ==="
