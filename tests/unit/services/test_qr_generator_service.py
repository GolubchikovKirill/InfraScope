import io
import zipfile

import pytest

from app.services import qr_generator
from app.services.qr_generator import QRGeneratorParams, generate_qr_docs_zip


def test_safe_db_name_rejects_unsupported_characters():
    with pytest.raises(ValueError):
        qr_generator._safe_db_name("CashDB51]; DROP TABLE users;")


def test_generate_qr_docs_zip_skips_empty_datasets_and_builds_both_databases(monkeypatch):
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_SERVER", "free-sql")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_SERVER", "paid-sql")

    def _fake_query_rows(*, server, database, sql_login, sql_password, airport_code, surnames):
        calls.append((server, database))
        if server == "free-sql":
            return [{"LOGIN": "4007001", "NAME": "Иванов Иван", "NameExt": "QR-DATA-1"}]
        return []

    monkeypatch.setattr(qr_generator, "_query_rows", _fake_query_rows)
    monkeypatch.setattr(
        qr_generator,
        "_build_word_from_nameext",
        lambda rows, **kwargs: ("cashiers.docx", f"nameext:{len(rows)}".encode()),
    )
    monkeypatch.setattr(
        qr_generator,
        "_build_word_from_login",
        lambda rows, **kwargs: ("sip.docx", f"login:{len(rows)}".encode()),
    )

    payload = generate_qr_docs_zip(
        QRGeneratorParams(
            server="DC1-SRV-KC01.regstaer.local",
            database="CashDB51",
            sql_login="sa",
            sql_password="secret",
            airport_code="4007",
            surnames=None,
            add_login=False,
            both_databases=True,
        )
    )

    assert calls == [
        ("free-sql", "CashDB51"),
        ("paid-sql", "CashDB51"),
    ]

    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert sorted(archive.namelist()) == ["cashiers.docx", "errors.txt", "sip.docx"]
    assert archive.read("cashiers.docx") == b"nameext:1"
    assert archive.read("sip.docx") == b"login:1"
    assert "Duty Paid" in archive.read("errors.txt").decode()


def test_generate_qr_docs_zip_uses_channel_specific_databases(monkeypatch):
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_SERVER", "free-sql")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_DATABASE", "FreeCash")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_SERVER", "paid-sql")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_DATABASE", "PaidCash")

    def _fake_query_rows(*, server, database, sql_login, sql_password, airport_code, surnames):
        calls.append((server, database))
        return [{"LOGIN": "4007001", "NAME": "Иванов Иван", "NameExt": "QR-DATA-1"}]

    monkeypatch.setattr(qr_generator, "_query_rows", _fake_query_rows)
    monkeypatch.setattr(qr_generator, "_build_word_from_nameext", lambda rows, **kwargs: (f"{kwargs['db_name']}-n.docx", b"n"))
    monkeypatch.setattr(qr_generator, "_build_word_from_login", lambda rows, **kwargs: (f"{kwargs['db_name']}-l.docx", b"l"))

    generate_qr_docs_zip(
        QRGeneratorParams(
            server="unused",
            database="FallbackCash",
            sql_login="sa",
            sql_password="secret",
            airport_code="4007",
            surnames=None,
            add_login=False,
            both_databases=True,
        )
    )

    assert calls == [("free-sql", "FreeCash"), ("paid-sql", "PaidCash")]


def test_generate_qr_docs_zip_keeps_partial_export_with_error_report(monkeypatch):
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_SERVER", "free-sql")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_SERVER", "paid-sql")

    def _fake_query_rows(*, server, database, sql_login, sql_password, airport_code, surnames):
        if server == "paid-sql":
            raise RuntimeError("login failed")
        return [{"LOGIN": "4007001", "NAME": "Иванов Иван", "NameExt": "QR-DATA-1"}]

    monkeypatch.setattr(qr_generator, "_query_rows", _fake_query_rows)
    monkeypatch.setattr(qr_generator, "_build_word_from_nameext", lambda rows, **kwargs: ("cashiers.docx", b"nameext"))
    monkeypatch.setattr(qr_generator, "_build_word_from_login", lambda rows, **kwargs: ("sip.docx", b"login"))

    payload = generate_qr_docs_zip(
        QRGeneratorParams(
            server="DC1-SRV-KC01.regstaer.local",
            database="CashDB51",
            sql_login="sa",
            sql_password="secret",
            airport_code="4007",
            surnames=None,
            add_login=False,
            both_databases=True,
        )
    )

    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert sorted(archive.namelist()) == ["cashiers.docx", "errors.txt", "sip.docx"]
    assert "Duty Paid" in archive.read("errors.txt").decode()
    assert "login failed" in archive.read("errors.txt").decode()


def test_generate_qr_docs_zip_raises_when_no_rows_found(monkeypatch):
    monkeypatch.setattr(qr_generator, "_query_rows", lambda **kwargs: [])

    with pytest.raises(ValueError, match="Нет данных"):
        generate_qr_docs_zip(
            QRGeneratorParams(
                server="DC1-SRV-KC01.regstaer.local",
                database="CashDB51",
                sql_login="sa",
                sql_password="secret",
                airport_code="4007",
                surnames=None,
                add_login=False,
                both_databases=False,
            )
        )
