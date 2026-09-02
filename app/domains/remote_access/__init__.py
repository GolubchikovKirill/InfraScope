"""Remote access (self-hosted RustDesk) wrapper.

Two responsibilities, matching how InfraScope already splits work:

* control plane - the RustDesk *console* (address book, users, live connections,
  device status) is `lejianwen/rustdesk-api`, running next to hbbs/hbbr outside
  this app. `rustdesk_client` proxies a curated slice of its REST API so
  InfraScope admins manage it behind InfraScope auth, no second login.

* deployment plane - installing/configuring/locking-down the RustDesk client on
  the fleet is InfraScope's own job (no RustDesk API covers it). `service`
  reconciles a desired per-device config (server, hostname ID, per-machine
  rotatable password, hide-from-user, block-outgoing) into `RemoteAccessDeployJob`
  rows that a Windows agent claims and executes.
"""
