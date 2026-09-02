# InfraScope RustDesk deploy agent

Applies InfraScope's desired RustDesk config to the fleet. Runs on **one**
domain-joined Windows box with local admin on the target machines (SMB + CIM/DCOM,
no WinRM). Mirrors `windows-media-agent`.

## Files
| file | purpose |
|---|---|
| `rustdesk-agent.ps1` | poll loop: claim job -> apply -> report |
| `apply-rustdesk.ps1` | pushed to each target, run as SYSTEM: install + config + hostname ID + covert flags + lockdown (shortcut strip, AppLocker deny non-admin launch) |
| `rustdesk-agent.example.json` | copy to `rustdesk-agent.json` and fill in |
| `install-rustdesk-agent.cmd` | first-run wizard + registers a SYSTEM scheduled task at startup |

Put the RustDesk installer (`rustdesk-1.4.9-x86_64.exe`) in `installer_dir`
(a share, e.g. `\\domain\NETLOGON\RustDesk\`).

## InfraScope side (`.env`)
```
REMOTE_ACCESS_ENABLED=true
RUSTDESK_API_URL=http://10.10.99.24:21114
RUSTDESK_API_TOKEN=<console -> API token>
RUSTDESK_ID_SERVER=10.10.99.24
RUSTDESK_RELAY_SERVER=10.10.99.24
RUSTDESK_KEY=<id_ed25519.pub of hbbs>
RUSTDESK_DEPLOY_AGENT_TOKEN=<random shared secret, also in rustdesk-agent.json>
```

## Flow
1. Admin picks devices in InfraScope -> `POST /api/v1/remote-access/deploy`
   (`deploy` / `reconfigure` / `rotate_password` / `set_lockdown` / `uninstall`).
2. InfraScope creates `RemoteAccessDeployJob` rows; first deploy also mints a
   per-machine random password (encrypted at rest).
3. Agent claims a job, fetches the password only when needed
   (`GET .../jobs/{id}/secret`), applies it, reports facts back
   (`installed_version`, `rustdesk_id`, `deploy_state`).
4. `POST /api/v1/remote-access/sync` refreshes live status from the console.

## Notes
- The permanent password is set by the agent via `Win32_Process.Create`
  (`rustdesk.exe --password <pw>`) in the agent account's admin context - the
  only context that persists it (SYSTEM tasks and non-admin users do not).
- `block_outgoing` needs the Application Identity service (`AppIDSvc`) running;
  the script sets it to Automatic and starts it.
- Cash registers (`*-KKM-*` / Win7/XP) are out of scope - keep them unmanaged.
