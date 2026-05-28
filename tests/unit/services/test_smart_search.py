from app.services.smart_search import text_matches_query


def test_text_matches_query_handles_latin_cyrillic_equivalence():
    assert text_matches_query(["VNA-MGR-1201"], "VNA-МGR")
    assert text_matches_query(["VNA-MGR-1201"], "VNA-MGR")
    assert text_matches_query(["VNA-MGR-1201"], "VNA МGR 1201")


def test_text_matches_query_requires_all_terms():
    assert text_matches_query(["A15 KKM-501"], "A15 KKM")
    assert not text_matches_query(["A15 KKM-501"], "A15 KKM X999")


def test_text_matches_query_works_with_multiple_fields():
    values = ["VNK-KKM-2501", "Store A25", "Windows 10"]
    assert text_matches_query(values, "A25 KKM")
    assert text_matches_query(values, "Windows A25")
    assert not text_matches_query(values, "Linux A25")
