from dataclasses import dataclass, field


@dataclass
class Customer:
    """One row of the customers CSV, normalised.

    ``fields`` holds every CSV column under its header name so
    templates can merge any of them (``{{amount}}``, ``{{item}}``, ...).
    The well-known fields are also exposed as attributes, normalised:
    phone is ``+<digits>`` and channel is lowercase.
    """

    name: str = ""
    phone: str = ""
    telegram_chat_id: str = ""
    channel: str = ""  # "telegram" | "whatsapp"
    order_id: str = ""
    fields: dict = field(default_factory=dict)

    @property
    def destination(self) -> str:
        """The address a message on ``channel`` would actually go to."""
        if self.channel == "telegram":
            return self.telegram_chat_id
        return self.phone

    def dedupe_key(self) -> tuple[str, str]:
        return (self.channel, self.destination)


@dataclass
class DeliveryRecord:
    """One processed message: attempted, or deliberately not attempted.

    ``status`` is one of ``sent``, ``failed``, ``skipped`` (duplicate,
    undeliverable or unrenderable — see ``error`` for the reason) or
    ``dry_run`` (rendered and logged, never sent).
    """

    channel: str
    recipient: str  # chat id or phone number the message was addressed to
    status: str
    customer_name: str = ""
    order_id: str = ""
    attempts: int = 0
    error: str = ""
    message: str = ""  # rendered text, kept so a run can be audited
    timestamp: str = ""  # ISO 8601 UTC; filled in by the delivery log
