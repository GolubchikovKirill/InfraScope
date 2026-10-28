# Install-RustDesk.ps1 - RustDesk install + configure for Windows 7 AND Windows 10/11.
#
# Runs ON the endpoint (elevated / SYSTEM). Normally started by Push-RustDesk.ps1,
# which copies this file, the installer and rustdesk.json into one folder
# and launches it over WMI. It can also be run by hand from that folder.
#
# NEVER REBOOTS AND NEVER REQUIRES A REBOOT:
#   * MSI runs with /qn /norestart (exit 0 and 3010 are both success);
#   * a pending-reboot flag in the OS is ignored on purpose;
#   * no WMF / .NET / Windows Update step exists here - the syntax below is
#     PowerShell 2.0 compatible, so old Windows 7 (PS 2.0, no WMF 5.1) works
#     as is. Do not use ConvertFrom-Json, Invoke-RestMethod, Get-FileHash,
#     Get-CimInstance, [pscustomobject], Get-Content -Raw or $PSScriptRoot here
#     (tests/unit/remote_access/test_endpoint_scripts.py enforces this).
#
# Installer choice (both files sit next to this script):
#   Windows 10/11 x64   -> installer_msi   (msiexec /qn, returns a real exit code)
#   Windows 7 or 32-bit -> installer_exe32 (32-bit sciter build, --silent-install)
#   Windows XP          -> unsupported by RustDesk, exits with code 3.
#
# Config: rustdesk.json next to this script (same file as the offline
# package, see rustdesk.example.json). Profiles are just the three flags:
#   client (kiosk/till):  hidden=true  unattended=true   (tray hidden, password only)
#   admin (engineer PC):  hidden=false unattended=false  (tray visible, accept prompt)
#
# Idempotent. Exit codes: 0 ok, 1 bad kit/config, 2 install failed,
# 3 unsupported OS, 4 installed but the service did not pick up the ID.

$ErrorActionPreference = 'Continue'
$kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = 'C:\ProgramData\InfraScope'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$logKit = Join-Path $kit 'install.log'
$logFleet = Join-Path $logDir 'rustdesk-configure.log'
function L($m) {
    $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + '  ' + $m
    $line | Out-File -FilePath $logKit -Append -Encoding ASCII
    $line | Out-File -FilePath $logFleet -Append -Encoding ASCII
}
function Done($code, $m) { L $m; L 'DONE'; exit $code }

$rid = ($env:COMPUTERNAME -replace '[^A-Za-z0-9]', '_')
if ($rid.Length -gt 32) { $rid = $rid.Substring(0, 32) }

# ---- config (PS 2.0 has no ConvertFrom-Json: plain values are read by regex) ----
$cfgPath = Join-Path $kit 'rustdesk.json'
if (-not (Test-Path $cfgPath)) { Done 1 'FAIL rustdesk.json is missing next to the script' }
$json = [IO.File]::ReadAllText($cfgPath)
function Get-Str($name) {
    $m = [regex]::Match($json, '"' + $name + '"\s*:\s*"([^"]*)"')
    if ($m.Success) { return $m.Groups[1].Value }
    return ''
}
function Get-Bool($name, $default) {
    $m = [regex]::Match($json, '"' + $name + '"\s*:\s*(true|false)')
    if ($m.Success) { return ($m.Groups[1].Value -eq 'true') }
    return $default
}
$idServer = Get-Str 'id_server'
$relay = Get-Str 'relay_server'; if (-not $relay) { $relay = $idServer }
$api = Get-Str 'api_server'; if (-not $api) { $api = 'http://' + $idServer + ':21114' }
$key = Get-Str 'key'
$pw = Get-Str 'permanent_password'
$hidden = Get-Bool 'hidden' $true
$unattended = Get-Bool 'unattended' $true
$msiName = Get-Str 'installer_msi'; if (-not $msiName) { $msiName = 'rustdesk-1.5.0-x86_64.msi' }
$exeName = Get-Str 'installer_exe32'; if (-not $exeName) { $exeName = 'rustdesk-1.5.0-x86-sciter.exe' }
# upgrade_only: put the new RustDesk build over the installed one and touch nothing else -
# ID, password, options and shortcuts stay exactly as they are (no key / password needed).
$upgradeOnly = Get-Bool 'upgrade_only' $false
if (-not $upgradeOnly) {
    if (-not $idServer -or -not $key) { Done 1 'FAIL id_server / key missing in rustdesk.json' }
    if ($unattended -and -not $pw) { Done 1 'FAIL unattended profile needs permanent_password in rustdesk.json' }
}

# ---- OS ----
$os = Get-WmiObject Win32_OperatingSystem
$cpu = Get-WmiObject Win32_Processor | Select-Object -First 1
$verParts = $os.Version.Split('.')
$major = [int]$verParts[0]
$is64 = ($cpu.AddressWidth -eq 64)
L ("host=$env:COMPUTERNAME rid=$rid os=$($os.Caption) $($os.Version) bits=$($cpu.AddressWidth) ps=$($PSVersionTable.PSVersion) hidden=$hidden unattended=$unattended")
if ($major -lt 6) { Done 3 'UNSUPPORTED Windows XP: RustDesk cannot run here' }
$legacy = ($major -lt 10) -or (-not $is64)
$instName = if ($legacy) { $exeName } else { $msiName }
$inst = Join-Path $kit $instName
if (-not (Test-Path $inst)) { Done 1 ("FAIL installer $instName is missing next to the script") }
$want = (Get-Str $(if ($legacy) { 'installer_exe32_sha256' } else { 'installer_msi_sha256' })).ToLower()
if ($want) {
    $sha = [Security.Cryptography.SHA256]::Create(); $fs = [IO.File]::OpenRead($inst)
    try { $have = ([BitConverter]::ToString($sha.ComputeHash($fs)) -replace '-', '').ToLower() } finally { $fs.Close() }
    if ($have -ne $want) { Done 1 "FAIL installer sha256 mismatch: $have" }
    L 'installer sha256 ok'
}

function Get-SvcExe {
    $s = Get-WmiObject Win32_Service -Filter "Name='RustDesk'"
    if ($s) { return ($s.PathName -replace '^"([^"]+)".*$', '$1') }
    return $null
}
function Stop-RD {
    $s = Get-Service RustDesk -ErrorAction SilentlyContinue
    if ($s -and $s.Status -ne 'Stopped') { & sc.exe stop RustDesk | Out-Null }
    Start-Sleep 4
    Get-Process rustdesk -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
}
function Wait-Svc($seconds) {
    $e = $null
    for ($i = 0; $i -lt ($seconds / 3); $i++) {
        Start-Sleep 3
        $e = Get-SvcExe
        if ($e -and (Test-Path $e)) { return $e }
    }
    return $null
}

function Get-ExeVersion($path) {
    $m = [regex]::Match([string](Get-Item $path).VersionInfo.FileVersion, '^\d+(\.\d+){1,3}')
    if ($m.Success) { return [version]$m.Value }
    return $null
}

# ---- upgrade only: new build over the old one, configuration left alone ----
if ($upgradeOnly) {
    $exe = Get-SvcExe
    if (-not $exe -or -not (Test-Path $exe)) { Done 5 'FAIL upgrade_only: RustDesk is not installed here, nothing to upgrade' }
    $wantVerRaw = Get-Str 'installer_version'
    if (-not $wantVerRaw) { Done 1 'FAIL upgrade_only needs installer_version in rustdesk.json' }
    $wantVer = [version]$wantVerRaw
    $haveVer = Get-ExeVersion $exe
    L "upgrade_only: installed=$haveVer target=$wantVer exe=$exe"
    if ($haveVer -and $haveVer -ge $wantVer) { Done 0 "OK already $haveVer, nothing to do" }

    # snapshot the service configs (and where the shortcuts stand) so the upgrade can be checked
    $cfgDirs = @("$env:WINDIR\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config",
                 "$env:WINDIR\System32\config\systemprofile\AppData\Roaming\RustDesk\config")
    $snap = @{}
    $bakRoot = Join-Path $logDir ('rustdesk-preupgrade-' + (Get-Date).ToString('yyyyMMdd-HHmmss'))
    $i = 0
    foreach ($d in $cfgDirs) {
        $i++
        foreach ($n in @('RustDesk.toml', 'RustDesk2.toml')) {
            $f = Join-Path $d $n
            if (Test-Path $f) {
                $snap[$f] = [IO.File]::ReadAllBytes($f)
                $b = Join-Path $bakRoot ([string]$i)
                if (-not (Test-Path $b)) { New-Item -ItemType Directory -Force -Path $b | Out-Null }
                Copy-Item $f (Join-Path $b $n) -Force
            }
        }
    }
    function Get-Lnks {
        $r = @()
        Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $r += @(Get-ChildItem ($_.FullName + '\Desktop') -Filter 'RustDesk*.lnk' -ErrorAction SilentlyContinue)
        }
        $r += @(Get-ChildItem 'C:\Users\Public\Desktop' -Filter 'RustDesk*.lnk' -ErrorAction SilentlyContinue)
        $r += @(Get-ChildItem ($env:ProgramData + '\Microsoft\Windows\Start Menu\Programs') -Filter 'RustDesk*' -ErrorAction SilentlyContinue)
        return $r
    }
    $lnkBefore = @(Get-Lnks).Count
    L "config snapshot: $($snap.Count) file(s) in $bakRoot, shortcuts before: $lnkBefore"

    # An MSI refuses to go over a RustDesk that was put on by its own installer (it fails with
    # 1603, "BlockSelfInstalledApp") and that kind has an "Uninstall\RustDesk" key of its own;
    # such a machine gets the self-installing x64 exe instead, which updates in place.
    $selfInstalled = $false
    if (-not $legacy) {
        foreach ($k in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk',
                         'HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\RustDesk')) {
            $u = Get-ItemProperty $k -ErrorAction SilentlyContinue
            if ($u -and $u.WindowsInstaller -ne 1) { $selfInstalled = $true }
        }
    }
    if ($selfInstalled) {
        $exe64Name = Get-Str 'installer_exe64'; if (-not $exe64Name) { $exe64Name = 'rustdesk-1.5.0-x86_64.exe' }
        $inst = Join-Path $kit $exe64Name
        $instName = $exe64Name
        if (-not (Test-Path $inst)) { Done 1 "FAIL installer $exe64Name is missing next to the script (this machine was not installed from an MSI)" }
        $want64 = (Get-Str 'installer_exe64_sha256').ToLower()
        if ($want64) {
            $sha = [Security.Cryptography.SHA256]::Create(); $fs = [IO.File]::OpenRead($inst)
            try { $have64 = ([BitConverter]::ToString($sha.ComputeHash($fs)) -replace '-', '').ToLower() } finally { $fs.Close() }
            if ($have64 -ne $want64) { Done 1 "FAIL installer sha256 mismatch: $have64" }
        }
        L "self-installed RustDesk: using $exe64Name instead of the msi"
    }

    Stop-RD
    if ($legacy -or $selfInstalled) {
        L "upgrading (self-installer): $instName --silent-install"
        Start-Process -FilePath $inst -ArgumentList '--silent-install' | Out-Null
    } else {
        L "upgrading (msi): $instName /qn /norestart"
        $msiArgs = @('/i', ('"' + $inst + '"'), '/qn', '/norestart', 'CREATESTARTMENUSHORTCUTS=N',
                     'CREATEDESKTOPSHORTCUTS=N', 'INSTALLPRINTER=N', '/l*v', ('"' + (Join-Path $kit 'rustdesk-msi.log') + '"'))
        $p = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Done 2 "FAIL msiexec exit $($p.ExitCode)" }
    }
    # the legacy installer does not wait for itself: poll until the new build is on disk
    $exe = $null
    $now = $null
    for ($k = 0; $k -lt 40; $k++) {
        Start-Sleep 3
        $exe = Get-SvcExe
        if ($exe -and (Test-Path $exe)) {
            $now = Get-ExeVersion $exe
            if ($now -and $now -ge $wantVer) { break }
        }
    }
    if (-not $exe -or -not $now -or $now -lt $wantVer) {
        # MSI can leave the files without registering the service - register it
        $cand = @("$env:ProgramFiles\RustDesk\RustDesk.exe", "${env:ProgramFiles(x86)}\RustDesk\RustDesk.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if ($cand -and -not (Get-SvcExe)) {
            L "service missing after upgrade, registering: $cand --install-service"
            Start-Process -FilePath $cand -ArgumentList '--install-service' -WindowStyle Hidden | Out-Null
            Start-Sleep 10
            $exe = Get-SvcExe
            if ($exe -and (Test-Path $exe)) { $now = Get-ExeVersion $exe }
        }
    }
    if (-not $exe -or -not $now -or $now -lt $wantVer) { Done 2 "FAIL upgrade did not take: version now=$now, wanted $wantVer" }
    Start-Sleep 5

    # the installer may have started the service / a UI: stop, put any changed config back, start
    Stop-RD
    $restored = 0
    foreach ($f in @($snap.Keys)) {
        $same = $false
        if (Test-Path $f) {
            $cur = [IO.File]::ReadAllBytes($f)
            $same = ($cur.Length -eq $snap[$f].Length) -and ([BitConverter]::ToString($cur) -eq [BitConverter]::ToString($snap[$f]))
        }
        if (-not $same) { [IO.File]::WriteAllBytes($f, $snap[$f]); $restored++ }
    }
    L "config files restored after upgrade: $restored"
    & sc.exe start RustDesk | Out-Null
    Start-Sleep 8

    # shortcuts: leave things as they were
    if ($lnkBefore -eq 0) {
        $n = 0
        @(Get-Lnks) | ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue; $n++ }
        L "shortcuts the installer created removed: $n"
    }

    # the session-0 UI/tray a WMI-started installer leaves behind: close it, keep the service
    Get-WmiObject Win32_Process -Filter "Name='RustDesk.exe'" | Where-Object {
        $_.SessionId -eq 0 -and $_.CommandLine -notmatch '--service|--server'
    } | ForEach-Object { [void]$_.Terminate() }

    $s = Get-WmiObject Win32_Service -Filter "Name='RustDesk'"
    $enc = $false
    $lsToml = Join-Path $cfgDirs[0] 'RustDesk.toml'
    if ((Test-Path $lsToml) -and (Select-String -Path $lsToml -Pattern '^\s*(enc_id|id)\s*=' -Quiet)) { $enc = $true }
    $state = "svc=$($s.State)/$($s.StartMode) version $haveVer -> $now, id kept=$enc, config untouched"
    if ($s.State -eq 'Running') { Done 0 "OK upgraded $state" }
    Done 4 "WARN upgraded but the service is not running: $state"
}

# ---- install (skipped when the service is already there) ----
$exe = Get-SvcExe
if ($exe -and (Test-Path $exe)) {
    L "already installed: $exe"
} else {
    if ($legacy) {
        L "installing (legacy 32-bit): $instName --silent-install"
        Start-Process -FilePath $inst -ArgumentList '--silent-install' | Out-Null
    } else {
        L "installing (msi): $instName /qn /norestart"
        $msiArgs = @('/i', ('"' + $inst + '"'), '/qn', '/norestart', 'CREATESTARTMENUSHORTCUTS=N',
                     'CREATEDESKTOPSHORTCUTS=N', 'INSTALLPRINTER=N', '/l*v', ('"' + (Join-Path $kit 'rustdesk-msi.log') + '"'))
        $p = Start-Process msiexec.exe -ArgumentList $msiArgs -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Done 2 "FAIL msiexec exit $($p.ExitCode)" }
    }
    $exe = Wait-Svc 90
    if (-not $exe) {
        # MSI can leave the files without registering the service - register it.
        $cand = @("$env:ProgramFiles\RustDesk\RustDesk.exe", "${env:ProgramFiles(x86)}\RustDesk\RustDesk.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if ($cand) {
            L "service missing after install, registering: $cand --install-service"
            Start-Process -FilePath $cand -ArgumentList '--install-service' -WindowStyle Hidden | Out-Null
            $exe = Wait-Svc 60
        }
    }
    if (-not $exe) { Done 2 'FAIL RustDesk service is not registered after install' }
    L "service exe: $exe"
    Start-Sleep 5
}

# ---- config ----
function Build-Toml($locks) {
    $l = @("rendezvous_server = '$idServer'", 'nat_type = 1', 'serial = 0', '', '[options]',
           "custom-rendezvous-server = '$idServer'", "relay-server = '$relay'", "api-server = '$api'", "key = '$key'",
           "enable-check-update = 'N'", "enable-lan-discovery = 'N'", "direct-server = 'N'",
           "allow-logon-screen-password = 'Y'", "remove-preset-password-warning = 'Y'", "hide-help-cards = 'Y'")
    if ($hidden) {
        $l += @("hide-tray = 'Y'", "hide-stop-service = 'Y'", "allow-hide-cm = 'Y'", "hide-security-settings = 'Y'",
                "hide-network-settings = 'Y'", "hide-server-settings = 'Y'")
    }
    if ($unattended) { $l += @("approve-mode = 'password'", "verification-method = 'use-permanent-password'") }
    if ($locks) { $l += @("disable-change-permanent-password = 'Y'", "disable-change-id = 'Y'") }
    return (($l -join "`r`n") + "`r`n")
}
$dirs = @("$env:WINDIR\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config",
          "$env:WINDIR\System32\config\systemprofile\AppData\Roaming\RustDesk\config")
function Write-Opts($locks) {
    $t = Build-Toml $locks
    foreach ($d in $dirs) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        [IO.File]::WriteAllText((Join-Path $d 'RustDesk2.toml'), $t, [Text.Encoding]::ASCII)
    }
}

# The connection-manager window ("who connected") and the tray icon are drawn by
# processes in the USER's session, and they read the options from that user's own
# profile - not from the service profiles above. Without this file a till shows the
# cashier a pop-up on every remote connection even though the service is set to hide it.
function Write-UserOpts($locks) {
    $t = Build-Toml $locks
    Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -notmatch '^(Public|Default|Default User|All Users)$' -and (Test-Path ($_.FullName + '\AppData\Roaming'))
    } | ForEach-Object {
        $d = $_.FullName + '\AppData\Roaming\RustDesk\config'
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        [IO.File]::WriteAllText((Join-Path $d 'RustDesk2.toml'), $t, [Text.Encoding]::ASCII)
    }
}

Stop-RD
Write-Opts $false
foreach ($d in $dirs) {
    $f = Join-Path $d 'RustDesk.toml'
    $keep = @()
    if (Test-Path $f) {
        Copy-Item $f "$f.bak" -Force
        $keep = @(Get-Content $f | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' })
    }
    Set-Content -Path $f -Value (@("id = '$rid'") + $keep) -Encoding ASCII
}
L "config + id written ($rid)"
& sc.exe start RustDesk | Out-Null

$lsToml = Join-Path $dirs[0] 'RustDesk.toml'
$enc = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep 3
    if ((Test-Path $lsToml) -and (Select-String -Path $lsToml -Pattern '^\s*enc_id' -Quiet)) { $enc = $true; break }
}
L "service picked up the id (enc_id): $enc"

if ($unattended) {
    & $exe --password $pw | Out-Null
    Start-Sleep 4
    L 'permanent password set'
    Stop-RD
    Write-Opts $true
    & sc.exe start RustDesk | Out-Null
    Start-Sleep 6
    L 'config locked'
}

if ($hidden) {
    Write-UserOpts $unattended
    L 'user-profile options written (no connection pop-up, no tray)'
    $n = 0
    Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ChildItem ($_.FullName + '\Desktop') -Filter 'RustDesk*.lnk' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item $_.FullName -Force; $n++ }
    }
    Get-ChildItem 'C:\Users\Public\Desktop' -Filter 'RustDesk*.lnk' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item $_.FullName -Force; $n++ }
    Get-ChildItem ($env:ProgramData + '\Microsoft\Windows\Start Menu\Programs') -Filter 'RustDesk*' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item $_.FullName -Recurse -Force; $n++ }
    L "shortcuts removed: $n"
} else {
    L 'shortcuts kept (admin profile)'
}

# The UI/tray instances a WMI-started session leaves in session 0 hold the
# script's file handles and are invisible to the user - close them, keep the
# service (--service) and its server (--server).
Get-WmiObject Win32_Process -Filter "Name='RustDesk.exe'" | Where-Object {
    $_.SessionId -eq 0 -and $_.CommandLine -notmatch '--service|--server'
} | ForEach-Object { [void]$_.Terminate() }

$s = Get-WmiObject Win32_Service -Filter "Name='RustDesk'"
$state = "svc=$($s.State)/$($s.StartMode) id=$rid enc_id=$enc"
if ($s.State -eq 'Running' -and $enc) { Done 0 "OK $state" }
Done 4 "WARN $state"
