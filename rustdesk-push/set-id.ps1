<#
    set-id.ps1 - set this endpoint's RustDesk ID from the console.

    Why bother when the client has a "Change ID" dialog: that dialog asks the
    rendezvous server for permission, this script does not.

    The dialog checks the format twice - three UI rules in Dart (starts with a
    letter, 6..16, ^[\w-]*$, shown as the green chips), then the same thing in
    Rust (is_valid_custom_id, ^[a-zA-Z][\w-]{5,15}$). Dash and underscore both
    pass both, so once every chip is green the local checks are done. The
    "Invalid format" that still comes back after pressing OK is a server
    answer: change_id_shared sends RegisterPk to every configured rendezvous
    server and surfaces INVALID_ID_FORMAT from whichever one replies. Our hbbs
    cannot be the one - rustdesk-server OSS has no format check at all (only
    id.len() < 6) and never sends that code - so a client getting it is
    talking to something else, typically a stock rs-*.rustdesk.com left in a
    config the GUI instance reads. See docs/rustdesk-deployment.md.

    Writing the config skips that whole conversation: the service registers
    with the ID it finds on start, and hbbs takes any ID of 6+ characters.
    It is also the only path on a machine already configured by configure.ps1
    / deploy_script.py, which write disable-change-id = 'Y'. Both set the ID
    exactly the way this script does - put a plain `id = '...'` line into
    RustDesk.toml, drop the `enc_id` (the client's encrypted copy of the same
    value, which otherwise wins), and let the service pick it up on start.

    Keep the ID equal to the hostname: that is what InfraScope derives on its
    side (_hostname_to_rid in app/domains/remote_access/service.py), so the
    address book, the console and the InfraScope device list stay aligned.

    Run elevated - the live config lives under C:\Windows.

        .\set-id.ps1                        # prompt, hostname pre-filled
        .\set-id.ps1 -Id VNA_MGR_1504       # non-interactive
        .\set-id.ps1 -UseHostname -Force    # GPO / schtasks, no prompt at all

    Idempotent. Exit 0 = the service consumed the new ID, 1 = it did not.
#>
[CmdletBinding()]
param(
    [string]$Id,            # skip the prompt and use this
    [switch]$UseHostname,   # skip the prompt and use the sanitised hostname
    [switch]$Force          # accept a sanitised value without confirming
)

$ErrorActionPreference = 'Stop'

$logDir = 'C:\ProgramData\InfraScope'
$null = New-Item -ItemType Directory -Force -Path $logDir
$log = Join-Path $logDir 'rustdesk-set-id.log'
function Log($m) {
    Add-Content $log ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m)
    Write-Host $m
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'run this elevated: the RustDesk service config is under C:\Windows' }

$exe = Join-Path $env:ProgramFiles 'RustDesk\rustdesk.exe'
if (-not (Test-Path $exe)) { throw "RustDesk not installed at $exe" }

# ---- ID rules -----------------------------------------------------------
function Test-RustDeskId([string]$v) { return ($v -match '^[A-Za-z][A-Za-z0-9_]{5,15}$') }

function ConvertTo-RustDeskId([string]$raw) {
    # RustDesk itself would take a dash, InfraScope does not: the server side
    # derives the same ID from the hostname with _hostname_to_rid (non-alnum ->
    # "_"), and an endpoint that spells it differently shows up in the console
    # under a name the address book does not have.
    $v = ($raw.Trim() -replace '[^A-Za-z0-9_]', '_')   # dash, dot, space -> _
    if ($v -notmatch '^[A-Za-z]') { $v = 'PC' + $v }   # must start with a letter
    if ($v.Length -gt 16) { $v = $v.Substring(0, 16) }
    while ($v.Length -lt 6) { $v += '_' }              # 6 is the client's floor
    return $v
}

$hostId = ConvertTo-RustDeskId $env:COMPUTERNAME

if ($UseHostname -and -not $Id) { $Id = $hostId }

if ($Id) {
    $norm = ConvertTo-RustDeskId $Id
    if ($norm -ne $Id) {
        if (-not $Force) {
            throw "'$Id' is not a valid RustDesk ID - use '$norm', or pass -Force to accept it"
        }
        Log "note: '$Id' -> '$norm'"
    }
    $Id = $norm
} else {
    # Interactive. Empty answer = the hostname, which is the right answer
    # almost always; anything else gets sanitised in front of the operator.
    Write-Host ''
    Write-Host 'RustDesk ID: letter first, then letters / digits / underscore, 6..16 chars.'
    Write-Host 'Anything else (dash, dot, space) becomes "_" - same rule InfraScope uses.'
    while (-not $Id) {
        $ans = Read-Host "New ID [$hostId]"
        if (-not $ans) { $ans = $hostId }
        # A name pasted out of an inventory list can carry Cyrillic lookalikes
        # (А М Р С Е О К) or a non-breaking space: identical on screen, not the
        # same character, and they would silently turn into "_" below.
        if ($ans -match '[^ -~]') {
            Write-Host '  WARNING: the text contains non-ASCII characters - retype it, do not paste'
        }
        $norm = ConvertTo-RustDeskId $ans
        if (-not (Test-RustDeskId $norm)) { Write-Host "  cannot make an ID out of '$ans', try again"; continue }
        if ($norm -ne $ans.Trim()) {
            Write-Host "  '$($ans.Trim())' is not accepted by RustDesk, will use: $norm"
            if (-not $Force) {
                $ok = Read-Host '  OK? [Y/n]'
                if ($ok -and $ok -notmatch '^[Yy]') { continue }
            }
        }
        $Id = $norm
    }
}
if (-not (Test-RustDeskId $Id)) { throw "internal: '$Id' still not a valid RustDesk ID" }

Log "=== set-id: $env:COMPUTERNAME -> $Id ==="

# ---- where the ID actually lives ----------------------------------------
# The service reads systemprofile; the LocalService copy can hold stale values
# and wins on some builds, so write both (the same pair configure.ps1 writes).
# Per-user configs are only touched when they already exist - a portable
# rustdesk.exe run by a technician would otherwise keep showing the old ID.
$dirs = @(
    (Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config'),
    (Join-Path $env:WINDIR 'System32\config\systemprofile\AppData\Roaming\RustDesk\config')
)
$dirs += @(Get-ChildItem 'C:\Users' -Directory -EA SilentlyContinue | ForEach-Object {
    Join-Path $_.FullName 'AppData\Roaming\RustDesk\config' } | Where-Object {
    Test-Path (Join-Path $_ 'RustDesk.toml') })

function Stop-RD {
    $s = Get-Service RustDesk -EA SilentlyContinue
    if ($s -and $s.Status -ne 'Stopped') {
        try { Stop-Service RustDesk -Force -EA Stop } catch { & sc.exe stop RustDesk | Out-Null }
    }
    Start-Sleep 2
    Get-Process rustdesk -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
    Start-Sleep 2
}

# A running client rewrites RustDesk.toml on exit and would put the old enc_id
# straight back, so it has to be down before the file is touched.
Stop-RD

foreach ($d in $dirs) {
    $null = New-Item -ItemType Directory -Force -Path $d
    $f = Join-Path $d 'RustDesk.toml'
    $keep = @()
    if (Test-Path $f) {
        Copy-Item $f "$f.bak" -Force -EA SilentlyContinue
        # keep password / salt / key_pair - only the identity lines go
        $keep = Get-Content $f | Where-Object { $_ -notmatch '^\s*(enc_id|id)\s*=' }
    }
    Set-Content $f (@("id = '$Id'") + $keep) -Encoding UTF8
    Log "wrote $f"
}

try { Start-Service RustDesk -EA Stop } catch { & sc.exe start RustDesk | Out-Null }
Start-Sleep 6

# ---- verify -------------------------------------------------------------
# The service replaces our plain `id` line with its own encrypted `enc_id`
# once it has read the value. A plain `id` still sitting there after a restart
# means that copy was never loaded, i.e. the ID did not take.
$consumed = $false
foreach ($d in $dirs[0..1]) {
    $f = Join-Path $d 'RustDesk.toml'
    $txt = @(Get-Content $f -EA SilentlyContinue)
    $plain = @($txt | Where-Object { $_ -match '^\s*id\s*=' }).Count -gt 0
    $enc   = @($txt | Where-Object { $_ -match '^\s*enc_id\s*=' }).Count -gt 0
    if ($enc -and -not $plain) { $consumed = $true; Log "ok: $f - service took the new ID" }
    else { Log "pending: $f (plain id=$plain enc_id=$enc)" }
}

# --get-id reads the config of whoever runs it, not necessarily the service's,
# so this is a hint for the operator rather than the check itself.
try {
    $shown = (& $exe --get-id 2>$null | Select-Object -First 1)
    if ($shown) { Log "rustdesk --get-id: $shown" }
} catch { }

if (-not $consumed) {
    Log 'WARN: the ID was written but no config shows enc_id yet - open RustDesk and check the ID field'
    Log '=== set-id done (unverified) ==='
    exit 1
}

Log "done: this machine is now $Id"
Log 'remember: the ID is the address in the console - update the device in InfraScope'
Log '(or re-run the deploy script) so the address book does not keep pointing at the old one.'
Log '=== set-id done ==='
exit 0
