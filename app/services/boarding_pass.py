from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass

import qrcode
from PIL import Image, ImageDraw

from app.domains.integrations.schemas import BoardingPassRequest


@dataclass(frozen=True)
class GeneratedBoardingPassFile:
    filename: str
    content_type: str
    payload: str
    content: bytes


class BoardingPassPayloadBuilder:
    def _normalize_token(self, value: str | None, *, field_name: str, upper: bool = False) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError(f"{field_name} is required")
        return normalized.upper() if upper else normalized

    def _resolve_day_in_year(self, payload: BoardingPassRequest) -> str:
        if payload.day_in_year:
            day = payload.day_in_year.strip()
            if not day.isdigit() or len(day) > 3:
                raise ValueError("day_in_year must contain up to 3 digits")
            return day.zfill(3)

        if not payload.flight_date:
            raise ValueError("flight_date or day_in_year is required")

        try:
            parsed = dt.date.fromisoformat(payload.flight_date)
        except ValueError as exc:
            raise ValueError("flight_date must use YYYY-MM-DD format") from exc
        return f"{parsed.timetuple().tm_yday:03d}"

    def build_payload(self, payload: BoardingPassRequest) -> str:
        if payload.raw_data:
            return payload.raw_data

        last_name = self._normalize_token(payload.last_name, field_name="last_name", upper=True)
        first_name = self._normalize_token(payload.first_name, field_name="first_name", upper=True)
        booking_ref = self._normalize_token(payload.booking_ref, field_name="booking_ref", upper=True)
        from_code = self._normalize_token(payload.from_code, field_name="from_code", upper=True)
        to_code = self._normalize_token(payload.to_code, field_name="to_code", upper=True)
        flight_operator = self._normalize_token(payload.flight_operator, field_name="flight_operator", upper=True)
        flight_number = self._normalize_token(payload.flight_number, field_name="flight_number", upper=True)
        travel_class = self._normalize_token(payload.travel_class, field_name="travel_class", upper=True)
        seat = self._normalize_token(payload.seat, field_name="seat", upper=True)
        boarding_index = self._normalize_token(payload.boarding_index, field_name="boarding_index", upper=True)
        day_in_year = self._resolve_day_in_year(payload)

        # Compact BCBP-style text payload that is deterministic and easy to validate in tests.
        return (
            f"M1{last_name}/{first_name} "
            f"{booking_ref} "
            f"{from_code}{to_code}"
            f"{flight_operator}{flight_number}"
            f"{day_in_year}"
            f"{travel_class}"
            f"{seat}"
            f"{boarding_index}"
        )


class BoardingPassRenderer:
    def render_png(self, *, barcode_format: str, payload_text: str) -> bytes:
        image = Image.new("RGB", (1200, 500), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 1170, 470), outline="black", width=3)
        draw.text((55, 55), f"BOARDING PASS {barcode_format.upper()}", fill="black")

        # Keep rendering dependency-light and stable: generate a real scannable
        # 2D payload image and embed it into the resulting PNG.
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(payload_text)
        qr.make(fit=True)
        barcode_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        barcode_target_size = 320
        barcode_image = barcode_image.resize((barcode_target_size, barcode_target_size), Image.Resampling.NEAREST)
        image.paste(barcode_image, (70, 105))

        draw.text((430, 140), "Payload:", fill="black")
        draw.text((430, 170), payload_text[:92], fill="black")
        if len(payload_text) > 92:
            draw.text((430, 200), payload_text[92:184], fill="black")
        draw.text((430, 360), "Scan 2D code to retrieve full payload", fill="black")

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


class BoardingPassService:
    def __init__(
        self,
        *,
        payload_builder: BoardingPassPayloadBuilder | None = None,
        renderer: BoardingPassRenderer | None = None,
    ) -> None:
        self._payload_builder = payload_builder or BoardingPassPayloadBuilder()
        self._renderer = renderer or BoardingPassRenderer()

    def generate_file(self, payload: BoardingPassRequest) -> GeneratedBoardingPassFile:
        payload_text = self._payload_builder.build_payload(payload)
        today = dt.date.today().isoformat()
        filename = f"boarding_pass_{payload.format}_{today}.png"
        content = self._renderer.render_png(barcode_format=payload.format, payload_text=payload_text)
        return GeneratedBoardingPassFile(
            filename=filename,
            content_type="image/png",
            payload=payload_text,
            content=content,
        )


_default_service = BoardingPassService()
_default_payload_builder = BoardingPassPayloadBuilder()


def build_boarding_pass_payload(payload: BoardingPassRequest) -> str:
    return _default_payload_builder.build_payload(payload)


def generate_boarding_pass_file(payload: BoardingPassRequest) -> GeneratedBoardingPassFile:
    return _default_service.generate_file(payload)
