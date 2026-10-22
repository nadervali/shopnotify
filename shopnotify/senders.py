"""Message senders: one interface, one implementation per channel.

Both senders talk to the provider over a small ``transport`` callable
— ``transport(url, headers, payload) -> (http_status, json_body)`` —
so tests can stub the HTTP layer and the whole suite runs offline.
The default transport is plain ``urllib``; there are no third-party
dependencies.

Error mapping is shared: HTTP 429 raises ``RateLimitError`` (carrying
the provider's retry-after hint when it sends one), 5xx raises
``TransientError``, and any other failure raises ``SendError``, which
the retry wrapper deliberately does not retry.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Callable

from .retry import RateLimitError, TransientError

logger = logging.getLogger(__name__)

Transport = Callable[[str, dict, dict], tuple[int, dict]]


class SendError(Exception):
    """A delivery failure that retrying will not fix (bad address, ...)."""


def urllib_transport(url: str, headers: dict, payload: dict) -> tuple[int, dict]:
    """POST ``payload`` as JSON; return (status, parsed body).

    HTTP error statuses are returned, not raised, so the caller can
    map them; only transport-level failures raise (as ConnectionError,
    which the retry wrapper treats as retryable).
    """
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, _parse(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _parse(exc.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ConnectionError(str(exc)) from exc


def _parse(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": raw.decode("utf-8", errors="replace")}


class Sender:
    """Interface every channel implements."""

    channel: str = ""

    def send(self, destination: str, text: str) -> str:
        """Deliver ``text``; return the provider's message id."""
        raise NotImplementedError


class TelegramSender(Sender):
    """Telegram Bot API ``sendMessage``.

    ``destination`` is a chat id. A customer only has one once they
    have opened the shop's bot and pressed Start — the id is what the
    customers CSV carries in ``telegram_chat_id``.
    """

    channel = "telegram"

    def __init__(self, bot_token: str,
                 transport: Transport = urllib_transport):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._transport = transport

    def send(self, destination: str, text: str) -> str:
        status, body = self._transport(
            self._url, {}, {"chat_id": destination, "text": text})
        if status == 200 and body.get("ok"):
            return str(body.get("result", {}).get("message_id", ""))
        description = body.get("description") or f"HTTP {status}"
        if status == 429:
            retry_after = body.get("parameters", {}).get("retry_after")
            raise RateLimitError(
                description,
                retry_after=float(retry_after) if retry_after else None)
        if status >= 500:
            raise TransientError(description)
        raise SendError(description)


class WhatsAppSender(Sender):
    """WhatsApp Cloud API (Meta Graph API) text messages.

    ``destination`` is the customer's phone number; the API wants it
    as digits only (the international ``wa_id`` form), so a leading
    ``+`` is stripped. Note the platform rule this client cannot code
    around: outside a 24-hour customer-service window WhatsApp only
    allows pre-approved template messages, so order alerts are best
    sent in reply to, or soon after, a customer interaction.
    """

    channel = "whatsapp"

    def __init__(self, access_token: str, phone_number_id: str,
                 transport: Transport = urllib_transport,
                 api_version: str = "v21.0"):
        self._url = (f"https://graph.facebook.com/{api_version}/"
                     f"{phone_number_id}/messages")
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._transport = transport

    def send(self, destination: str, text: str) -> str:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destination.lstrip("+"),
            "type": "text",
            "text": {"body": text},
        }
        status, body = self._transport(self._url, self._headers, payload)
        messages = body.get("messages") or []
        if 200 <= status < 300 and messages:
            return str(messages[0].get("id", ""))
        error = body.get("error") or {}
        message = error.get("message") or f"HTTP {status}"
        if status == 429 or error.get("code") == 130429:
            raise RateLimitError(message)
        if status >= 500:
            raise TransientError(message)
        raise SendError(message)
