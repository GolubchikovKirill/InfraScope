"""Read-only aggregate report; run inside the backend container."""

import json
from datetime import UTC, datetime

from sqlalchemy import inspect, text

from app.core.db import engine

report = {}
with engine.connect() as connection:
    schema = inspect(connection)
    for table in schema.get_table_names():
        columns = {column["name"] for column in schema.get_columns(table)}
        if not {"last_polled_at", "is_online"} <= columns:
            continue
        # Table names come from the DB inspector and are quoted as identifiers.
        name = connection.dialect.identifier_preparer.quote(table)
        rows = connection.execute(text(f"SELECT is_online, last_polled_at FROM {name}"))
        counts = {"total": 0, "online": 0, "offline": 0, "unknown": 0, "stale_30m": 0}
        for online, checked_at in rows:
            counts["total"] += 1
            counts["unknown" if online is None else "online" if online else "offline"] += 1
            if checked_at is None or (datetime.now(UTC) - checked_at.replace(tzinfo=UTC)).total_seconds() > 1800:
                counts["stale_30m"] += 1
        report[table] = counts
print(json.dumps(report, indent=2))
