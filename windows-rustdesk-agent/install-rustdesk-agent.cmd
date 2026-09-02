@echo off
setlocal
set "DIR=%~dp0"
set "CONFIG=%DIR%rustdesk-agent.json"

if not exist "%CONFIG%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$c=[ordered]@{ server=(Read-Host 'InfraScope server URL [https://10.10.99.24]'); agent_id=(Read-Host 'Agent id [deploy01]'); token=(Read-Host 'Deploy agent token (RUSTDESK_DEPLOY_AGENT_TOKEN)'); poll_seconds=15; installer_dir=(Read-Host 'Installer dir (UNC to rustdesk-*-x86_64.exe)') };" ^
    "if(-not $c.server){$c.server='https://10.10.99.24'}; if(-not $c.agent_id){$c.agent_id='deploy01'};" ^
    "if(-not $c.installer_dir){$c.installer_dir=$env:DIR};" ^
    "($c|ConvertTo-Json)|Set-Content -LiteralPath '%CONFIG%' -Encoding UTF8; Write-Host 'saved %CONFIG%'"
  if errorlevel 1 exit /b 1
)

rem The agent reaches the fleet over \\host\C$ + CIM/DCOM, so it must run as a
rem domain account that is local admin on the targets - NOT as SYSTEM (SYSTEM
rem authenticates to the network as the machine account and cannot touch the fleet).
rem Registered here under the account running this script; schtasks prompts for
rem that account's password so the task can run when you're logged off.
echo Registering scheduled task 'InfraScope-RustDesk-Agent' as %USERDOMAIN%\%USERNAME% ...
schtasks /Create /TN "InfraScope-RustDesk-Agent" /RU "%USERDOMAIN%\%USERNAME%" /RL HIGHEST /SC ONSTART /F ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%DIR%rustdesk-agent.ps1\""
schtasks /Run /TN "InfraScope-RustDesk-Agent"
echo.
echo Done. Watch live:  powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%rustdesk-agent.ps1"
echo Stop: schtasks /End /TN "InfraScope-RustDesk-Agent"   Remove: schtasks /Delete /TN "InfraScope-RustDesk-Agent" /F
