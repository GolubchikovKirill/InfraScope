@echo off
setlocal
set "DIR=%~dp0"
set "CONFIG=%DIR%rustdesk-agent.json"

if not exist "%CONFIG%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$c=[ordered]@{ server=(Read-Host 'InfraScope server URL [http://10.10.98.10]'); agent_id=(Read-Host 'Agent id [deploy01]'); token=(Read-Host 'Deploy agent token (RUSTDESK_DEPLOY_AGENT_TOKEN)'); poll_seconds=15; installer_dir=(Read-Host 'Installer dir (UNC to rustdesk-*-x86_64.exe)') };" ^
    "if(-not $c.server){$c.server='http://10.10.98.10'}; if(-not $c.agent_id){$c.agent_id='deploy01'};" ^
    "if(-not $c.installer_dir){$c.installer_dir=$env:DIR};" ^
    "($c|ConvertTo-Json)|Set-Content -LiteralPath '%CONFIG%' -Encoding UTF8; Write-Host 'saved %CONFIG%'"
  if errorlevel 1 exit /b 1
)

echo Registering scheduled task 'InfraScope-RustDesk-Agent' (SYSTEM, at startup)...
schtasks /Create /TN "InfraScope-RustDesk-Agent" /RU SYSTEM /RL HIGHEST /SC ONSTART /F ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%DIR%rustdesk-agent.ps1\""
schtasks /Run /TN "InfraScope-RustDesk-Agent"
echo Done. Logs: run the task interactively or check Event Viewer. Stop: schtasks /End /TN "InfraScope-RustDesk-Agent"
