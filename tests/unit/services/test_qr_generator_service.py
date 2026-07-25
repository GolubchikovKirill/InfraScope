import io
import zipfile

import pytest

from app.services import qr_generator
from app.services.qr_generator import QRGeneratorParams, generate_qr_docs_zip


def test_safe_db_name_rejects_unsupported_characters():
    with pytest.raises(ValueError):
        qr_generator._safe_db_name("CashDB51]; DROP TABLE users;")


def test_generate_qr_docs_zip_skips_empty_datasets_and_builds_both_databases(monkeypatch):
    # _qr_database_targets() falls back to real settings.QR_SQL_DUTY_* values
    # when they're set (which they are in this deployment's .env, pointing
    # at real IPs) - pin them to the hostnames this test actually asserts
    # against so it isn't at the mercy of whatever's configured on whatever
    # machine runs the suite.
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_SERVER", "DC1-SRV-KC01.regstaer.local")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_DATABASE", "CashDB51")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_SERVER", "DC1-SRV-KC02.regstaer.local")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_DATABASE", "CashDB51")

    calls: list[tuple[str, str]] = []

    def _fake_query_rows(*, server, database, sql_login, sql_password, airport_code, surnames):
        calls.append((server, database))
        if "KC01" in server:
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
        ("DC1-SRV-KC01.regstaer.local", "CashDB51"),
        ("DC1-SRV-KC02.regstaer.local", "CashDB51"),
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
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_SERVER", "DC1-SRV-KC01.regstaer.local")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_FREE_DATABASE", "CashDB51")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_SERVER", "DC1-SRV-KC02.regstaer.local")
    monkeypatch.setattr(qr_generator.settings, "QR_SQL_DUTY_PAID_DATABASE", "CashDB51")

    def _fake_query_rows(*, server, database, sql_login, sql_password, airport_code, surnames):
        if "KC02" in server:
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


def test_generate_qr_docs_zip_single_database_uses_explicit_label(monkeypatch):
    # Regression test: the label used to be guessed from whether "KC01"
    # appeared in the server string, which broke once real servers were
    # identified by IP address - duty_free requests came out labeled
    # "Duty Paid" since IPs never contain "KC01".
    monkeypatch.setattr(qr_generator, "_query_rows", lambda **kwargs: [{"LOGIN": "4007001", "NAME": "Иванов Иван", "NameExt": "QR-DATA-1"}])
    monkeypatch.setattr(qr_generator, "_build_word_from_nameext", lambda rows, **kwargs: (f"cashiers-{kwargs['db_name']}.docx", b"n"))
    monkeypatch.setattr(qr_generator, "_build_word_from_login", lambda rows, **kwargs: (f"sip-{kwargs['db_name']}.docx", b"l"))

    payload = generate_qr_docs_zip(
        QRGeneratorParams(
            server="10.10.94.228",
            database="CashDB51",
            sql_login="sa",
            sql_password="secret",
            airport_code="4007",
            surnames=None,
            add_login=False,
            both_databases=False,
            label="Duty Free",
        )
    )

    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert sorted(archive.namelist()) == ["cashiers-Duty Free.docx", "sip-Duty Free.docx"]


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
