"""Notification orchestration and command-line entry point.

Flow per customer row::

    load -> dedupe -> render -> [dry-run | send with retries] -> log

Nothing is silently dropped: duplicates, rows with no usable address
and template errors are written to the delivery log as ``skipped``
with the reason, and messages that still fail after the retries are
``failed`` with the provider's error attached. Sends are paced by a
rate limiter so a long customer list does not trip the providers'
per-second limits.
"""

import argparse
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Settings
from .customers import dedupe_customers, load_customers
from .delivery_log import DeliveryLog
from .models import Customer, DeliveryRecord
from .retry import retry_call
from .senders import Sender, TelegramSender, WhatsAppSender
from .templating import MissingValueError, render

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforces a minimum gap between sends.

    ``clock`` and ``sleep`` are injectable so tests can observe the
    pacing without actually waiting.
    """

    def __init__(self, interval_seconds: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None and self.interval > 0:
            remaining = self.interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


@dataclass
class RunSummary:
    run_id: str
    total: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: int = 0

    def line(self) -> str:
        return (f"run {self.run_id}: {self.total} row(s): sent={self.sent}, "
                f"failed={self.failed}, skipped={self.skipped}, "
                f"dry_run={self.dry_run}")


class Notifier:
    def __init__(self, senders: dict[str, Sender], log: DeliveryLog, *,
                 rate_limiter: RateLimiter | None = None,
                 max_attempts: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        self._senders = senders
        self._log = log
        self._limiter = rate_limiter or RateLimiter(0)
        self._max_attempts = max_attempts
        self._sleep = sleep

    def run(self, customers: list[Customer], template: str, *,
            dry_run: bool = False, run_id: str | None = None) -> RunSummary:
        run_id = run_id or uuid.uuid4().hex[:12]
        summary = RunSummary(run_id=run_id, total=len(customers))

        unique, duplicates = dedupe_customers(customers)
        for duplicate in duplicates:
            self._record(run_id, duplicate, "skipped",
                         error="duplicate recipient in this run")
            summary.skipped += 1

        for customer in unique:
            status = self._process(run_id, customer, template, dry_run)
            setattr(summary, status, getattr(summary, status) + 1)
        return summary

    def _process(self, run_id: str, customer: Customer, template: str,
                 dry_run: bool) -> str:
        if not customer.destination:
            missing = ("telegram chat id" if customer.channel == "telegram"
                       else "phone number")
            self._record(run_id, customer, "skipped",
                         error=f"no {missing} for channel "
                               f"'{customer.channel}'")
            return "skipped"

        try:
            text = render(template, _merge_values(customer))
        except MissingValueError as exc:
            self._record(run_id, customer, "skipped", error=str(exc))
            return "skipped"

        if dry_run:
            self._record(run_id, customer, "dry_run", message=text)
            return "dry_run"

        sender = self._senders.get(customer.channel)
        if sender is None:
            self._record(run_id, customer, "skipped", message=text,
                         error=f"no sender configured for channel "
                               f"'{customer.channel}'")
            return "skipped"

        self._limiter.wait()
        attempts = {"n": 0}

        def attempt() -> str:
            attempts["n"] += 1
            return sender.send(customer.destination, text)

        try:
            retry_call(attempt, max_attempts=self._max_attempts,
                       sleep=self._sleep)
        except Exception as exc:  # retries exhausted or fatal error
            logger.warning("delivery to %s failed: %s",
                           customer.destination, exc)
            self._record(run_id, customer, "failed", message=text,
                         attempts=attempts["n"], error=str(exc))
            return "failed"
        self._record(run_id, customer, "sent", message=text,
                     attempts=attempts["n"])
        return "sent"

    def _record(self, run_id: str, customer: Customer, status: str, *,
                message: str = "", attempts: int = 0,
                error: str = "") -> None:
        self._log.record(run_id, DeliveryRecord(
            channel=customer.channel,
            recipient=customer.destination,
            customer_name=customer.name,
            order_id=customer.order_id,
            status=status, attempts=attempts, error=error,
            message=message))


def _merge_values(customer: Customer) -> dict:
    """Template values for one customer.

    Every CSV column is available; the normalised attributes win over
    the raw cells, so ``{{phone}}`` renders ``+98912...``, not the
    spaced-out value from the spreadsheet.
    """
    return {
        **customer.fields,
        "name": customer.name,
        "phone": customer.phone,
        "telegram_chat_id": customer.telegram_chat_id,
        "channel": customer.channel,
        "order_id": customer.order_id,
    }


def build_senders(settings: Settings) -> dict[str, Sender]:
    senders: dict[str, Sender] = {}
    if settings.telegram_bot_token:
        senders["telegram"] = TelegramSender(settings.telegram_bot_token)
    if settings.whatsapp_token and settings.whatsapp_phone_number_id:
        senders["whatsapp"] = WhatsAppSender(
            settings.whatsapp_token, settings.whatsapp_phone_number_id,
            api_version=settings.whatsapp_api_version)
    return senders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shopnotify",
        description="Send personalised order alerts from a customer CSV.")
    sub = parser.add_subparsers(dest="command", required=True)

    send = sub.add_parser("send", help="render and send a batch")
    send.add_argument("--csv", required=True, help="customers CSV file")
    send.add_argument("--template", required=True,
                      help="message template file ({{merge tags}})")
    send.add_argument("--db", help="delivery log database "
                                   "(default: LOG_DB from settings)")
    send.add_argument("--dry-run", action="store_true",
                      help="render and log only; contact nobody")
    send.add_argument("--interval", type=float,
                      help="seconds between sends (default: settings)")
    send.add_argument("--max-attempts", type=int,
                      help="send attempts per message (default: settings)")
    send.add_argument("--country-code",
                      help="country code for numbers without one, e.g. 98")

    report = sub.add_parser("report", help="summarise the delivery log")
    report.add_argument("--db", help="delivery log database "
                                     "(default: LOG_DB from settings)")
    report.add_argument("--csv-out", help="also export records to this CSV")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    if args.command == "report":
        with DeliveryLog(args.db or settings.log_db) as log:
            counts = log.summary()
            total = sum(counts.values())
            print(f"{total} deliveries: "
                  + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            if args.csv_out:
                log.export_csv(args.csv_out)
        return 0

    customers = load_customers(
        args.csv,
        default_country_code=args.country_code
        or settings.default_country_code)
    template = Path(args.template).read_text(encoding="utf-8")
    senders = build_senders(settings)
    if not args.dry_run and not senders:
        parser.error("no sender configured: set TELEGRAM_BOT_TOKEN or "
                     "WHATSAPP_TOKEN + WHATSAPP_PHONE_NUMBER_ID in .env, "
                     "or pass --dry-run")

    limiter = RateLimiter(
        settings.send_interval_seconds if args.interval is None
        else args.interval)
    with DeliveryLog(args.db or settings.log_db) as log:
        notifier = Notifier(
            senders, log, rate_limiter=limiter,
            max_attempts=settings.max_attempts if args.max_attempts is None
            else args.max_attempts)
        summary = notifier.run(customers, template, dry_run=args.dry_run)
        for row in log.records(summary.run_id):
            if row["status"] in ("failed", "skipped"):
                print(f"{row['status']}: {row['customer_name'] or '-'} "
                      f"({row['channel']} {row['recipient'] or '-'}): "
                      f"{row['error']}")
    print(summary.line())
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
