import asyncio
from datetime import UTC, datetime

from app.domains.remote_access import service
from app.domains.remote_access.models import RemoteAccessDevice


def test_sync_does_not_replace_operator_target_with_numeric_peer(db_session, monkeypatch):
    device = RemoteAccessDevice(hostname="VNA-MGR-101", rustdesk_id="CUSTOM_ID_101")
    db_session.add(device)
    db_session.commit()

    async def peers():
        return [{"id": "123456789", "hostname": device.hostname,
                 "last_online_time": int(datetime.now(UTC).timestamp())}]

    monkeypatch.setattr(service.rustdesk_client, "list_admin_peers", peers)
    asyncio.run(service.sync_from_console(db_session))
    assert device.rustdesk_id == "CUSTOM_ID_101"
    assert device.observed_rustdesk_id == "123456789"
    assert service.deployment_config(device)["rustdesk_id"] == "CUSTOM_ID_101"
