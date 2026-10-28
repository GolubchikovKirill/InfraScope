<#
    Set-RustDeskGPO.ps1
    ───────────────────
    Канал доставки RustDesk: computer startup script через GPO.
    Запуск при загрузке от SYSTEM, без удалённого исполнения — групповые
    политики и запуск скриптов при старте защитное ПО не расценивает как lateral movement.

    Скрипт делает надёжно-скриптуемую часть:
      1. группа SG-RustDesk-Targets (Global Security)
      2. заводит в неё компьютерные учётки из rustdesk-targets-no-kkm.txt
      3. создаёт GPO, линкует к корню домена
      4. security-filtering: Authenticated Users -> только Read, группа -> Apply
         (поэтому линк к корню безопасен и обходит проблему ~69 машин в CN=Computers)

    Одно НЕ трогает автоматически (по опыту рвётся на версии GPO/scripts.ini):
      5. саму строку startup-скрипта -> добавить руками в GPMC (инструкция в конце),
         либо запустить с -WireStartupScript (SYSVOL-метод, требует прав на SYSVOL).

    Требования: RSAT (ActiveDirectory + GroupPolicy), запуск от Domain Admin.
    Харнес Claude блокирует запись в AD — этот скрипт запускает пользователь.

    Пример:
      .\Set-RustDeskGPO.ps1 -WhatIfMembership
      .\Set-RustDeskGPO.ps1
      .\Set-RustDeskGPO.ps1 -WireStartupScript
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $GroupName   = 'SG-RustDesk-Targets',
    [string] $GroupPath,                                   # OU для группы; по умолч. CN=Users,<domainDN>
    [string] $GpoName     = 'RustDesk Deploy (InfraScope)',
    [string] $KitCmd      = '\\vnk-srv-backup1\Install\RustDesk-Deploy\rustdesk-run.cmd',
    [string] $TargetsFile = (Join-Path $PSScriptRoot 'rustdesk-targets-no-kkm.txt'),
    [string] $LinkTarget,                                  # DN для линка; по умолч. корень домена
    [switch] $WireStartupScript,
    [switch] $WhatIfMembership
)

$ErrorActionPreference = 'Stop'

foreach ($m in 'ActiveDirectory','GroupPolicy') {
    if (-not (Get-Module -ListAvailable -Name $m)) {
        throw "Нет модуля $m. Поставить RSAT: Add-WindowsCapability -Online -Name Rsat.$($m -replace 'ActiveDirectory','ActiveDirectory.DS-LDS.Tools' -replace 'GroupPolicy','GroupPolicy.Management.Tools')~~~~0.0.1.0"
    }
    Import-Module $m -ErrorAction Stop
}

$domain   = Get-ADDomain
$domainDN = $domain.DistinguishedName
if (-not $GroupPath)  { $GroupPath  = "CN=Users,$domainDN" }
if (-not $LinkTarget) { $LinkTarget = $domainDN }
# SYSVOL writes below target this one DC by name, not the \\<domain>\SysVol DFS
# namespace: that namespace can hand two UNC calls seconds apart to different
# DCs, so a Set-Content on one and a Get-Item on the other sees "not found"
# before DFSR replicates. Pinning to the PDC emulator makes write-then-read
# within a single run consistent regardless of replication lag.
$sysvolHost = $domain.PDCEmulator

Write-Host "Домен      : $($domain.DNSRoot)"
Write-Host "Группа      : $GroupName  ($GroupPath)"
Write-Host "GPO         : $GpoName  -> линк $LinkTarget"
Write-Host "Startup cmd : $KitCmd"
Write-Host ("=" * 68)

# ── 1. группа ───────────────────────────────────────────────────────────────
$group = Get-ADGroup -Filter "Name -eq '$GroupName'" -ErrorAction SilentlyContinue
if (-not $group) {
    if ($PSCmdlet.ShouldProcess($GroupName, 'New-ADGroup')) {
        $group = New-ADGroup -Name $GroupName -GroupScope Global -GroupCategory Security `
            -Path $GroupPath -Description 'Компьютеры, на которые GPO раскатывает RustDesk (InfraScope)' -PassThru
        Write-Host "[+] группа создана"
    }
} else { Write-Host "[=] группа уже есть" }

# ── 2. членство ─────────────────────────────────────────────────────────────
if (-not (Test-Path $TargetsFile)) { throw "Нет файла целей: $TargetsFile" }
$targets = Get-Content $TargetsFile |
    ForEach-Object { ($_ -replace '#.*$', '').Trim() } |
    Where-Object { $_ }

$current = @{}
if ($group) {
    Get-ADGroupMember $group -ErrorAction SilentlyContinue |
        ForEach-Object { $current[$_.SamAccountName.TrimEnd('$').ToUpper()] = $true }
}

$add = @(); $missing = @()
foreach ($name in $targets) {
    $comp = Get-ADComputer -Filter "Name -eq '$name'" -ErrorAction SilentlyContinue
    if (-not $comp)                                  { $missing += $name; continue }
    if ($current.ContainsKey($name.ToUpper()))       { continue }
    $add += $comp
}

Write-Host "Целей в файле : $($targets.Count)"
Write-Host "Уже в группе  : $($current.Count)"
Write-Host "К добавлению  : $($add.Count)  -> $([string]::Join(', ', @($add.Name)))"
if ($missing) { Write-Warning "Нет объекта AD (проверить имя/переименовать): $([string]::Join(', ', $missing))" }

if ($add -and -not $WhatIfMembership) {
    if ($PSCmdlet.ShouldProcess("$($add.Count) computer(s)", "Add-ADGroupMember $GroupName")) {
        Add-ADGroupMember -Identity $group -Members $add
        Write-Host "[+] добавлено в группу"
    }
} elseif ($WhatIfMembership) {
    Write-Host "[i] -WhatIfMembership: членство не менялось"
}

# ── 3. GPO + линк ──────────────────────────────────────────────────────────
$gpo = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
if (-not $gpo) {
    if ($PSCmdlet.ShouldProcess($GpoName, 'New-GPO')) {
        $gpo = New-GPO -Name $GpoName -Comment 'InfraScope: computer startup script ставит RustDesk.'
        Write-Host "[+] GPO создан  {$($gpo.Id)}"
    }
} else { Write-Host "[=] GPO уже есть  {$($gpo.Id)}" }

if ($gpo) {
    $linked = (Get-GPInheritance -Target $LinkTarget).GpoLinks | Where-Object { $_.GpoId -eq $gpo.Id }
    if (-not $linked) {
        if ($PSCmdlet.ShouldProcess("$LinkTarget", "New-GPLink $GpoName")) {
            New-GPLink -Guid $gpo.Id -Target $LinkTarget -LinkEnabled Yes | Out-Null
            Write-Host "[+] залинкован к $LinkTarget"
        }
    } else { Write-Host "[=] линк уже есть" }

    # ── 4. security filtering ─────────────────────────────────────────────
    if ($PSCmdlet.ShouldProcess($GpoName, 'security filtering')) {
        Set-GPPermission -Guid $gpo.Id -TargetName 'Authenticated Users' -TargetType Group `
            -PermissionLevel GpoRead -Replace | Out-Null
        Set-GPPermission -Guid $gpo.Id -TargetName $GroupName -TargetType Group `
            -PermissionLevel GpoApply | Out-Null
        Write-Host "[+] фильтр: Authenticated Users=Read, $GroupName=Apply"
    }

    # ── 4b. Always wait for the network at computer startup and logon ──────
    # Without this, background (async) GPO processing is the default after the
    # first ever boot - the computer starts running its startup scripts before
    # the network stack is actually usable, so a script whose only job is a
    # UNC path to \\vnk-srv-backup1\... can silently fail with nothing to show
    # for it (no error, no log - the network share was simply not there yet).
    # Registry.pol (Administrative Templates) applies reliably even on an
    # async pass, so this converges within one reboot; the *scripts* CSE that
    # reads it synchronously only benefits starting the reboot after that.
    if ($PSCmdlet.ShouldProcess($GpoName, 'Always wait for the network at computer startup and logon')) {
        Set-GPRegistryValue -Guid $gpo.Id -Key 'HKLM\Software\Policies\Microsoft\Windows\System' `
            -ValueName 'SyncForegroundPolicy' -Type DWord -Value 1 | Out-Null
        Write-Host "[+] policy: SyncForegroundPolicy=1 (wait for network at startup)"
    }

    # ── 5. startup-скрипт ────────────────────────────────────────────────
    if ($WireStartupScript) {
        $guid    = "{$($gpo.Id.ToString().ToUpper())}"
        $polDir  = "\\$sysvolHost\SysVol\$($domain.DNSRoot)\Policies\$guid\Machine\Scripts"
        $startup = Join-Path $polDir 'Startup'
        New-Item -ItemType Directory -Force -Path $startup | Out-Null
        $ini = Join-Path $polDir 'scripts.ini'
        @(
            '[Startup]'
            "0CmdLine=$KitCmd"
            '0Parameters='
        ) | Set-Content -Path $ini -Encoding Unicode
        # -Force: on a rerun the file is already Hidden from the previous pass,
        # and plain Get-Item does not return hidden items - it would find
        # nothing and the attribute assignment below would throw on $null.
        (Get-Item $ini -Force).Attributes = 'Hidden'

        # CSE GUIDs для Scripts + bump computer-версии в AD и GPT.INI
        $cse = '[{42B5FAAE-6536-11D2-AE5A-0000F87571E3}{40B6664F-4972-11D1-A7CA-0000F87571E3}]'
        $gpoObj = Get-ADObject "CN=$guid,CN=Policies,CN=System,$domainDN" -Properties gPCMachineExtensionNames,versionNumber
        if ($gpoObj.gPCMachineExtensionNames -notlike "*42B5FAAE-6536-11D2-AE5A-0000F87571E3*") {
            Set-ADObject $gpoObj.DistinguishedName -Replace @{ gPCMachineExtensionNames = ($gpoObj.gPCMachineExtensionNames + $cse) }
        }
        $newVer = [int]$gpoObj.versionNumber + 0x10000
        Set-ADObject $gpoObj.DistinguishedName -Replace @{ versionNumber = $newVer }
        $gptIni = "\\$sysvolHost\SysVol\$($domain.DNSRoot)\Policies\$guid\GPT.INI"
        Set-Content $gptIni "[General]`r`nVersion=$newVer" -Encoding Ascii
        Write-Host "[+] startup-скрипт вписан через SYSVOL, версия GPO -> $newVer"
    } else {
        Write-Host ""
        Write-Host "РУЧНОЙ ШАГ (GPMC) — вписать startup-скрипт:" -ForegroundColor Yellow
        Write-Host "  1. gpmc.msc -> '$GpoName' -> Edit"
        Write-Host "  2. Computer Configuration -> Policies -> Windows Settings -> Scripts (Startup/Shutdown)"
        Write-Host "  3. Startup -> Add -> Script Name: $KitCmd   (Parameters: пусто)"
        Write-Host "  4. Закрыть редактор (версия GPO поднимется сама)."
        Write-Host "  Либо перезапустить: .\Set-RustDeskGPO.ps1 -WireStartupScript"
    }
}

Write-Host ("=" * 68)
Write-Host "Проверка:"
Write-Host "  • пилот: перезагрузить одну машину из группы, затем на ней"
Write-Host "      gpresult /r /scope:computer   (GPO '$GpoName' в Applied)"
Write-Host "      type C:\ProgramData\InfraScope\rustdesk-configure.log"
Write-Host "  • через ~2 мин — readiness на странице «Удалённый доступ» в InfraScope"
Write-Host "  • ККМ добавляются позже: дописать имена в $TargetsFile и прогнать скрипт снова"
Write-Host ""
Write-Host "Если антивирус всё же удаляет rustdesk.exe как Trojan-agent — нужно правило"
Write-Host "доверенное приложение для %ProgramFiles%\RustDesk\rustdesk.exe в политике антивируса;"
Write-Host "канал доставки этого не решает."
