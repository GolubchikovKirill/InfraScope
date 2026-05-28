param(
    [Parameter(Mandatory = $true)]
    [string]$Uri
)

$LogPath = Join-Path $env:TEMP "infrascope-nsm.log"

function Write-Log([string]$text) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $text"
    try {
        [System.IO.File]::AppendAllText($LogPath, "$line`r`n", [System.Text.Encoding]::UTF8)
    } catch {
        # Logging must never break connection flow.
    }
}

function Show-Error([string]$text) {
    Add-Type -AssemblyName PresentationFramework | Out-Null
    [System.Windows.MessageBox]::Show($text, "InfraScope NetSupport Helper") | Out-Null
    Write-Log "ERROR: $text"
}

function Resolve-TargetFromUri([string]$rawUri) {
    $value = $rawUri.Trim()
    if (-not $value.ToLower().StartsWith("infrascope-nsm://")) {
        return $null
    }

    $payload = $value.Substring("infrascope-nsm://".Length).TrimStart("/")
    if (-not $payload) {
        return $null
    }

    $payloadLower = $payload.ToLower()
    if ($payloadLower.StartsWith("connect?") -or $payloadLower.StartsWith("connect/?")) {
        $query = if ($payloadLower.StartsWith("connect/?")) {
            $payload.Substring("connect/?".Length)
        } else {
            $payload.Substring("connect?".Length)
        }

        $hostValue = $null
        $ipValue = $null
        $portValue = $null
        $rawValue = $null

        foreach ($pair in $query.Split("&")) {
            $parts = $pair.Split("=", 2)
            if ($parts.Length -ne 2) {
                continue
            }
            $name = $parts[0].ToLower()
            $v = [uri]::UnescapeDataString($parts[1]).Trim()
            if ($name -eq "host") { $hostValue = $v; continue }
            if ($name -eq "ip") { $ipValue = $v; continue }
            if ($name -eq "port") { $portValue = $v; continue }
            if ($name -eq "raw") { $rawValue = $v; continue }
        }

        return @{
            Host = $hostValue
            Ip = $ipValue
            Port = $portValue
            Raw = $rawValue
        }
    }

    return @{
        Host = [uri]::UnescapeDataString($payload).Trim().Trim("/")
        Ip = $null
        Port = $null
        Raw = $null
    }
}

function Normalize-Target([string]$target) {
    if (-not $target) { return $null }
    $value = $target.Trim().Trim('"').Trim("'").Trim("/")
    if (-not $value) { return $null }
    $value = $value -replace "^[a-zA-Z][a-zA-Z0-9+.-]*://", ""
    $value = $value.Trim().Trim("/")
    if (-not $value) { return $null }
    return $value
}

function Normalize-Port([string]$portRaw) {
    if (-not $portRaw) { return 5405 }
    $num = 0
    if ([int]::TryParse($portRaw, [ref]$num) -and $num -ge 1 -and $num -le 65535) {
        return $num
    }
    return 5405
}

function Split-HostPort([string]$target, [int]$defaultPort) {
    if (-not $target) {
        return @{
            HostValue = $null
            Port = $defaultPort
        }
    }
    $hostValue = $target
    $port = $defaultPort
    if ($target.Contains(":")) {
        $parts = $target.Split(":", 2)
        if ($parts.Length -eq 2) {
            $p = 0
            if ([int]::TryParse($parts[1], [ref]$p) -and $p -ge 1 -and $p -le 65535) {
                $hostValue = $parts[0]
                $port = $p
            }
        }
    }
    return @{
        HostValue = $hostValue
        Port = $port
    }
}

function Resolve-IPv4([string]$hostname, [string]$providedIp) {
    if ($providedIp) {
        $ip = $providedIp.Trim()
        if ($ip) { return $ip }
    }
    if (-not $hostname) { return $null }
    $lookupHost = $hostname.TrimStart(">")
    if ($lookupHost.Contains(":")) {
        $maybeHostPort = Split-HostPort -target $lookupHost -defaultPort 5405
        if ($maybeHostPort.HostValue) {
            $lookupHost = $maybeHostPort.HostValue
        }
    }
    try {
        $addresses = [System.Net.Dns]::GetHostAddresses($lookupHost)
        foreach ($addr in $addresses) {
            if ($addr.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                return $addr.ToString()
            }
        }
    } catch {
        Write-Log "DNS resolve failed for '$lookupHost': $($_.Exception.Message)"
        # Handle common typo/mismatch in host prefixes: VNA- <-> VNK-
        if ($lookupHost -match "^VNA-") {
            $altHost = $lookupHost -replace "^VNA-", "VNK-"
            try {
                $altAddresses = [System.Net.Dns]::GetHostAddresses($altHost)
                foreach ($alt in $altAddresses) {
                    if ($alt.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                        Write-Log "DNS alias fallback used: '$lookupHost' -> '$altHost'"
                        return $alt.ToString()
                    }
                }
            } catch {
                Write-Log "DNS alias fallback failed for '$altHost': $($_.Exception.Message)"
            }
        } elseif ($lookupHost -match "^VNK-") {
            $altHost = $lookupHost -replace "^VNK-", "VNA-"
            try {
                $altAddresses = [System.Net.Dns]::GetHostAddresses($altHost)
                foreach ($alt in $altAddresses) {
                    if ($alt.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                        Write-Log "DNS alias fallback used: '$lookupHost' -> '$altHost'"
                        return $alt.ToString()
                    }
                }
            } catch {
                Write-Log "DNS alias fallback failed for '$altHost': $($_.Exception.Message)"
            }
        }
    }
    return $null
}

function Build-Candidates([string]$hostname, [string]$ip, [int]$port) {
    $result = New-Object System.Collections.Generic.List[string]
    $seen = @{}

    # Prefer direct IP targets first; hostname can be unreliable on some operator PCs.
    foreach ($item in @($ip, $(if ($ip) { "$ip`:$port" } else { $null }), $hostname)) {
        if (-not $item) { continue }
        foreach ($candidate in @($item, ">$item")) {
            if (-not $seen.ContainsKey($candidate)) {
                $seen[$candidate] = $true
                $result.Add($candidate)
            }
        }
    }
    return $result
}

function Test-TcpPort([string]$target, [int]$port, [int]$timeoutMs = 700) {
    if (-not $target) { return $false }
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($target, $port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($timeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($iar) | Out-Null
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Find-NetSupportExecutable {
    $paths = @(
        "C:\Program Files (x86)\NetSupport\NetSupport Manager\Pcictlui.exe",
        "C:\Program Files\NetSupport\NetSupport Manager\Pcictlui.exe",
        "C:\Program Files (x86)\NetSupport\NetSupport Manager\PCICTLUI.EXE",
        "C:\Program Files\NetSupport\NetSupport Manager\PCICTLUI.EXE"
    )

    foreach ($path in $paths) {
        if (Test-Path $path) { return $path }
    }

    foreach ($reg in @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Pcictlui.exe",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Pcictlui.exe"
    )) {
        try {
            $appPath = (Get-ItemProperty -Path $reg -ErrorAction Stop)."(Default)"
            if ($appPath -and (Test-Path $appPath)) { return $appPath }
        } catch {
            # ignore missing registry keys
        }
    }

    return $null
}

function Is-NetSupportAlreadyOpen {
    $proc = Get-Process -Name "Pcictlui" -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $proc
}

function Is-IPv4([string]$value) {
    if (-not $value) { return $false }
    return $value -match "^(?:\d{1,3}\.){3}\d{1,3}$"
}

$targetData = Resolve-TargetFromUri -rawUri $Uri
Write-Log "Incoming URI: $Uri"
if (-not $targetData) {
    Show-Error "Cannot parse target from URI: $Uri"
    exit 1
}

$targetHost = Normalize-Target -target $targetData.Host
if (-not $targetHost) {
    Show-Error "Invalid host in URI: $Uri"
    exit 1
}

$targetPort = Normalize-Port -portRaw $targetData.Port
$targetIp = Resolve-IPv4 -hostname $targetHost -providedIp $targetData.Ip
Write-Log "Parsed host raw: $($targetData.Host)"
Write-Log "Parsed ip raw: $($targetData.Ip)"
Write-Log "Parsed port raw: $($targetData.Port)"
Write-Log "Parsed raw mode: $($targetData.Raw)"
$candidates = Build-Candidates -hostname $targetHost -ip $targetIp -port $targetPort
if ($candidates.Count -eq 0 -and $targetHost) {
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add($targetHost)
    $candidates.Add(">$targetHost")
}
if ($candidates.Count -eq 0) {
    Show-Error "No connect candidates built from URI: $Uri"
    exit 1
}

Write-Log "Resolved host: $targetHost"
Write-Log "Resolved ip: $targetIp"
Write-Log "Candidates: $($candidates -join ', ')"

$selectedTarget = $targetHost
if ($targetData.Raw -eq "1") {
    # Explicit target mode: do not rewrite host to resolved IP.
    $selectedTarget = $targetHost
} else {
    if ($targetIp -and (Test-TcpPort -target $targetIp -port $targetPort)) {
        $selectedTarget = $targetIp
    } elseif (Test-TcpPort -target $targetHost -port $targetPort) {
        $selectedTarget = $targetHost
    } elseif ($targetIp) {
        # No reachable endpoint detected quickly; prefer IP first.
        $selectedTarget = $targetIp
    }
}
Write-Log "Selected target: $selectedTarget"

$exe = Find-NetSupportExecutable
if (-not $exe) {
    Show-Error "Pcictlui.exe not found. Install NetSupport Manager."
    exit 1
}
Write-Log "Using executable: $exe"

try {
    $alreadyOpen = Is-NetSupportAlreadyOpen
    Write-Log "NetSupport already open before send: $alreadyOpen"
    if ($alreadyOpen) {
        # Some NetSupport builds ignore connect args when an instance is already running.
        Stop-Process -Name "Pcictlui" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 250
        Write-Log "Restarted NetSupport process to force command-line connect handling."
    }
    $parts = Split-HostPort -target $selectedTarget -defaultPort $targetPort
    $useDirectName = ($targetData.Raw -eq "1") -and (-not (Is-IPv4 -value $parts.HostValue)) -and (-not $parts.HostValue.Contains(":"))
    if ($useDirectName) {
        # Raw mode for host aliases: pass exact client name.
        $args = @("/U", "TC", "/C", $parts.HostValue, "/VC")
    } else {
        # Address mode: older NetSupport builds expect ">address" syntax.
        $addrToken = ">$($parts.HostValue):$($parts.Port)"
        $args = @("/U", "TC", "/C", $addrToken)
        $normalizedHost = Normalize-Target -target $targetHost
        if ($normalizedHost -and $normalizedHost -ne $parts.HostValue -and -not $normalizedHost.Contains(":")) {
            $args += @("/C", $normalizedHost)
        }
        $args += @("/VC")
    }
    Start-Process -FilePath $exe -ArgumentList $args
    Write-Log "Connect command sent: $($args -join ' ')"
    if (Is-NetSupportAlreadyOpen) {
        Write-Log "NetSupport process detected after command."
    }
} catch {
    Show-Error "Failed to start NetSupport Manager: $($_.Exception.Message)"
    exit 1
}
