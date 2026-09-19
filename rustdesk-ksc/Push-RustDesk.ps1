<#
    Push-RustDesk.ps1 - roll RustDesk out to Windows 7 and Windows 10/11 machines
    from an ADMIN WORKSTATION, with no reboot of the target, ever.

    Why this exists next to the pull rollout (docs/rustdesk-ksc-deployment.md):
    the pull bootstrap needs TLS 1.2 to reach InfraScope, which Windows 7 with
    PowerShell 2.0 / .NET 2.0 cannot do, and it needs a trigger (KSC / GPO /
    schtasks). This tool pushes over what an admin already has: the C$ admin
    share and WMI/DCOM (no WinRM, no PsExec, no scheduled task, no service is
    created on the target). It runs on YOUR machine, not on the InfraScope
    server - the server never remote-executes on the fleet, by design.

    What it does per machine:
      1. probes the OS over WMI (caption, version, bitness, RustDesk service);
      2. skips Windows XP (RustDesk does not run there);
      3. copies endpoint\Install-RustDesk.ps1, a per-profile rustdesk-ksc.json
         and the right installer into C:\Windows\Temp\RustDesk-Deploy:
             Windows 10/11 x64 -> *.msi   (msiexec /qn /norestart)
             Windows 7 / 32-bit -> 32-bit sciter *.exe (--silent-install)
      4. starts the script through Win32_Process.Create and waits for it;
      5. if the RPC dropped mid-run (seen on Windows 7) it looks at the log
         and re-runs once - the script is idempotent;
      6. checks the RustDesk service is Running and the log ends in OK;
      7. deletes the staging folder (use -KeepFiles to leave it).
    Nothing here reboots a machine: a pending-reboot flag on the target is
    deliberately ignored, and no Windows update / WMF / .NET is ever installed.

    Profiles (the three flags in rustdesk-ksc.json are overridden per run):
      client  till / kiosk / office PC: tray hidden, permanent password only
      admin   engineer workstation (ITD-SA*): tray visible, accept prompt,
              no permanent password, no lock

    Needs, next to this script:
      rustdesk-ksc.json                 copy of rustdesk-ksc.example.json with
                                        the real hbbs key and password
      packages\rustdesk-*-x86_64.msi    installer for Windows 10/11
      packages\rustdesk-*-x86-sciter.exe installer for Windows 7 / 32-bit
    (installers are not in git; see packages\README.md)

    Examples:
      .\Push-RustDesk.ps1 -ComputerName VNK-KKM-3301,VNK-KKM-3302
      .\Push-RustDesk.ps1 -ListFile .\targets.txt -Profile client
      .\Push-RustDesk.ps1 -ComputerName VNK-ITD-SA04 -Profile admin
      .\Push-RustDesk.ps1 -ComputerName VNA-KKM-701 -DryRun
#>
[CmdletBinding()]
param(
    [string[]]$ComputerName,
    [string]$ListFile,
    [ValidateSet('client', 'admin')][string]$Profile = 'client',
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'rustdesk-ksc.json'),
    [string]$PackageDir = (Join-Path $PSScriptRoot 'packages'),
    [int]$TimeoutMinutes = 8,
    [switch]$KeepFiles,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$endpointScript = Join-Path $PSScriptRoot 'endpoint\Install-RustDesk.ps1'
$stage = 'C:\Windows\Temp\RustDesk-Deploy'

$targets = @()
if ($ComputerName) { $targets += $ComputerName }
if ($ListFile) { $targets += Get-Content $ListFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') } }
$targets = $targets | Select-Object -Unique
if (-not $targets) { throw 'Give -ComputerName and/or -ListFile.' }
if (-not (Test-Path $endpointScript)) { throw "Missing $endpointScript" }
if (-not (Test-Path $ConfigPath)) { throw "Missing $ConfigPath - copy rustdesk-ksc.example.json and fill in the key and password." }

# per-profile config: only the three flags change, everything else is the fleet config
$cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$cfg | Add-Member -NotePropertyName hidden -NotePropertyValue ($Profile -eq 'client') -Force
$cfg | Add-Member -NotePropertyName unattended -NotePropertyValue ($Profile -eq 'client') -Force
$cfg | Add-Member -NotePropertyName block_outgoing -NotePropertyValue $false -Force
$msiName = if ($cfg.installer_msi) { $cfg.installer_msi } else { 'rustdesk-1.4.9-x86_64.msi' }
$exeName = if ($cfg.installer_exe32) { $cfg.installer_exe32 } else { 'rustdesk-1.4.9-x86-sciter.exe' }
$stageCfg = Join-Path ([IO.Path]::GetTempPath()) ("rustdesk-ksc-" + [guid]::NewGuid().ToString('N') + '.json')
$cfg | ConvertTo-Json -Depth 5 | Set-Content $stageCfg -Encoding UTF8

function Read-Log($unc) {
    if (Test-Path $unc) { return @(Get-Content $unc -ErrorAction SilentlyContinue) }
    return @()
}

function Invoke-OneHost([string]$h) {
    $row = [ordered]@{ Host = $h; OS = ''; Path = ''; Result = ''; Detail = '' }
    $cs = $null
    try {
        $cs = New-CimSession -ComputerName $h -SessionOption (New-CimSessionOption -Protocol Dcom) -OperationTimeoutSec 30 -ErrorAction Stop
        $os = Get-CimInstance -CimSession $cs Win32_OperatingSystem
        $cpu = Get-CimInstance -CimSession $cs Win32_Processor | Select-Object -First 1
        $svc = Get-CimInstance -CimSession $cs Win32_Service -Filter "Name='RustDesk'"
        $major = [int]($os.Version.Split('.')[0])
        $legacy = ($major -lt 10) -or ($cpu.AddressWidth -ne 64)
        $row.OS = "$($os.Caption -replace 'Майкрософт |Microsoft ','') ($($os.Version), $($cpu.AddressWidth)-bit)"
        if ($major -lt 6) { $row.Result = 'SKIPPED'; $row.Detail = 'Windows XP: RustDesk is not supported'; return [pscustomobject]$row }
        $installerName = if ($legacy) { $exeName } else { $msiName }
        $row.Path = if ($legacy) { "legacy 32-bit ($installerName)" } else { "msi ($installerName)" }
        $installer = Join-Path $PackageDir $installerName
        if (-not (Test-Path $installer)) { $row.Result = 'FAILED'; $row.Detail = "installer missing: $installer"; return [pscustomobject]$row }
        if ($DryRun) { $row.Result = 'DRY-RUN'; $row.Detail = "RustDesk service: $(if ($svc) { $svc.State } else { 'absent' }); would push profile '$Profile'"; return [pscustomobject]$row }

        $dst = "\\$h\C$\Windows\Temp\RustDesk-Deploy"
        $null = New-Item -ItemType Directory -Force -Path $dst
        Copy-Item $endpointScript (Join-Path $dst 'Install-RustDesk.ps1') -Force
        Copy-Item $stageCfg (Join-Path $dst 'rustdesk-ksc.json') -Force
        Copy-Item $installer (Join-Path $dst $installerName) -Force
        $logUnc = Join-Path $dst 'install.log'
        Remove-Item $logUnc -ErrorAction SilentlyContinue

        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stage\Install-RustDesk.ps1"
        for ($attempt = 1; $attempt -le 2; $attempt++) {
            $r = Invoke-CimMethod -CimSession $cs -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
            if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create returned $($r.ReturnValue)" }
            $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
            $gone = $false
            while ((Get-Date) -lt $deadline) {
                Start-Sleep 5
                try {
                    if (-not (Get-CimInstance -CimSession $cs Win32_Process -Filter "ProcessId=$($r.ProcessId)" -ErrorAction Stop)) { $gone = $true; break }
                } catch { $gone = $true; break }   # RPC dropped: judge by the log below
            }
            $log = Read-Log $logUnc
            if ($log -match '\bDONE\b') { break }
            if ($attempt -eq 1) { Write-Host "  $h : no DONE in the log (RPC hiccup?) - re-running once" -ForegroundColor Yellow; Start-Sleep 10 }
        }

        $log = Read-Log $logUnc
        $last = ($log | Where-Object { $_ -match '\b(OK|WARN|FAIL|UNSUPPORTED)\b' } | Select-Object -Last 1)
        $svcNow = Get-CimInstance -CimSession $cs Win32_Service -Filter "Name='RustDesk'"
        $row.Detail = ("$last" -replace '^\S+ \S+\s+', '') + " | service: $(if ($svcNow) { "$($svcNow.State)/$($svcNow.StartMode)" } else { 'absent' })"
        if ($last -match '\bOK\b' -and $svcNow.State -eq 'Running') { $row.Result = 'OK' }
        elseif ($last -match '\bWARN\b' -and $svcNow.State -eq 'Running') { $row.Result = 'WARN' }
        else { $row.Result = 'FAILED' }
        if (-not $KeepFiles -and $row.Result -ne 'FAILED') {
            try { [IO.Directory]::Delete($dst, $true) } catch { $row.Detail += ' | staging folder not removed: ' + $_.Exception.Message.Split("`n")[0] }
        }
    } catch {
        $row.Result = 'FAILED'
        $row.Detail = $_.Exception.Message.Split("`n")[0]
    } finally {
        if ($cs) { Remove-CimSession $cs -ErrorAction SilentlyContinue }
    }
    return [pscustomobject]$row
}

Write-Host "Profile: $Profile | targets: $($targets.Count) | dry-run: $DryRun" -ForegroundColor Cyan
$results = foreach ($h in $targets) {
    Write-Host "-> $h" -ForegroundColor Cyan
    Invoke-OneHost $h
}
Remove-Item $stageCfg -ErrorAction SilentlyContinue
Write-Host ''
foreach ($r in $results) {
    $color = switch ($r.Result) { 'OK' { 'Green' } 'DRY-RUN' { 'Cyan' } 'WARN' { 'Yellow' } 'SKIPPED' { 'DarkGray' } default { 'Red' } }
    Write-Host ("{0,-8} {1}" -f $r.Result, $r.Host) -ForegroundColor $color
    Write-Host ("         {0}  [{1}]" -f $r.OS, $r.Path)
    if ($r.Detail) { Write-Host ("         {0}" -f $r.Detail) }
}
$failed = @($results | Where-Object { $_.Result -eq 'FAILED' }).Count
if ($failed) { Write-Host "$failed host(s) FAILED - see Detail; staging folders of failed hosts were kept for inspection." -ForegroundColor Red; exit 1 }
