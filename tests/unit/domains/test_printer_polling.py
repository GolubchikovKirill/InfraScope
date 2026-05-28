from __future__ import annotations

from app.domains.inventory.models import Printer
from app.domains.inventory.printer_polling import poll_printer_batch, verify_printer_mac


def test_verify_printer_mac_records_first_seen_mac() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.10",
    )

    status = verify_printer_mac(printer, "aa:bb:cc:dd:ee:ff")

    assert status == "verified"
    assert printer.mac_address == "aa:bb:cc:dd:ee:ff"


def test_verify_printer_mac_detects_mismatch() -> None:
    printer = Printer(
        printer_type="laser",
        connection_type="ip",
        store_name="Store A",
        model="HP",
        ip_address="10.10.10.10",
        mac_address="aa:bb:cc:dd:ee:ff",
    )

    status = verify_printer_mac(printer, "11:22:33:44:55:66")

    assert status == "mismatch"
    assert printer.mac_address == "aa:bb:cc:dd:ee:ff"


def test_poll_printer_batch_preserves_result_for_each_ip(monkeypatch) -> None:
    printers = [
        Printer(
            printer_type="label",
            connection_type="ip",
            store_name="Label A",
            model="Zebra",
            ip_address="10.10.10.20",
        ),
        Printer(
            printer_type="label",
            connection_type="ip",
            store_name="Label B",
            model="Zebra",
            ip_address="10.10.10.21",
        ),
    ]

    def fake_poll_one(printer: Printer):
        return printer.ip_address, {"is_online": printer.ip_address.endswith(".20")}, None

    monkeypatch.setattr("app.domains.inventory.printer_polling.poll_one_printer", fake_poll_one)

    result = poll_printer_batch(printers)

    assert result == {
        "10.10.10.20": ({"is_online": True}, None),
        "10.10.10.21": ({"is_online": False}, None),
    }
