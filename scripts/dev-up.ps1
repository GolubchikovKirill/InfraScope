<#
.SYNOPSIS
  Local development stack in Docker (docker-compose.local.yml).

.DESCRIPTION
  First run creates .env from .env.local.example with fresh keys, builds the
  images and starts db, redis, backend (auto-reload), worker, beat and the
  Vite dev server. Refuses to start on a production .env.

.EXAMPLE
  .\scripts\dev-up.ps1                    # start / update
  .\scripts\dev-up.ps1 -FromProdBackup    # also load last night's prod backup
  .\scripts\dev-up.ps1 -ResetAdmin        # local admin password back to the one in .env
  .\scripts\dev-up.ps1 -Logs              # follow backend + worker logs
  .\scripts\dev-up.ps1 -Down              # stop (data kept)
  .\scripts\dev-up.ps1 -Reset             # stop and wipe the local database
#>
param(
    [switch]$FromProdBackup,
    [switch]$ResetAdmin,
    [switch]$Logs,
    [switch]$Down,
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$Compose = @("compose", "-p", "infrascope-local", "-f", "docker-compose.yml", "-f", "docker-compose.local.yml")
$Services = @("db", "redis", "backend", "worker", "beat", "frontend-dev")

function Invoke-Compose([string[]]$Arguments) {
    & docker @Compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker $($Compose + $Arguments -join ' ') failed ($LASTEXITCODE)" }
}

function New-Secret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    # URL-safe base64, which is also exactly a Fernet key for 32 bytes
    return [Convert]::ToBase64String($buffer).Replace("+", "-").Replace("/", "_")
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or not on PATH. Install Docker Desktop and start it."
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is installed but not running. Start Docker Desktop and run this again." }

if ($Down) { Invoke-Compose @("down"); return }
if ($Reset) { Invoke-Compose @("down", "-v"); Write-Host "Local stack stopped, local volumes removed."; return }
function Reset-Admin {
    Get-Content -Raw scripts\dev_reset_admin.py | & docker @Compose exec -T backend python -
    if ($LASTEXITCODE -ne 0) { throw "Admin password reset failed ($LASTEXITCODE)" }
}
if ($ResetAdmin) { Reset-Admin; return }
if ($Logs) { Invoke-Compose @("logs", "-f", "--tail", "100", "backend", "worker"); return }

# --- .env ---------------------------------------------------------------------
if (Test-Path .env) {
    $existing = Get-Content .env -Raw
    if ($existing -match "(?m)^\s*ENVIRONMENT\s*=\s*['""]?production") {
        throw (".env here is a production one (ENVIRONMENT=production). It carries live integration " +
               "tokens. Rename it (Rename-Item .env .env.prod-copy) and run this again: a local .env " +
               "is created from .env.local.example.")
    }
    Write-Host "Using the existing .env (ENVIRONMENT is forced to development by docker-compose.local.yml)."
} else {
    $template = Get-Content .env.local.example -Raw
    $template = $template -replace "(?m)^SECRET_KEY=__GENERATED__", ("SECRET_KEY=" + (New-Secret 48))
    $template = $template -replace "(?m)^CREDENTIALS_ENCRYPTION_KEYS=__GENERATED__", ("CREDENTIALS_ENCRYPTION_KEYS=" + (New-Secret 32))
    # LF endings: the containers read this file
    [IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), ($template -replace "`r`n", "`n"))
    Write-Host "Created .env from .env.local.example with fresh keys."
}

# --- start ----------------------------------------------------------------------
Invoke-Compose (@("up", "-d", "--build") + $Services)

Write-Host "Waiting for the API (migrations run on first start)..."
$deadline = (Get-Date).AddMinutes(4)
do {
    Start-Sleep -Seconds 3
    try { $ok = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://localhost:8000/health).StatusCode -eq 200 } catch { $ok = $false }
} until ($ok -or (Get-Date) -gt $deadline)
if (-not $ok) {
    Invoke-Compose @("logs", "--tail", "60", "backend")
    throw "The API did not come up within 4 minutes; its log is above."
}

# --- optional: last night's production backup ---------------------------------
if ($FromProdBackup) {
    Write-Host "Fetching the latest nightly backup from infrascope-server..."
    $latest = (& ssh infrascope-server "ls -1t ~/InfraScope/backups/postgres/daily/*.dump | head -n 1").Trim()
    if (-not $latest) { throw "No backup found in ~/InfraScope/backups/postgres/daily on the server." }
    New-Item -ItemType Directory -Force backups\local | Out-Null
    $dump = "backups\local\prod-latest.dump"
    & scp "infrascope-server:$latest" $dump
    if ($LASTEXITCODE -ne 0) { throw "scp of $latest failed" }
    Invoke-Compose @("stop", "backend", "worker", "beat")
    Invoke-Compose @("cp", $dump, "db:/tmp/prod.dump")
    # --no-owner: the dump's roles may not exist here; -c --if-exists: replace what migrations created
    & docker @Compose exec -T db sh -c "pg_restore -U postgres -d infrascope -c --if-exists --no-owner /tmp/prod.dump; rm -f /tmp/prod.dump"
    Invoke-Compose @("start", "backend", "worker", "beat")
    # the dump brought the prod admin hash; give the admin the local password back
    Reset-Admin
    Write-Host "Restored $latest. Switch and vault passwords stay encrypted with the prod key and are unreadable here, by design."
    Write-Host "Log in with the local admin below, or with your own prod login."
}

$envText = Get-Content .env -Raw
$email = [regex]::Match($envText, "(?m)^FIRST_SUPERUSER_EMAIL=(.*)$").Groups[1].Value.Trim()
$password = [regex]::Match($envText, "(?m)^FIRST_SUPERUSER_PASSWORD=(.*)$").Groups[1].Value.Trim()
Write-Host ""
Write-Host "Local InfraScope is up:" -ForegroundColor Green
Write-Host "  App   http://localhost:5173   (hot reload)"
Write-Host "  API   http://localhost:8000/docs"
Write-Host "  Login $email / $password"
Write-Host "Hardware writes are OFF: no AP reboots, no DHCP cleanup, no switch writes from this stack."
Write-Host "Logs: .\scripts\dev-up.ps1 -Logs    Stop: .\scripts\dev-up.ps1 -Down"
Write-Host "The worker does not auto-reload: after changing tasks run  docker compose -p infrascope-local restart worker"
