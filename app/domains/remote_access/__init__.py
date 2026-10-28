"""Remote access (self-hosted RustDesk) wrapper.

InfraScope owns the console side of the fleet end to end: who can connect, what
they see, what each machine's client is configured to be, and whether that
machine is actually reachable right now.

* `rustdesk_client` talks to the `lejianwen/rustdesk-api` console. One token
  opens both of its API surfaces - the client API reads `Authorization: Bearer`,
  the admin API reads `api-token` - so we send both headers and get console
  accounts, shared address books, the peer inventory (with client versions) and
  the audit log behind InfraScope's own auth, with no second login.

* `service` mirrors the InfraScope endpoint inventory (cash registers,
  computers, nettop media players) into device rows, holds each machine's
  desired config, provisions engineer accounts into a console group, keeps the
  shared address book (passwords included, so connecting is one click), and
  records the rollout state each endpoint reports.

* `deploy_script` renders the PowerShell an endpoint runs to install and
  configure itself, for the GPO/pull rollout and (triggered remotely, see
  below) for a network push alike.

* `push_jobs` queues "roll this out to device X now" and runs it over WinRM
  (`winrm_exec`) - the sanctioned Windows remote-admin protocol, not SMB
  admin-share + WMI/DCOM execution (what the push kit historically used from a
  separate Windows admin host; that technique is what EDR correlates with
  lateral movement). See docs/rustdesk-deployment.md.
"""
