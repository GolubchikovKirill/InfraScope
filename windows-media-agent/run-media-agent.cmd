@echo off
setlocal
set "DIR=%~dp0"
set "CONFIG=%DIR%media-agent.json"

if not exist "%CONFIG%" (
  echo Не найден media-agent.json. Запускаю мастер первичной настройки клиента...
  call "%DIR%install-media-agent.cmd"
  if errorlevel 1 exit /b 1
)

"%DIR%infrascope-media-agent-windows-amd64.exe" -config "%CONFIG%"
pause
