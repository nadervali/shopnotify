"""Loading and normalising the customers CSV.

Expected columns (a header row is required)::

    name, phone, telegram_chat_id, channel, order_id, amount

``channel`` is ``telegram`` or ``whatsapp``; when it is blank the row
defaults to WhatsApp if a phone number is present, otherwise Telegram.
Any further columns (``item``, ``eta``, ...) are kept in
``Customer.fields`` so templates can merge them.

Phone numbers are normalised to ``+<digits>``: spaces, dashes and
parentheses are stripped and a leading ``00`` becomes ``+``. A number
with no country code gets ``default_country_code`` prepended (a leading
trunk ``0`` is dropped first), so with country code ``98`` the number
``0912 555 0134`` becomes ``+989125550134``.
"""

import csv
import logging
import re
from pathlib import Path

from .models import Customer

logger = logging.getLogger(__name__)

CHANNELS = ("telegram", "whatsapp")


def normalise_phone(raw: str, default_country_code: str = "") -> str:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif not digits.startswith("+") and default_country_code:
        if digits.startswith("0"):
            digits = digits[1:]
        digits = "+" + default_country_code + digits
    return digits


def load_customers(path: str | Path,
                   default_country_code: str = "") -> list[Customer]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [_to_customer(raw, default_country_code)
                for raw in csv.DictReader(fh)]
    logger.info("loaded %d customer row(s) from %s", len(rows), path)
    return rows


def _to_customer(raw: dict, default_country_code: str) -> Customer:
    clean = {(key or "").strip(): (value or "").strip()
             for key, value in raw.items()}
    channel = clean.get("channel", "").lower()
    if channel not in CHANNELS:
        channel = "whatsapp" if clean.get("phone") else "telegram"
    return Customer(
        name=clean.get("name", ""),
        phone=normalise_phone(clean.get("phone", ""), default_country_code),
        telegram_chat_id=clean.get("telegram_chat_id", ""),
        channel=channel,
        order_id=clean.get("order_id", ""),
        fields=clean,
    )


def dedupe_customers(
        customers: list[Customer]) -> tuple[list[Customer], list[Customer]]:
    """Split into (unique, duplicates) keyed by channel + destination.

    The first occurrence wins; later rows addressed to the same
    destination on the same channel come back as duplicates so the
    caller can log them instead of messaging the customer twice. Rows
    with no destination are never duplicates of each other — they are
    undeliverable, which is a different problem and is reported as such.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Customer] = []
    duplicates: list[Customer] = []
    for customer in customers:
        key = customer.dedupe_key()
        if customer.destination and key in seen:
            duplicates.append(customer)
            continue
        if customer.destination:
            seen.add(key)
        unique.append(customer)
    return unique, duplicates
