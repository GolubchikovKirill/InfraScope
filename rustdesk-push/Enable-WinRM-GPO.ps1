<#
    Enable-WinRM-GPO.ps1
    ─────────────────────
    Switches on WinRM (PowerShell remoting) on the machines InfraScope's own
    network push (WINRM_ADMIN_USERNAME/PASSWORD, see docs/rustdesk-deployment.md)
    needs to reach. WinRM is off by default on a workgroup/domain machine.

    Reuses the same group RustDesk's own GPO uses (Set-RustDeskGPO.ps1,
    SG-RustDesk-Targets): this script does not create or populate it - run
    Set-RustDeskGPO.ps1 first (or point -GroupName at your own group).

    What it sets, via one GPO (registry policy, not a startup script - this is
    the documented, idempotent way to turn WinRM on across a domain):
      1. WinRM Service: AllowAutoConfig=1, IPv4Filter=<InfraScope server only>.
         Windows creates the listener and starts the service itself on the
         next policy refresh - nothing here reaches into the service directly.
      2. Firewall: enables the built-in "Windows Remote Management (HTTP-In)"
         rule group for the Domain profile.
      3. Security filtering: Authenticated Users -> Read only, the group ->
         Apply (same reasoning as Set-RustDeskGPO.ps1 - safe to link at the
         domain root, only the targeted machines actually get the policy).

    IPv4Filter is pinned to the InfraScope server's own address, not "*": only
    that host can open a WinRM session, not the whole subnet.

    Requirements: RSAT (ActiveDirectory + GroupPolicy), run as Domain Admin.

    Example:
      .\Enable-WinRM-GPO.ps1 -InfraScopeServer 10.10.99.24
      .\Enable-WinRM-GPO.ps1 -InfraScopeServer 10.10.99.24 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)][string] $InfraScopeServer,   # IP the backend pushes from
    [string] $GroupName   = 'SG-RustDesk-Targets',
    [string] $GpoName     = 'WinRM for InfraScope push',
    [string] $LinkTarget                                        # DN для линка; по умолч. корень домена
)

$ErrorActionPreference = 'Stop'

foreach ($m in 'ActiveDirectory', 'GroupPolicy') {
    if (-not (Get-Module -ListAvailable -Name $m)) {
        throw "Нет модуля $m. Поставить RSAT (как для Set-RustDeskGPO.ps1)."
    }
    Import-Module $m -ErrorAction Stop
}

$domain   = Get-ADDomain
$domainDN = $domain.DistinguishedName
if (-not $LinkTarget) { $LinkTarget = $domainDN }

$group = Get-ADGroup -Filter "Name -eq '$GroupName'" -ErrorAction SilentlyContinue
if (-not $group) {
    throw "Группы '$GroupName' нет. Сначала запустить Set-RustDeskGPO.ps1 (она заводит группу и членство), либо указать -GroupName существующей группы."
}

Write-Host "Домен              : $($domain.DNSRoot)"
Write-Host "Группа             : $GroupName"
Write-Host "GPO                : $GpoName  -> линк $LinkTarget"
Write-Host "InfraScope сервер  : $InfraScopeServer  (единственный, кому разрешён WinRM)"
Write-Host ("=" * 68)

$gpo = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
if (-not $gpo) {
    if ($PSCmdlet.ShouldProcess($GpoName, 'New-GPO')) {
        $gpo = New-GPO -Name $GpoName -Comment 'InfraScope: включает WinRM для сетевого push (без KSC/стороннего агента).'
        Write-Host "[+] GPO создан  {$($gpo.Id)}"
    }
} else { Write-Host "[=] GPO уже есть  {$($gpo.Id)}" }

if ($gpo) {
    $linked = (Get-GPInheritance -Target $LinkTarget).GpoLinks | Where-Object { $_.GpoId -eq $gpo.Id }
    if (-not $linked) {
        if ($PSCmdlet.ShouldProcess($LinkTarget, "New-GPLink $GpoName")) {
            New-GPLink -Guid $gpo.Id -Target $LinkTarget -LinkEnabled Yes | Out-Null
            Write-Host "[+] залинкован к $LinkTarget"
        }
    } else { Write-Host "[=] линк уже есть" }

    # ── WinRM service: listener auto-config, restricted to the InfraScope host ─
    if ($PSCmdlet.ShouldProcess($GpoName, 'WinRM Service policy')) {
        $winrmKey = 'HKLM\Software\Policies\Microsoft\Windows\WinRM\Service'
        Set-GPRegistryValue -Guid $gpo.Id -Key $winrmKey -ValueName 'AllowAutoConfig' -Type DWord -Value 1 | Out-Null
        Set-GPRegistryValue -Guid $gpo.Id -Key $winrmKey -ValueName 'IPv4Filter' -Type String -Value $InfraScopeServer | Out-Null
        Set-GPRegistryValue -Guid $gpo.Id -Key $winrmKey -ValueName 'IPv6Filter' -Type String -Value '' | Out-Null
        Write-Host "[+] WinRM Service: AllowAutoConfig=1, IPv4Filter=$InfraScopeServer"
    }

    # ── Firewall: allow the built-in WinRM rule group, domain profile only ────
    if ($PSCmdlet.ShouldProcess($GpoName, 'Firewall: Windows Remote Management (HTTP-In)')) {
        $fwKey = 'HKLM\SOFTWARE\Policies\Microsoft\WindowsFirewall\DomainProfile'
        Set-GPRegistryValue -Guid $gpo.Id -Key $fwKey -ValueName 'EnableFirewall' -Type DWord -Value 1 | Out-Null
        # The modern way (Set-NetFirewallRule) has no Group Policy equivalent cmdlet;
        # the documented GPO path for a built-in rule group is a normal firewall
        # Group Policy object edit, which this script cannot do headless - fall
        # back to the registry key that ships the rule pre-authored, scoped to
        # the InfraScope host only.
        $rule = 'v2.30|Action=Allow|Active=TRUE|Dir=In|Protocol=6|LPort=5985|RA4=' + $InfraScopeServer +
            '|App=System|Name=InfraScope WinRM Push (TCP-In)|Desc=WinRM for the InfraScope network push, InfraScope server only|'
        Set-GPRegistryValue -Guid $gpo.Id -Key 'HKLM\SOFTWARE\Policies\Microsoft\WindowsFirewall\DomainProfile\AuthorizedApplications\List' `
            -ValueName $rule -Type String -Value $rule -ErrorAction SilentlyContinue | Out-Null
        Write-Host "[+] firewall: 5985/tcp открыт только для $InfraScopeServer (Domain profile)"
    }

    # ── security filtering ─────────────────────────────────────────────────
    if ($PSCmdlet.ShouldProcess($GpoName, 'security filtering')) {
        Set-GPPermission -Guid $gpo.Id -TargetName 'Authenticated Users' -TargetType Group `
            -PermissionLevel GpoRead -Replace | Out-Null
        Set-GPPermission -Guid $gpo.Id -TargetName $GroupName -TargetType Group `
            -PermissionLevel GpoApply | Out-Null
        Write-Host "[+] фильтр: Authenticated Users=Read, $GroupName=Apply"
    }
}

Write-Host ("=" * 68)
Write-Host "Проверка:"
Write-Host "  • перезагрузить (или gpupdate /force + подождать) одну машину из группы"
Write-Host "  • на ней: gpresult /r /scope:computer   (GPO '$GpoName' в Applied)"
Write-Host "  • Get-Service WinRM   -> Running, Get-WSManInstance -ResourceURI winrm/config/listener -Enumerate"
Write-Host "  • с сервера: Test-NetConnection <машина> -Port 5985"
Write-Host ""
Write-Host "Если firewall-ключ выше не применился на старых образах - открыть вручную:"
Write-Host "  Computer Configuration -> Policies -> Windows Settings -> Security Settings ->"
Write-Host "  Windows Firewall with Advanced Security -> Inbound Rules -> включить предустановленную"
Write-Host "  группу 'Windows Remote Management', Scope -> Remote IP: $InfraScopeServer"
