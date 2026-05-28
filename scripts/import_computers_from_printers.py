from datetime import UTC, datetime

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Computer

ROWS: list[tuple[str, str | None, str, str]] = [
    ("VNA-MGR-04", "A4", "DF", "vna-mgr-04"),
    ("VNA-MGR-102", "A1", "DF", "vna-mgr-102"),
    ("VNA-MGR-1101", "A11", "DF", "vna-mgr-1101"),
    ("VNA-MGR-1201", "A12", "DF", "vna-mgr-1201"),
    ("VNA-MGR-15", None, "DP", "VNA-MGR-15"),
    ("VNA-MGR-1501", None, "DP", "VNA-MGR-1501/1502"),
    ("VNA-MGR-1502", None, "DP", "VNA-MGR-1502"),
    ("VNA-MGR-1503", "A15", "DP", "VNA-MGR-1503"),
    ("VNA-MGR-1504", None, "DP", "VNA-MGR-1504"),
    ("VNA-MGR-1602", "A31", "DP", "VNA-MGR-1602"),
    ("VNA-MGR-19", "A19", "DP", "VNA-MGR-19"),
    ("VNA-MGR-201", "A2", "all", "vna-mgr-201"),
    ("VNA-MGR-202", None, "DF", "vna-mgr-202"),
    ("VNA-MGR-204", None, "DF", "vna-mgr-204"),
    ("VNA-MGR-205", "A2", "DF", "vna-mgr-205"),
    ("VNA-MGR-2102", "A21", "all", "VNA-MGR-2102"),
    ("VNA-MGR-2103", "A21", "DP", "VNA-MGR-2103"),
    ("VNA-MGR-2201", "A22", "DP", "VNA-MGR-2201"),
    ("VNA-MGR-2302", "A23", "DP", "VNA-MGR-2302"),
    ("VNA-MGR-2601", "A26", "DP", "VNA-MGR-2601"),
    ("VNA-MGR-2701", "A27", "DP", "VNA-MGR-2701"),
    ("VNA-MGR-2801", "A28", "DF", "vna-mgr-2801"),
    ("VNA-MGR-2901", "A29", "DP", "VNA-MGR-2901"),
    ("VNA-MGR-3001", "A30", "DF", "vna-mgr-3001"),
    ("VNA-MGR-301", "A3", "DF", "vna-mgr-301"),
    ("VNA-MGR-501", "A5", "DF", "vna-mgr-501"),
    ("VNA-MGR-601", "A6", "DF", "vna-mgr-601"),
    ("VNA-MGR-801", "A8", "DF", "vna-mgr-801"),
    ("VNA-MGR-901", "A9", "DF", "VNA-MGR-901"),
    ("VNK-MGR-D1", None, "other", "VNK-MGR-D1"),
]


def main() -> None:
    created = 0
    updated = 0
    with Session(engine) as session:
        for hostname, location, sheet, raw in ROWS:
            current = session.exec(select(Computer).where(Computer.hostname == hostname)).first()
            comment = f"Импорт PRINTERS ({sheet}): {raw}"
            if current:
                changed = False
                if location and current.location != location:
                    current.location = location
                    changed = True
                if current.comment != comment:
                    current.comment = comment
                    changed = True
                if changed:
                    current.updated_at = datetime.now(UTC)
                    session.add(current)
                    updated += 1
                continue

            session.add(
                Computer(
                    hostname=hostname,
                    location=location,
                    comment=comment,
                )
            )
            created += 1

        session.commit()

    print({"created": created, "updated": updated, "total_input": len(ROWS)})


if __name__ == "__main__":
    main()
