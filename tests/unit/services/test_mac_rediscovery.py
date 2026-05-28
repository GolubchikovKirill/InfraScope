import pytest

from app.services.mac_rediscovery import MacRediscoveryTarget, normalize_mac, resolve_devices_by_mac


def test_normalize_mac_accepts_common_formats() -> None:
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aabb.ccdd.eeff") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_rejects_invalid_values() -> None:
    assert normalize_mac(None) is None
    assert normalize_mac("not-a-mac") is None
    assert normalize_mac("aa:bb:cc") is None


@pytest.mark.asyncio
async def test_resolve_devices_by_mac_normalizes_targets(monkeypatch) -> None:
    async def _fake_find_devices_by_macs(macs: list[str], subnets: list[str] | None = None) -> dict[str, str]:
        assert macs == ["aa:bb:cc:dd:ee:ff"]
        assert subnets == ["10.10.98.0/24"]
        return {"AA-BB-CC-DD-EE-FF": "10.10.98.22"}

    monkeypatch.setattr("app.services.mac_rediscovery.find_devices_by_macs", _fake_find_devices_by_macs)
    matches = await resolve_devices_by_mac(
        [
            MacRediscoveryTarget(
                device_kind="printer",
                entity_id="p1",
                name="Store 1",
                current_ip="10.10.98.20",
                mac_address="aabb.ccdd.eeff",
            )
        ],
        subnets=["10.10.98.0/24"],
    )

    assert len(matches) == 1
    assert matches[0].new_ip == "10.10.98.22"
    assert matches[0].moved is True
