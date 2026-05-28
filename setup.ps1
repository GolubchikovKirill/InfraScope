# InfraScope — Windows Setup Script
# Run in PowerShell (Administrator recommended for hosts file)

$ErrorActionPreference = "Stop"

function Write-Info  { param($msg) Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  +==============================================+"
Write-Host "  |          InfraScope  -  Setup                |"
Write-Host "  +==============================================+"
Write-Host ""

# -- 1. Check Docker --

try {
    $dockerVer = docker --version 2>&1
    Write-Info "Docker: $dockerVer"
} catch {
    Write-Err "Docker not installed. Download: https://docker.com/products/docker-desktop"
}

try {
    docker compose version | Out-Null
} catch {
    Write-Err "Docker Compose v2 not found."
}

# -- 2. Create .env --

if (!(Test-Path ".env")) {
    Copy-Item ".env.example" ".env"

    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $secret = [Convert]::ToBase64String($bytes).Replace("+","").Replace("/","").Replace("=","").Substring(0,43)

    $dbBytes = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($dbBytes)
    $dbPass = [Convert]::ToBase64String($dbBytes).Replace("+","").Replace("/","").Replace("=","").Substring(0,20)

    $apBytes = New-Object byte[] 6
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($apBytes)
    $adminPass = "Admin" + [Convert]::ToBase64String($apBytes).Replace("+","").Replace("/","").Replace("=","").Substring(0,8) + "1!"

    $content = Get-Content ".env" -Raw
    $content = $content.Replace("SECRET_KEY=CHANGE_ME", "SECRET_KEY=$secret")
    $content = $content.Replace("POSTGRES_PASSWORD=CHANGE_ME", "POSTGRES_PASSWORD=$dbPass")
    $content = $content.Replace("FIRST_SUPERUSER_PASSWORD=CHANGE_ME", "FIRST_SUPERUSER_PASSWORD=$adminPass")
    Set-Content ".env" $content -NoNewline

    Write-Info ".env created"
    Write-Info "Admin password: $adminPass"
    Write-Warn "Save this password! It will not be shown again."
} else {
    Write-Info ".env already exists - skipping"
}

# -- 3. SSL certificates --

$hasMkcert = $false
try { mkcert --version 2>&1 | Out-Null; $hasMkcert = $true } catch {}

if ($hasMkcert) {
    if (!(Test-Path "certs\cert.pem") -or !(Test-Path "certs\key.pem")) {
        New-Item -ItemType Directory -Force -Path "certs" | Out-Null
        mkcert -install 2>$null
        Push-Location certs
        mkcert -cert-file cert.pem -key-file key.pem infrascope.local localhost 127.0.0.1 "::1"
        Pop-Location
        Write-Info "SSL certificates created (mkcert - trusted)"
    } else {
        Write-Info "SSL certificates already exist"
    }
} else {
    Write-Warn "mkcert not found - self-signed certificates will be generated automatically"
    Write-Warn "For trusted HTTPS install mkcert:"
    Write-Warn "  choco install mkcert && mkcert -install"
}

# -- 4. Local domain --

$hostsFile = "C:\Windows\System32\drivers\etc\hosts"
$hostsContent = ""
try { $hostsContent = Get-Content $hostsFile -Raw -ErrorAction SilentlyContinue } catch {}

if ($hostsContent -notmatch "infrascope\.local") {
    try {
        Add-Content $hostsFile "`n127.0.0.1 infrascope.local" -ErrorAction Stop
        Write-Info "Domain infrascope.local added to hosts"
    } catch {
        Write-Warn "Could not modify hosts file (run PowerShell as Administrator)"
        Write-Warn "Manually add: 127.0.0.1 infrascope.local"
        Write-Warn "File: $hostsFile"
    }
} else {
    Write-Info "Domain infrascope.local already configured"
}

# -- 5. SCAN_SUBNET prompt --

$envContent = Get-Content ".env" -Raw
if ($envContent -match "SCAN_SUBNET=\s*$" -or $envContent -match "SCAN_SUBNET=$") {
    Write-Host ""
    $subnet = Read-Host "Printer subnets to scan (e.g. 10.10.98.0/24, 10.10.99.0/24)"
    if ($subnet) {
        $envContent = $envContent -replace "SCAN_SUBNET=.*", "SCAN_SUBNET=$subnet"
        Set-Content ".env" $envContent -NoNewline
        Write-Info "SCAN_SUBNET set: $subnet"
    } else {
        Write-Warn "SCAN_SUBNET not set - network scanner will be unavailable until configured in .env"
    }
}

# -- 6. Build and start --

Write-Host ""
Write-Info "Building and starting containers..."
Write-Host ""

docker compose up -d --build

Write-Host ""
Write-Host "  +==============================================+"
Write-Host "  |        InfraScope is running!                |"
Write-Host "  |==============================================|"
Write-Host "  |  https://infrascope.local                    |"
Write-Host "  |  https://localhost                           |"
Write-Host "  |  API: https://localhost/docs                 |"
Write-Host "  |==============================================|"
Write-Host "  |  Login: admin@infrascope.dev                 |"
Write-Host "  +==============================================+"
Write-Host ""
