@echo off
setlocal
set "DIR=%~dp0"
set "CONFIG=%DIR%media-agent.json"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$configPath = [IO.Path]::GetFullPath('%CONFIG%');" ^
  "$defaultServer = 'http://127.0.0.1:8014';" ^
  "$defaultPlayer = if (Test-Path 'C:\Program Files\VideoLAN\VLC\vlc.exe') { 'C:\Program Files\VideoLAN\VLC\vlc.exe' } elseif (Test-Path 'C:\Program Files\mpv\mpv.exe') { 'C:\Program Files\mpv\mpv.exe' } else { 'mpv' };" ^
  "Write-Host '=== InfraScope Media Client Setup ===' -ForegroundColor Cyan;" ^
  "$server = Read-Host ('Server URL [' + $defaultServer + ']'); if ([string]::IsNullOrWhiteSpace($server)) { $server = $defaultServer };" ^
  "$deviceId = Read-Host 'Device UUID (из карточки устройства в InfraScope)';" ^
  "if ([string]::IsNullOrWhiteSpace($deviceId)) { throw 'Device UUID is required' };" ^
  "$token = Read-Host 'Token (можно пусто, если не задан на сервере)';" ^
  "$player = Read-Host ('Player path [' + $defaultPlayer + ']'); if ([string]::IsNullOrWhiteSpace($player)) { $player = $defaultPlayer };" ^
  "$intervalRaw = Read-Host 'Polling interval seconds [10]'; if ([string]::IsNullOrWhiteSpace($intervalRaw)) { $interval = 10 } else { $interval = [int]$intervalRaw };" ^
  "if ($interval -lt 3) { $interval = 3 };" ^
  "$cfg = [ordered]@{ server=$server.TrimEnd('/'); device_id=$deviceId.Trim(); token=$token; player=$player; interval_seconds=$interval };" ^
  "$json = $cfg | ConvertTo-Json -Depth 4;" ^
  "Set-Content -LiteralPath $configPath -Value $json -Encoding UTF8;" ^
  "Write-Host ('Config saved: ' + $configPath) -ForegroundColor Green;" ^
  "Write-Host 'Done. Use run-media-agent.cmd to start the client.' -ForegroundColor Green;"

if errorlevel 1 (
  echo Ошибка настройки клиента.
  pause
  exit /b 1
)

exit /b 0
