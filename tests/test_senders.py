import pytest

from shopnotify.retry import RateLimitError, TransientError
from shopnotify.senders import SendError, TelegramSender, WhatsAppSender


class StubTransport:
    """Records calls and replays scripted (status, body) responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, headers, payload):
        self.calls.append((url, headers, payload))
        return self.responses.pop(0)


def test_telegram_sends_chat_id_and_text_and_returns_message_id():
    transport = StubTransport(
        (200, {"ok": True, "result": {"message_id": 77}}))
    sender = TelegramSender("TOKEN", transport=transport)
    assert sender.send("512345678", "hello") == "77"
    url, headers, payload = transport.calls[0]
    assert url == "https://api.telegram.org/botTOKEN/sendMessage"
    assert payload == {"chat_id": "512345678", "text": "hello"}


def test_telegram_rate_limit_carries_retry_after():
    transport = StubTransport(
        (429, {"ok": False, "description": "Too Many Requests",
               "parameters": {"retry_after": 3}}))
    sender = TelegramSender("TOKEN", transport=transport)
    with pytest.raises(RateLimitError) as excinfo:
        sender.send("1", "hi")
    assert excinfo.value.retry_after == 3.0


def test_telegram_server_error_is_transient():
    transport = StubTransport((502, {"description": "Bad Gateway"}))
    sender = TelegramSender("TOKEN", transport=transport)
    with pytest.raises(TransientError):
        sender.send("1", "hi")


def test_telegram_client_error_is_fatal_with_provider_message():
    transport = StubTransport(
        (400, {"ok": False, "description": "Bad Request: chat not found"}))
    sender = TelegramSender("TOKEN", transport=transport)
    with pytest.raises(SendError, match="chat not found"):
        sender.send("1", "hi")


def test_whatsapp_payload_shape_and_auth_header():
    transport = StubTransport(
        (200, {"messages": [{"id": "wamid.123"}]}))
    sender = WhatsAppSender("SECRET", "10987654321", transport=transport)
    assert sender.send("+989123456789", "hello") == "wamid.123"
    url, headers, payload = transport.calls[0]
    assert url == ("https://graph.facebook.com/v21.0/"
                   "10987654321/messages")
    assert headers["Authorization"] == "Bearer SECRET"
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "989123456789"  # digits only, no leading +
    assert payload["type"] == "text"
    assert payload["text"] == {"body": "hello"}


def test_whatsapp_error_uses_provider_message():
    transport = StubTransport(
        (400, {"error": {"message": "Recipient phone number not in "
                                   "allowed list", "code": 131030}}))
    sender = WhatsAppSender("SECRET", "1", transport=transport)
    with pytest.raises(SendError, match="not in allowed list"):
        sender.send("+100", "hi")


def test_whatsapp_rate_limit_by_error_code():
    transport = StubTransport(
        (400, {"error": {"message": "Rate limit hit", "code": 130429}}))
    sender = WhatsAppSender("SECRET", "1", transport=transport)
    with pytest.raises(RateLimitError):
        sender.send("+100", "hi")


def test_whatsapp_server_error_is_transient():
    transport = StubTransport((503, {"error": {"message": "Unavailable"}}))
    sender = WhatsAppSender("SECRET", "1", transport=transport)
    with pytest.raises(TransientError):
        sender.send("+100", "hi")
