# InfraScope Media Client

Lightweight Go client for nettop media playback.

The client polls `media-service` for a device manifest and starts a local player
when the assigned media revision changes.

## Run

On Windows, place these files in one folder:

- `infrascope-media-agent-windows-amd64.exe`
- `run-media-agent.cmd`
- `install-media-agent.cmd`
- `media-agent.json`

Recommended setup:

1. Run `install-media-agent.cmd`
2. Fill server URL, device UUID, token (optional), and player path
3. Start `run-media-agent.cmd`

Manual config (optional):

```json
{
  "server": "http://10.10.98.10:8014",
  "device_id": "PASTE_DEVICE_UUID_HERE",
  "token": "",
  "player": "C:\\Program Files\\mpv\\mpv.exe",
  "interval_seconds": 10
}
```

Then double-click `run-media-agent.cmd`.

Command-line run is also supported:

```bash
go run ./cmd/media-agent \
  -server http://infrascope.local:8014 \
  -device-id <media-player-uuid> \
  -token <MEDIA_CLIENT_TOKEN> \
  -player mpv
```

Environment variables:

- `MEDIA_SERVICE_URL`
- `MEDIA_DEVICE_ID`
- `MEDIA_CLIENT_TOKEN`
- `MEDIA_PLAYER_BIN`
- `MEDIA_POLL_INTERVAL_SECONDS`

Install `mpv` or set `MEDIA_PLAYER_BIN=vlc`.
