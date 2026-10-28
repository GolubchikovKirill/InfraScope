"""Reconciliation between the RustDesk console, InfraScope inventory and the fleet.

Four jobs live here:

* **Inventory mirror.** Every cash register, computer and nettop media player
  becomes a `RemoteAccessDevice` row carrying the config that machine should end
  up with (id, password, lockdown switches).
* **Console accounts.** Engineers get their own RustDesk login, in a console
  group that the shared address book is shared with, so each of them sees the
  whole fleet without a per-user push.
* **Shared address book.** One console collection holds every managed device
  *with its password*, so connecting is one click and nobody types a secret.
* **Rollout state.** The endpoint script reports what it actually did; we store
  that verbatim and never infer it.

InfraScope does not remote-execute anything: the endpoint pulls its installer
and config (see `deploy_script`). What lands here is the report.

The package splits that along the same lines:

  devices       the device row: identity, password, deploy profile, readiness
  inventory     the inventory mirror (seed / link / refresh / release)
  console       reconciliation with the RustDesk console, unlisted peers
  deployment    endpoint config, source check, deploy reports
  accounts      engineers' console accounts and the console group
  address_book  the shared address book

Callers keep using `from app.domains.remote_access import service` and
`service.<name>`; everything is re-exported here.
"""
from app.domains.remote_access import rustdesk_client  # noqa: F401  (service.rustdesk_client is patched in tests)

from . import (
    accounts,  # noqa: F401
    address_book,  # noqa: F401
    console,  # noqa: F401
    deployment,  # noqa: F401
    devices,  # noqa: F401
    inventory,  # noqa: F401
)
from .accounts import (  # noqa: F401
    ensure_console_group,
    ensure_shared_book,
    provision_account,
    reset_account_password,
    set_account_active,
    sync_accounts,
)
from .address_book import (  # noqa: F401
    _ab_payload,
    address_book_status,
    push_shared_address_book,
    sync_address_book,
    sync_stale_address_book,
)
from .console import (  # noqa: F401
    FAILED_HEAL_AFTER,
    _failure_outlived,
    _peer_last_online,
    _peer_online,
    adopt_peer,
    dismiss_peer,
    list_unlisted_console_peers,
    sync_from_console,
)
from .deployment import (  # noqa: F401
    _resolve_hostname_ip,
    apply_deploy_report,
    deployment_config,
    mark_deploy_requested,
    package_config,
    verify_deploy_source,
)
from .devices import (  # noqa: F401
    _APPLOCKER_UNSUPPORTED_EDITION_PREFIXES,
    _DEPLOYED_STATES,
    _NETTOP,
    _PW_ALPHABET,
    _SOURCE_RANK,
    DEPLOY_PROFILES,
    DEPLOY_STALLED_AFTER,
    DEPLOY_STATES,
    READINESS,
    _find_device,
    _get_or_create_device,
    _hostname_to_rid,
    _now,
    apply_deploy_profile,
    classify_applocker_support,
    default_password,
    delete_device,
    generate_password,
    hostname_type_tag,
    mark_config_stale,
    readiness,
    resolve_scope,
    rotate_password,
    suggested_profile,
)
from .inventory import (  # noqa: F401
    _cr_location,
    _inventory_maps,
    _inventory_rows,
    _inventory_status,
    _link_inventory,
    ensure_device,
    refresh_status_from_inventory,
    release_inventory_row,
    seed_from_inventory,
)
