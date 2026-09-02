<#
    InfraScope RustDesk deploy agent.

    Runs on ONE domain-joined Windows box that has local admin on the fleet
    (same rights you use by hand). Polls InfraScope for deploy jobs and applies
    them to the job's target hostname over SMB + CIM/DCOM - no WinRM needed.

    Config: rustdesk-agent.json next to this file
      { "server": "http://10.10.98.10", "agent_id": "deploy01",
        "token": "<RUSTDESK_DEPLOY_AGENT_TOKEN>", "poll_seconds": 15,
        "installer_dir": "\\\\domain\\NETLOGON\\RustDesk" }

    install-rustdesk-agent.cmd registers it as a scheduled task (SYSTEM, at boot).
#>
[CmdletBinding()]
param([string]$ConfigPath = (Join-Path $PSScriptRoot 'rustdesk-agent.json'))

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $ConfigPath)) { throw "config not found: $ConfigPath" }
$cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$Server   = $cfg.server.TrimEnd('/')
$AgentId  = $cfg.agent_id
$Token    = $cfg.token
$Poll     = [int]($cfg.poll_seconds); if ($Poll -lt 5) { $Poll = 15 }
$InstDir  = if ($cfg.installer_dir) { $cfg.installer_dir } else { $PSScriptRoot }
$Base     = "$Server/api/v1/remote-access/agent"
$Headers  = @{ 'X-Deploy-Agent-Token' = $Token }
$RdExe    = 'C:\Program Files\RustDesk\rustdesk.exe'

function Log($m) { Write-Host ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m) }

# --------------------------------------------------------------------------- #
# per-target primitives (over \\host\C$ + CIM Win32_Process)                  #
# --------------------------------------------------------------------------- #
function Test-Tcp($h, $p, $ms = 3000) {
    try { $c = [Net.Sockets.TcpClient]::new(); $a = $c.BeginConnect($h, $p, $null, $null)
        $ok = $a.AsyncWaitHandle.WaitOne($ms); if ($ok) { $c.EndConnect($a) }; $c.Close(); return $ok } catch { return $false }
}
function New-Cim($h) { New-CimSession -ComputerName $h -SessionOption (New-CimSessionOption -Protocol Dcom) -EA Stop }
function Invoke-Remote($cs, $cmdline) {
    (Invoke-CimMethod -CimSession $cs -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdline }).ReturnValue
}
function Remote-RustDeskInstalled($h) { Test-Path "\\$h\C$\Program Files\RustDesk\rustdesk.exe" }

function Deploy-Client {
    param($h, $job)
    $p = $job.params
    $inst = Get-ChildItem $InstDir -Filter 'rustdesk-*-x86_64.exe' -EA SilentlyContinue | Select-Object -First 1
    if (-not $inst) { throw "no rustdesk installer in $InstDir" }
    $dst = "\\$h\C$\ProgramData\InfraScope\rustdesk"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item $inst.FullName $dst -Force
    Copy-Item (Join-Path $PSScriptRoot 'apply-rustdesk.ps1') $dst -Force

    # write a job manifest the on-box script reads (kept local to the target, no secrets in transit logs)
    $manifest = [ordered]@{
        rustdesk_id    = $job.rustdesk_id
        id_server      = $job.id_server
        relay_server   = $job.relay_server
        key            = $job.key
        installer      = $inst.Name
        hidden         = [bool]$job.desired_hidden
        block_outgoing = [bool]$job.desired_block_outgoing
        unattended     = [bool]$job.desired_unattended
        action         = $job.action
    }
    ($manifest | ConvertTo-Json) | Set-Content "$dst\job.json" -Encoding UTF8

    $cs = New-Cim $h
    try {
        # 1) install + config + lockdown, as SYSTEM
        $rc = Invoke-Remote $cs ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File " +
            "C:\ProgramData\InfraScope\rustdesk\apply-rustdesk.ps1")
        Start-Sleep 90
        # 2) permanent password - MUST be set as an admin in an interactive-ish
        #    context; CIM Win32_Process runs as this agent's account (fleet admin),
        #    which is the combo that actually persists it.
        if ($job.desired_unattended) {
            $sec = Invoke-RestMethod -Method Get -Uri "$Base/jobs/$($job.job_id)/secret" -Headers $Headers -TimeoutSec 30
            $pw = $sec.permanent_password
            if ($pw) {
                Invoke-Remote $cs ('cmd /c ""{0}" --password {1}"' -f $RdExe, $pw) | Out-Null
                Start-Sleep 15
            }
        }
    } finally { Remove-CimSession $cs }

    if (-not (Remote-RustDeskInstalled $h)) { throw "rustdesk.exe still absent after apply" }
    $ver = (Get-Item "\\$h\C$\Program Files\RustDesk\rustdesk.exe" -EA SilentlyContinue).VersionInfo.FileVersion
    return @{ installed_version = $ver; rustdesk_id = $job.rustdesk_id; deploy_state = 'configured' }
}

function Rotate-Password {
    param($h, $job)
    if (-not (Remote-RustDeskInstalled $h)) { throw "rustdesk not installed" }
    $sec = Invoke-RestMethod -Method Get -Uri "$Base/jobs/$($job.job_id)/secret" -Headers $Headers -TimeoutSec 30
    $pw = $sec.permanent_password
    if (-not $pw) { throw "server returned empty password" }
    $cs = New-Cim $h
    try { Invoke-Remote $cs ('cmd /c ""{0}" --password {1}"' -f $RdExe, $pw) | Out-Null } finally { Remove-CimSession $cs }
    Start-Sleep 15
    $f = "\\$h\C$\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\RustDesk.toml"
    $ok = ((Get-Content $f -EA SilentlyContinue) -match "^\s*password\s*=\s*'.+'")
    if (-not $ok) { throw "password hash did not persist (no admin/interactive session on target?)" }
    return @{ deploy_state = 'configured' }
}

function Uninstall-Client {
    param($h, $job)
    if (Remote-RustDeskInstalled $h) {
        $cs = New-Cim $h
        try { Invoke-Remote $cs ('cmd /c ""{0}" --uninstall"' -f $RdExe) | Out-Null } finally { Remove-CimSession $cs }
        Start-Sleep 20
    }
    return @{ deploy_state = 'not_installed' }
}

# --------------------------------------------------------------------------- #
# main loop                                                                   #
# --------------------------------------------------------------------------- #
function Report($jobId, $status, $detail, $facts) {
    $body = @{ status = $status; detail = $detail }
    if ($facts) { $facts.GetEnumerator() | ForEach-Object { $body[$_.Key] = $_.Value } }
    try { Invoke-RestMethod -Method Post -Uri "$Base/jobs/$jobId/report" -Headers $Headers `
            -Body ($body | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 30 | Out-Null }
    catch { Log "report failed: $($_.Exception.Message)" }
}

Log "agent $AgentId -> $Server (poll ${Poll}s, installers: $InstDir)"
while ($true) {
    try {
        $job = Invoke-RestMethod -Method Post -Uri "$Base/claim?agent_id=$AgentId" -Headers $Headers -TimeoutSec 30
    } catch { Log "claim failed: $($_.Exception.Message)"; Start-Sleep $Poll; continue }

    if (-not $job -or -not $job.job_id) { Start-Sleep $Poll; continue }
    $h = $job.hostname
    Log "job $($job.job_id) $($job.action) -> $h"
    Report $job.job_id 'running' $null $null

    try {
        if (-not (Test-Tcp $h 445)) { throw "target unreachable on 445" }
        $facts = switch ($job.action) {
            'deploy'          { Deploy-Client   $h $job }
            'reconfigure'     { Deploy-Client   $h $job }
            'set_lockdown'    { Deploy-Client   $h $job }
            'rotate_password' { Rotate-Password $h $job }
            'uninstall'       { Uninstall-Client $h $job }
            default           { throw "unknown action $($job.action)" }
        }
        Report $job.job_id 'done' "applied $($job.action)" $facts
        Log "job $($job.job_id) done"
    } catch {
        Report $job.job_id 'failed' $_.Exception.Message $null
        Log "job $($job.job_id) FAILED: $($_.Exception.Message)"
    }
}
