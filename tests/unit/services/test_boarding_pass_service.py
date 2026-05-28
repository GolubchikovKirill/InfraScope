import pytest

from app.schemas import BoardingPassRequest
from app.services.boarding_pass import build_boarding_pass_payload, generate_boarding_pass_file


def test_build_boarding_pass_payload_from_fields():
    payload = build_boarding_pass_payload(
        BoardingPassRequest(
            format="aztec",
            first_name=" ivan ",
            last_name=" ivanov ",
            booking_ref=" ebr123 ",
            from_code=" svo ",
            to_code=" led ",
            flight_operator=" su ",
            flight_number=" 1234 ",
            flight_date="2026-02-01",
            travel_class=" y ",
            seat=" 12a ",
            boarding_index=" 7 ",
        )
    )

    assert payload == "M1IVANOV/IVAN EBR123 SVOLEDSU1234032Y12A7"


def test_build_boarding_pass_payload_uses_raw_data_bypass():
    payload = build_boarding_pass_payload(
        BoardingPassRequest(
            format="pdf417",
            raw_data=" M1RAW-PAYLOAD ",
        )
    )

    assert payload == "M1RAW-PAYLOAD"


def test_build_boarding_pass_payload_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="last_name is required"):
        build_boarding_pass_payload(
            BoardingPassRequest(
                format="aztec",
                first_name="Ivan",
                booking_ref="EBR123",
            )
        )


def test_build_boarding_pass_payload_rejects_invalid_day_in_year():
    with pytest.raises(ValueError, match="day_in_year must contain up to 3 digits"):
        build_boarding_pass_payload(
            BoardingPassRequest(
                format="aztec",
                first_name="Ivan",
                last_name="Ivanov",
                booking_ref="EBR123",
                from_code="SVO",
                to_code="LED",
                flight_operator="SU",
                flight_number="1234",
                day_in_year="36A",
                travel_class="Y",
                seat="12A",
                boarding_index="7",
            )
        )


def test_build_boarding_pass_payload_rejects_invalid_flight_date_format():
    with pytest.raises(ValueError, match="flight_date must use YYYY-MM-DD format"):
        build_boarding_pass_payload(
            BoardingPassRequest(
                format="aztec",
                first_name="Ivan",
                last_name="Ivanov",
                booking_ref="EBR123",
                from_code="SVO",
                to_code="LED",
                flight_operator="SU",
                flight_number="1234",
                flight_date="01-02-2026",
                travel_class="Y",
                seat="12A",
                boarding_index="7",
            )
        )


def test_generate_boarding_pass_file_returns_png_bytes():
    generated = generate_boarding_pass_file(
        BoardingPassRequest(
            format="pdf417",
            raw_data="M1RAW-PAYLOAD",
        )
    )

    assert generated.content_type == "image/png"
    assert generated.filename.startswith("boarding_pass_pdf417_")
    assert generated.content.startswith(b"\x89PNG\r\n\x1a\n")
