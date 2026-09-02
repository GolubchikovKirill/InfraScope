# InfraScope RustDesk deploy agent

Applies InfraScope's desired RustDesk config to the fleet. Runs on **one**
domain-joined Windows box with local admin on the target machines (SMB + CIM/DCOM,
no WinRM). Mirrors `windows-media-agent`.

## Where to run it

The same domain box you used for the manual `rollout.ps1` / `Set-Passwords-AsAdmin.ps1`
runs — anything domain-joined with a Domain Admin (or an account that is local admin
on the fleet) and line of sight to port 445 on the targets and 443 on
`10.10.99.24`. It does not have to be the InfraScope server.

## Setup (run in an elevated cmd on that box)

```cmd
:: 1. get the code onto the box (git clone, or copy the windows-rustdesk-agent folder)
cd windows-rustdesk-agent

:: 2. one-time: creates rustdesk-agent.json (prompts) + registers a SYSTEM task at boot, and starts it
install-rustdesk-agent.cmd
```

Answers to the prompts:

| prompt | value |
|---|---|
| InfraScope server URL | `https://10.10.99.24` |
| Agent id | `deploy01` |
| Deploy agent token | value of `RUSTDESK_DEPLOY_AGENT_TOKEN` in the server's `~/InfraScope/.env` |
| Installer dir | UNC share holding `rustdesk-1.4.9-x86_64.exe`, e.g. `\\regstaer.local\NETLOGON\RustDesk` |

To watch it live instead of via the scheduled task:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File .\rustdesk-agent.ps1
```

Stop the task: `schtasks /End /TN "InfraScope-RustDesk-Agent"` ·
Remove: `schtasks /Delete /TN "InfraScope-RustDesk-Agent" /F`

**Account:** the agent talks to the fleet over `\\host\C$` + CIM/DCOM, so it
must run as a **domain account with local admin on the targets** — the same
account you use for the manual rollout. `install-rustdesk-agent.cmd` registers
the task under whoever runs it (schtasks prompts for that password so it can
run logged-off). Do **not** run it as SYSTEM — SYSTEM authenticates to the
network as the machine account and can't reach the fleet.

> InfraScope's HTTPS cert is self-signed; the agent trusts it explicitly
> (`ServerCertificateValidationCallback`) since it only ever talks to
> `10.10.99.24` on the LAN with the shared token.

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
