from app.services.snmp import _detect_color, _detect_vendor, _is_toner_supply


def test_detect_vendor_from_sysdescr():
    assert _detect_vendor("HP LaserJet Pro M428") == "hp"
    assert _detect_vendor("RICOH MP C3004") == "ricoh"


def test_detect_color_works_for_text_and_suffix():
    assert _detect_color("Black Toner Cartridge") == "black"
    assert _detect_color("TK-5240M") == "magenta"


def test_is_toner_supply_rejects_non_consumables():
    assert _is_toner_supply("Drum unit", 15) is False
    assert _is_toner_supply("Black Toner", 3) is True
