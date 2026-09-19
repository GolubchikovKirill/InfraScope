<#
    Run-PushRunner.ps1 - lets InfraScope roll RustDesk out over the network, from THIS Windows machine.

    The InfraScope server never runs anything on the fleet (from a Linux box that looks like
    lateral movement and gets blocked). Instead it keeps a queue of "push RustDesk to host X"
    jobs. This script is the other half: it runs on a Windows admin machine, asks the server
    for work, runs the existing push kit for each job (rustdesk-ksc\Push-RustDesk.ps1: C$ admin
    share + WMI/DCOM, Windows 7 and 10, never reboots anything) and reports how it went. The
    server then moves the device's rollout state, exactly as if the machine had reported itself.

    Run it as the account that is a local admin on the target machines (it is the same right
    the push kit needs when you run it by hand). No password is stored anywhere: the job
    config, which contains the machine's RustDesk password, lives in a temp file only for
    the duration of one push and is deleted right after.

    Needs, next to the kit (see docs/rustdesk-deployment.md):
      ..\rustdesk-ksc\Push-RustDesk.ps1 and endpoint\Install-RustDesk.ps1
      ..\rustdesk-ksc\packages\  with the MSI (Windows 10/11) and the 32-bit sciter exe (Windows 7)

    Usage:
      .\Run-PushRunner.ps1 -Server https://10.10.99.24 -Token <runner token> -SkipCertCheck
      .\Run-PushRunner.ps1 -Server https://10.10.99.24 -Token <token> -Once     # one round, then exit

    -Token is RUSTDESK_RUNNER_TOKEN from the server's .env (or RUSTDESK_DEPLOY_TOKEN when no
    separate runner token is set). -SkipCertCheck is for the server's self-signed certificate.

    Leave the window open while jobs should run. Closing it mid-push abandons that job: the
    server fails it after 30 minutes and the machine shows the failure, nothing is left half-done
    that a re-run would not fix (the push is idempotent).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$KitPath = (Join-Path $PSScriptRoot '..\rustdesk-ksc'),
    [string]$RunnerName = $env:COMPUTERNAME,
    [int]$PollSeconds = 15,
    [int]$Batch = 3,
    [switch]$SkipCertCheck,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$Server = $Server.TrimEnd('/')
$push = Join-Path $KitPath 'Push-RustDesk.ps1'
if (-not (Test-Path $push)) { throw "Push kit not found: $push (use -KitPath)" }

# Windows PowerShell 5.1 defaults to TLS 1.0/1.1, which the server's nginx refuses
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if ($SkipCertCheck) {
    [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    Write-Host 'Certificate check is OFF (-SkipCertCheck): only use this against your own InfraScope server.' -ForegroundColor Yellow
}

function Write-Log([string]$text, [string]$color = 'Gray') {
    Write-Host ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $text) -ForegroundColor $color
}

function Invoke-Api([string]$path, $body) {
    Invoke-RestMethod -Method Post -Uri "$Server/api/v1/remote-access/$path" `
        -Headers @{ 'X-InfraScope-Runner-Token' = $Token } `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 8 -Compress))) `
        -TimeoutSec 30
}

# The kit prints, per machine:
#   OK       VNK-KKM-3301
#            Windows 10 Pro (10.0.19045, 64-bit)  [msi (rustdesk-1.4.9-x86_64.msi)]   (Windows XP: empty [])
#            <detail>
# Result words: OK / WARN / FAILED / SKIPPED / DRY-RUN.
function ConvertFrom-KitOutput([string]$output, [string]$hostName) {
    $lines = $output -split "`r?`n"
    $map = @{ 'OK' = 'ok'; 'WARN' = 'warn'; 'FAILED' = 'failed'; 'SKIPPED' = 'skipped'; 'DRY-RUN' = 'dry_run' }
    $escaped = [regex]::Escape($hostName)
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^(OK|WARN|FAILED|SKIPPED|DRY-RUN)\s+' + $escaped + '\s*$')) {
            $result = $map[$Matches[1]]
            $os = $null
            $detail = @()
            for ($j = $i + 1; $j -lt $lines.Count -and $lines[$j] -match '^\s{4,}\S'; $j++) {
                $text = $lines[$j].Trim()
                if (-not $os -and $text -match '^(.*?)\s+\[[^\]]*\]\s*$') { $os = $Matches[1] } else { $detail += $text }
            }
            return @{ result = $result; os = $os; detail = ($detail -join ' | ') }
        }
    }
    $tail = ($lines | Where-Object { $_.Trim() } | Select-Object -Last 6) -join ' | '
    return @{ result = 'failed'; os = $null; detail = "no result line from the push kit: $tail" }
}

function Invoke-PushJob($job) {
    $configFile = Join-Path ([IO.Path]::GetTempPath()) ('infrascope-push-' + [guid]::NewGuid().ToString('N') + '.json')
    try {
        # per-machine config from the server: its own RustDesk ID and password, so the password on
        # the machine is the one the shared address book holds. Written UTF-8 without BOM.
        [IO.File]::WriteAllText($configFile, ($job.config | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
        $kitArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $push,
            '-ComputerName', $job.hostname, '-Profile', $job.profile, '-ConfigPath', $configFile)
        if ($job.dry_run) { $kitArgs += '-DryRun' }
        Write-Log ("-> {0}  (profile {1}{2})" -f $job.hostname, $job.profile, $(if ($job.dry_run) { ', dry run' } else { '' })) 'Cyan'
        $output = & powershell.exe @kitArgs 2>&1 | Out-String
        $verdict = ConvertFrom-KitOutput $output $job.hostname
    } catch {
        $verdict = @{ result = 'failed'; os = $null; detail = "runner error: " + $_.Exception.Message.Split("`n")[0] }
    } finally {
        # the file holds the machine's password: it must not outlive the push
        Remove-Item $configFile -Force -ErrorAction SilentlyContinue
    }
    $color = switch ($verdict.result) { 'ok' { 'Green' } 'warn' { 'Yellow' } 'dry_run' { 'Cyan' } 'skipped' { 'DarkGray' } default { 'Red' } }
    Write-Log ("   {0}: {1}" -f $verdict.result.ToUpper(), $verdict.detail) $color
    $report = @{ job_id = $job.id; result = $verdict.result; detail = $verdict.detail }
    if ($verdict.os) { $report.os_caption = $verdict.os }
    for ($try = 1; $try -le 3; $try++) {
        try { $null = Invoke-Api 'runner/report' $report; return }
        catch { Write-Log ("   could not report to InfraScope (try $try): " + $_.Exception.Message) 'Yellow'; Start-Sleep 5 }
    }
    Write-Log ("   GAVE UP reporting {0}: the server will fail the job after 30 minutes." -f $job.hostname) 'Red'
}

Write-Log ("Push runner '{0}' -> {1}   (Ctrl+C to stop)" -f $RunnerName, $Server) 'Cyan'
$backoff = $PollSeconds
while ($true) {
    try {
        $claim = Invoke-Api 'runner/claim' @{ runner = $RunnerName; limit = $Batch }
        $backoff = $PollSeconds
        foreach ($job in @($claim.jobs)) { Invoke-PushJob $job }
        if ($Once) { break }
        if (-not @($claim.jobs).Count) { Start-Sleep -Seconds $PollSeconds }
    } catch {
        Write-Log ("InfraScope is not answering: " + $_.Exception.Message) 'Yellow'
        if ($Once) { throw }
        Start-Sleep -Seconds $backoff
        $backoff = [Math]::Min($backoff * 2, 120)
    }
}
