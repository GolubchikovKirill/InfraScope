from __future__ import annotations

import pytest
from sqlmodel import select

from app.api.routes import computers as computer_routes
from app.domains.inventory import computer_stale
from app.domains.inventory.models import Computer
from app.domains.remote_access import service as remote_access_service
from app.domains.remote_access.models import RemoteAccessDevice


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(computer_routes, "invalidate_computer_cache", _noop)


def _console(monkeypatch, hostnames: list[str] | Exception, *, enabled: bool = True):
    async def list_admin_peers():
        if isinstance(hostnames, Exception):
            raise hostnames
        return [{"hostname": h, "id": h} for h in hostnames]

    monkeypatch.setattr(computer_stale.rustdesk_client, "enabled", lambda: enabled)
    monkeypatch.setattr(computer_stale.rustdesk_client, "list_admin_peers", list_admin_peers)


def _add(db_session, hostname: str, *, online: bool | None) -> Computer:
    row = Computer(hostname=hostname, is_online=online)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_stale_list_requires_a_superuser(client, user_token: str):
    assert client.get("/api/v1/computers/stale").status_code == 401
    assert client.get("/api/v1/computers/stale", headers=_auth(user_token)).status_code == 403


def test_reports_computers_missing_from_the_console_and_not_answering(client, admin_token, db_session, monkeypatch):
    _add(db_session, "VNA-MGR-201", online=True)  # in the console
    _add(db_session, "VNA-MGR-202", online=False)  # gone: not in the console, silent
    _add(db_session, "VNA-MGR-203", online=True)  # not in the console but answers: a real machine without a client
    _console(monkeypatch, ["vna-mgr-201"])  # case-insensitive match

    body = client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()

    assert body["console_reachable"] is True
    assert [c["hostname"] for c in body["data"]] == ["VNA-MGR-202"]
    assert body["data"][0]["reason"] == computer_stale.REASON


def test_a_computer_never_polled_counts_as_not_answering(client, admin_token, db_session, monkeypatch):
    _add(db_session, "VNK-COM-003", online=None)
    _console(monkeypatch, ["someone-else"])

    body = client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()

    assert [c["hostname"] for c in body["data"]] == ["VNK-COM-003"]


def test_laptops_are_flagged_and_listed_after_the_rest(client, admin_token, db_session, monkeypatch):
    for host in ("VNK-TAM-NB01", "VNK-DIR-NOTE", "VNK-HR-N02", "VNK-LPT-01", "VNK-SEC-07"):
        _add(db_session, host, online=False)
    _console(monkeypatch, ["someone-else"])

    data = client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()["data"]

    assert [c["hostname"] for c in data][0] == "VNK-SEC-07"
    assert {c["hostname"] for c in data if c["laptop_like"]} == {"VNK-TAM-NB01", "VNK-DIR-NOTE", "VNK-HR-N02", "VNK-LPT-01"}
    assert next(c for c in data if c["hostname"] == "VNK-SEC-07")["laptop_like"] is False


@pytest.mark.parametrize(
    "console",
    [RuntimeError("console down"), []],
    ids=["console unreadable", "console lists nothing"],
)
def test_reports_nothing_when_the_console_cannot_be_trusted(client, admin_token, db_session, monkeypatch, console):
    _add(db_session, "VNA-MGR-202", online=False)
    _console(monkeypatch, console)

    body = client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()

    # an outage would make every computer look stale - so nothing is judged
    assert body == {"console_reachable": False, "count": 0, "data": []}


def test_reports_nothing_when_remote_access_is_not_configured(client, admin_token, db_session, monkeypatch):
    _add(db_session, "VNA-MGR-202", online=False)
    _console(monkeypatch, ["x"], enabled=False)

    assert client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()["console_reachable"] is False


def test_flags_computers_that_are_still_managed_in_remote_access(client, admin_token, db_session, monkeypatch):
    computer = _add(db_session, "VNA-MGR-202", online=False)
    db_session.add(RemoteAccessDevice(hostname="VNA-MGR-202", computer_id=computer.id, managed=True))
    db_session.commit()
    _console(monkeypatch, ["x"])

    data = client.get("/api/v1/computers/stale", headers=_auth(admin_token)).json()["data"]

    assert data[0]["in_remote_access"] is True


def test_deleting_a_computer_takes_its_remote_access_entry_out_of_management(client, admin_token, db_session, monkeypatch):
    """RemoteAccessDevice.computer_id is a foreign key: deleting the computer used to fail in the
    database whenever an entry pointed at it, and would otherwise leave a live-looking entry behind."""
    computer = _add(db_session, "VNA-MGR-202", online=False)
    device = RemoteAccessDevice(hostname="VNA-MGR-202", computer_id=computer.id, managed=True, in_address_book=True)
    db_session.add(device)
    db_session.commit()
    device_id = device.id
    removed_from_book: list[str] = []

    async def _no_console(*_a, **_kw):
        removed_from_book.append("called")

    monkeypatch.setattr(remote_access_service.rustdesk_client, "delete_address_book_row", _no_console)

    response = client.delete(f"/api/v1/computers/{computer.id}", headers=_auth(admin_token))

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.exec(select(Computer).where(Computer.hostname == "VNA-MGR-202")).first() is None
    kept = db_session.get(RemoteAccessDevice, device_id)
    assert kept is not None and kept.computer_id is None
    assert kept.managed is False and kept.in_address_book is False


def test_deleting_a_computer_without_a_remote_access_entry_still_works(client, admin_token, db_session):
    computer = _add(db_session, "VNA-MGR-300", online=False)

    assert client.delete(f"/api/v1/computers/{computer.id}", headers=_auth(admin_token)).status_code == 200


@pytest.mark.parametrize(
    ("kind", "url"),
    [("cash_register", "/api/v1/cash-registers/{id}"), ("media_player", "/api/v1/media-players/{id}")],
)
def test_deleting_a_cash_register_or_media_player_releases_its_remote_access_entry(client, admin_token, db_session, monkeypatch, kind, url):
    """Same foreign key as for computers: NO ACTION, so the delete used to fail while an entry pointed at the row."""
    from app.api.routes import cash_registers as cash_routes
    from app.api.routes import media_players as media_routes
    from app.domains.inventory.models import MediaPlayer
    from app.domains.operations.models import CashRegister

    async def _noop():
        return None

    monkeypatch.setattr(cash_routes, "_invalidate_cache", _noop)
    monkeypatch.setattr(media_routes, "_invalidate_cache", _noop)
    if kind == "cash_register":
        row = CashRegister(kkm_number="1", hostname="VNA-KKM-999")
        link = "cash_register_id"
    else:
        row = MediaPlayer(device_type="nettop", name="n", model="m", ip_address="10.0.0.9", hostname="VNA-MUZ-999")
        link = "media_player_id"
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    device = RemoteAccessDevice(hostname="host-999", managed=True, **{link: row.id})
    db_session.add(device)
    db_session.commit()
    device_id = device.id

    response = client.delete(url.format(id=row.id), headers=_auth(admin_token))

    assert response.status_code == 200
    db_session.expire_all()
    kept = db_session.get(RemoteAccessDevice, device_id)
    assert kept is not None and getattr(kept, link) is None and kept.managed is False
