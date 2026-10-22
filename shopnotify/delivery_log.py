"""SQLite delivery log.

Every row the notifier processes leaves exactly one record — sent,
failed, skipped (duplicate, undeliverable or unrenderable) or dry_run
— so a run can be audited after the fact: "did Sara get her order
alert?" is a query, not a guess. Records can also be exported to CSV
for the shop's own bookkeeping.
"""

import csv
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import DeliveryRecord

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    customer_name TEXT NOT NULL DEFAULT '',
    order_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT ''
)
"""

_COLUMNS = ("timestamp", "channel", "recipient", "customer_name",
            "order_id", "status", "attempts", "error", "message")


class DeliveryLog:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DeliveryLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def record(self, run_id: str, record: DeliveryRecord) -> None:
        timestamp = record.timestamp or datetime.now(
            timezone.utc).isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO deliveries (run_id, timestamp, channel,"
            " recipient, customer_name, order_id, status, attempts,"
            " error, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, timestamp, record.channel, record.recipient,
             record.customer_name, record.order_id, record.status,
             record.attempts, record.error, record.message))
        self._conn.commit()

    def records(self, run_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM deliveries"
        params: tuple = ()
        if run_id is not None:
            query += " WHERE run_id = ?"
            params = (run_id,)
        rows = self._conn.execute(query + " ORDER BY id", params)
        return [dict(row) for row in rows]

    def summary(self, run_id: str | None = None) -> dict[str, int]:
        """Delivery counts by status, e.g. ``{"sent": 5, "skipped": 2}``."""
        counts: dict[str, int] = {}
        for row in self.records(run_id):
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts

    def export_csv(self, path: str | Path,
                   run_id: str | None = None) -> int:
        rows = self.records(run_id)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["run_id", *_COLUMNS])
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row[key]
                                 for key in ("run_id", *_COLUMNS)})
        logger.info("exported %d delivery record(s) to %s", len(rows), path)
        return len(rows)
