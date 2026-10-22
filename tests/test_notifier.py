from shopnotify.delivery_log import DeliveryLog
from shopnotify.models import Customer
from shopnotify.notifier import Notifier, RateLimiter
from shopnotify.retry import TransientError
from shopnotify.senders import SendError

TEMPLATE = "Hi {{name}}, order {{order_id}} ready. Total: {{amount}}."


class FakeSender:
    """Sender with per-destination scripted outcomes."""

    def __init__(self, behaviour: dict | None = None):
        self.calls: list[tuple[str, str]] = []
        self.behaviour = behaviour or {}

    def send(self, destination: str, text: str) -> str:
        self.calls.append((destination, text))
        outcomes = self.behaviour.get(destination)
        if outcomes:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return "msg-1"


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.delays: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += seconds


def make_customer(name="Sara", channel="telegram", destination="111",
                  amount="250000", order_id="1042") -> Customer:
    customer = Customer(
        name=name, channel=channel, order_id=order_id,
        fields={"name": name, "order_id": order_id, "amount": amount,
                "item": "Shoes"})
    if channel == "telegram":
        customer.telegram_chat_id = destination
    else:
        customer.phone = destination
    return customer


def run_notifier(tmp_path, customers, sender=None, **kwargs):
    kwargs.setdefault("sleep", lambda seconds: None)
    senders = {"telegram": sender or FakeSender(),
               "whatsapp": sender or FakeSender()}
    with DeliveryLog(tmp_path / "log.db") as log:
        summary = Notifier(senders, log, **kwargs).run(
            customers, TEMPLATE, run_id="run1")
        rows = log.records("run1")
    return summary, rows


def test_happy_path_sends_and_logs(tmp_path):
    sender = FakeSender()
    summary, rows = run_notifier(
        tmp_path, [make_customer(), make_customer("Omid", "whatsapp", "+100")],
        sender=sender)
    assert (summary.sent, summary.failed, summary.skipped) == (2, 0, 0)
    assert len(sender.calls) == 2
    assert sender.calls[0][1].startswith("Hi Sara, order 1042 ready.")
    assert all(row["status"] == "sent" and row["attempts"] == 1
               for row in rows)


def test_duplicate_recipient_is_skipped_not_messaged_twice(tmp_path):
    sender = FakeSender()
    summary, rows = run_notifier(
        tmp_path, [make_customer(), make_customer()], sender=sender)
    assert len(sender.calls) == 1
    assert summary.sent == 1 and summary.skipped == 1
    skipped = [r for r in rows if r["status"] == "skipped"]
    assert "duplicate" in skipped[0]["error"]


def test_missing_destination_is_skipped(tmp_path):
    sender = FakeSender()
    customer = make_customer(destination="")
    summary, rows = run_notifier(tmp_path, [customer], sender=sender)
    assert sender.calls == []
    assert summary.skipped == 1
    assert "no telegram chat id" in rows[0]["error"]


def test_missing_template_value_is_skipped(tmp_path):
    customer = make_customer(amount="")
    summary, rows = run_notifier(tmp_path, [customer])
    assert summary.skipped == 1
    assert "amount" in rows[0]["error"]


def test_dry_run_renders_and_logs_but_never_sends(tmp_path):
    sender = FakeSender()
    with DeliveryLog(tmp_path / "log.db") as log:
        summary = Notifier({"telegram": sender}, log).run(
            [make_customer()], TEMPLATE, dry_run=True, run_id="run1")
        rows = log.records("run1")
    assert sender.calls == []
    assert summary.dry_run == 1
    assert rows[0]["status"] == "dry_run"
    assert "Sara" in rows[0]["message"]  # rendered text kept for review


def test_transient_failure_is_retried_and_eventually_sent(tmp_path):
    sender = FakeSender({"111": [TransientError("502"), "msg-9"]})
    summary, rows = run_notifier(tmp_path, [make_customer()], sender=sender)
    assert summary.sent == 1
    assert rows[0]["attempts"] == 2


def test_exhausted_retries_are_logged_failed_with_reason(tmp_path):
    sender = FakeSender(
        {"111": [TransientError("down"), TransientError("down")]})
    summary, rows = run_notifier(tmp_path, [make_customer()], sender=sender,
                                 max_attempts=2)
    assert summary.failed == 1
    assert rows[0]["attempts"] == 2
    assert rows[0]["error"] == "down"


def test_fatal_error_fails_without_retry(tmp_path):
    sender = FakeSender({"111": [SendError("chat not found")]})
    summary, rows = run_notifier(tmp_path, [make_customer()], sender=sender)
    assert summary.failed == 1
    assert rows[0]["attempts"] == 1
    assert rows[0]["error"] == "chat not found"


def test_unconfigured_channel_is_skipped_with_reason(tmp_path):
    with DeliveryLog(tmp_path / "log.db") as log:
        summary = Notifier({"telegram": FakeSender()}, log).run(
            [make_customer("Omid", "whatsapp", "+100")], TEMPLATE,
            run_id="run1")
        rows = log.records("run1")
    assert summary.skipped == 1
    assert "no sender configured" in rows[0]["error"]


def test_rate_limiter_paces_sends():
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock.clock, sleep=clock.sleep)
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert clock.delays == [2.0, 2.0]  # first send is immediate


def test_notifier_applies_rate_limiter_between_sends(tmp_path):
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock.clock, sleep=clock.sleep)
    customers = [make_customer(destination=str(n)) for n in (1, 2, 3)]
    run_notifier(tmp_path, customers, rate_limiter=limiter)
    assert clock.delays == [1.0, 1.0]
