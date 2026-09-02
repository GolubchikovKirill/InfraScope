"""Remote access (self-hosted RustDesk) wrapper.

InfraScope tracks and administers the self-hosted RustDesk fleet; it does not
push the client - that is rolled out through Kaspersky Security Center with a
preconfigured package (docs/rustdesk-ksc-deployment.md).

* `rustdesk_client` proxies a curated slice of the `lejianwen/rustdesk-api`
  console REST API (address book, users, live connections, peer status) so
  InfraScope admins manage it behind InfraScope auth, no second login.

* `service` mirrors the InfraScope endpoint inventory (cash registers, computers,
  nettop media players) into device rows, folds live status in from the console,
  holds each machine's desired package config (server, hostname ID, per-machine
  password, hide-from-user, block-outgoing), and owns the address-book push.
"""
