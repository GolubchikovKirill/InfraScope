$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$handlerPath = Join-Path $scriptDir "NetSupportUriHandler.ps1"

if (-not (Test-Path $handlerPath)) {
    throw "Не найден обработчик: $handlerPath"
}

$protocolKey = "HKCU:\Software\Classes\infrascope-nsm"
$command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$handlerPath`" `"%1`""

New-Item -Path $protocolKey -Force | Out-Null
New-ItemProperty -Path $protocolKey -Name "(Default)" -Value "URL:InfraScope NetSupport Protocol" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $protocolKey -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null
New-Item -Path "$protocolKey\shell\open\command" -Force | Out-Null
New-ItemProperty -Path "$protocolKey\shell\open\command" -Name "(Default)" -Value $command -PropertyType String -Force | Out-Null

Write-Host "InfraScope NetSupport helper installed."
Write-Host "Test with: infrascope-nsm://HOSTNAME"
