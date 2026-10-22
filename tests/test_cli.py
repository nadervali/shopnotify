from pathlib import Path

from shopnotify.delivery_log import DeliveryLog
from shopnotify.notifier import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_cli_dry_run_over_bundled_example(tmp_path):
    db = tmp_path / "deliveries.db"
    code = main(["send",
                 "--csv", str(EXAMPLES / "customers.csv"),
                 "--template", str(EXAMPLES / "templates" / "order_ready.txt"),
                 "--db", str(db), "--dry-run", "--country-code", "98"])
    assert code == 0
    with DeliveryLog(db) as log:
        counts = log.summary()
    # 7 rows: Sara x2 (one is a duplicate), Omid, Lena, Karl (no amount),
    # Neda, Mina -> 5 rendered, 2 skipped.
    assert counts == {"dry_run": 5, "skipped": 2}


def test_cli_report_prints_counts_and_exports(tmp_path, capsys):
    import csv

    db = tmp_path / "deliveries.db"
    main(["send",
          "--csv", str(EXAMPLES / "customers.csv"),
          "--template", str(EXAMPLES / "templates" / "order_ready.txt"),
          "--db", str(db), "--dry-run"])
    out_csv = tmp_path / "export.csv"
    assert main(["report", "--db", str(db),
                 "--csv-out", str(out_csv)]) == 0
    printed = capsys.readouterr().out
    assert "7 deliveries" in printed
    with open(out_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 7  # multi-line messages stay quoted in one field
