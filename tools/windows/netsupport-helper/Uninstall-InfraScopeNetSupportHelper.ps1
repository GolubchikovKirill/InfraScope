$protocolKey = "HKCU:\Software\Classes\infrascope-nsm"

if (Test-Path $protocolKey) {
    Remove-Item -Path $protocolKey -Recurse -Force
    Write-Host "InfraScope NetSupport helper removed."
} else {
    Write-Host "Helper is not installed."
}
