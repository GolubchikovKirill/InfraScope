from app.services.iconbit import _parse_free_space, _parse_now_html, _parse_status_xml


def test_parse_status_xml_extracts_state_and_track():
    xml = "<root><state>playing</state><file>song.mp3</file><position>12</position><duration>180</duration></root>"
    parsed = _parse_status_xml(xml)
    assert parsed is not None
    assert parsed["state"] == "playing"
    assert parsed["file"] == "song.mp3"
    assert parsed["position"] == 12
    assert parsed["duration"] == 180


def test_parse_now_html_extracts_track_name():
    html = "<html><body><b>playlist/track01.mp3</b></body></html>"
    assert _parse_now_html(html) == "playlist/track01.mp3"


def test_parse_free_space_supports_russian_label():
    html = "Доступно 12.3GB / 29.7GB"
    assert _parse_free_space(html) == "12.3GB / 29.7GB"
