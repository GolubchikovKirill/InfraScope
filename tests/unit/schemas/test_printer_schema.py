import pytest
from pydantic import ValidationError

from app.schemas import PrinterCreate


def test_printer_create_requires_ip_for_ip_connection():
    with pytest.raises(ValidationError):
        PrinterCreate(
            printer_type="laser",
            connection_type="ip",
            store_name="Store",
            model="HP",
            ip_address=None,
        )


def test_printer_create_allows_usb_without_ip():
    model = PrinterCreate(
        printer_type="label",
        connection_type="usb",
        store_name="Store",
        model="Zebra",
        host_pc="POS-01",
    )
    assert model.connection_type == "usb"
    assert model.ip_address is None
