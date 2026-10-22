from shopnotify.delivery_log import DeliveryLog
from shopnotify.models import DeliveryRecord


def make_record(status: str, name: str = "Sara") -> DeliveryRecord:
    return DeliveryRecord(channel="telegram", recipient="111",
                          customer_name=name, order_id="1042",
                          status=status, attempts=1, message="hi")


def test_records_round_trip_with_generated_timestamp(tmp_path):
    with DeliveryLog(tmp_path / "log.db") as log:
        log.record("run1", make_record("sent"))
        rows = log.records("run1")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "sent"
    assert row["recipient"] == "111"
    assert row["timestamp"]  # filled in by the log


def test_summary_counts_by_status_and_filters_by_run(tmp_path):
    with DeliveryLog(tmp_path / "log.db") as log:
        log.record("run1", make_record("sent"))
        log.record("run1", make_record("sent"))
        log.record("run1", make_record("skipped"))
        log.record("run2", make_record("failed"))
        assert log.summary("run1") == {"sent": 2, "skipped": 1}
        assert log.summary() == {"sent": 2, "skipped": 1, "failed": 1}


def test_records_persist_across_connections(tmp_path):
    path = tmp_path / "log.db"
    with DeliveryLog(path) as log:
        log.record("run1", make_record("sent"))
    with DeliveryLog(path) as log:
        assert len(log.records()) == 1


def test_export_csv_writes_header_and_rows(tmp_path):
    db = tmp_path / "log.db"
    out = tmp_path / "export.csv"
    with DeliveryLog(db) as log:
        log.record("run1", make_record("sent"))
        log.record("run1", make_record("failed"))
        assert log.export_csv(out, run_id="run1") == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("run_id,timestamp,channel,recipient")
    assert len(lines) == 3
    assert "failed" in lines[2]
