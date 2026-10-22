"""Settings, read from the environment and a local ``.env`` if present.

Only the standard library is used: the ``.env`` parser understands
plain ``KEY=VALUE`` lines (and ``#`` comments), which is all
``.env.example`` needs. Real environment variables win over the file.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    telegram_bot_token: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    default_country_code: str = ""
    send_interval_seconds: float = 1.0
    max_attempts: int = 3
    log_db: str = "deliveries.db"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env",
                 environ: dict | None = None) -> "Settings":
        values = _read_env_file(env_file)
        values.update(os.environ if environ is None else environ)
        return cls(
            telegram_bot_token=values.get("TELEGRAM_BOT_TOKEN", ""),
            whatsapp_token=values.get("WHATSAPP_TOKEN", ""),
            whatsapp_phone_number_id=values.get(
                "WHATSAPP_PHONE_NUMBER_ID", ""),
            whatsapp_api_version=values.get(
                "WHATSAPP_API_VERSION", "v21.0"),
            default_country_code=values.get("DEFAULT_COUNTRY_CODE", ""),
            send_interval_seconds=_as_float(
                values.get("SEND_INTERVAL_SECONDS"), 1.0),
            max_attempts=_as_int(values.get("MAX_ATTEMPTS"), 3),
            log_db=values.get("LOG_DB", "deliveries.db"),
        )


def _read_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _as_float(raw: str | None, default: float) -> float:
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _as_int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw else default
    except ValueError:
        return default
