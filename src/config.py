"""Configuration loader and validation."""

import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    """Holds configuration values."""

    telegram_bot_token: str
    database_url: str
    webhook_base_url: str
    webhook_secret: str
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    webhook_path: str = "/telegram/webhook"
    port: int = 8080
    log_level: str = "INFO"


def load_config() -> Config:
    """
    Load configuration from environment variables.

    Reads .env file if present. Raises ValueError if required variables are missing.
    """
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    database_url = os.getenv("DATABASE_URL")
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL")
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    webhook_path = os.getenv("WEBHOOK_PATH", "/telegram/webhook")
    port_raw = os.getenv("PORT", "8080")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    missing = []
    if not telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not database_url:
        missing.append("DATABASE_URL")
    if not webhook_base_url:
        missing.append("WEBHOOK_BASE_URL")
    if not webhook_secret:
        missing.append("WEBHOOK_SECRET")

    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    if not webhook_path.startswith("/"):
        raise ValueError("WEBHOOK_PATH must start with '/'")
    if "=" in webhook_base_url:
        raise ValueError("WEBHOOK_BASE_URL must contain only the URL, not 'KEY=value'")
    if not webhook_base_url.startswith("https://"):
        raise ValueError("WEBHOOK_BASE_URL must start with 'https://'")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(f"Invalid PORT: {port_raw}") from exc

    # Validate log level
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError(f"Invalid LOG_LEVEL: {log_level}")

    return Config(
        telegram_bot_token=telegram_bot_token,
        database_url=database_url,
        webhook_base_url=webhook_base_url.rstrip("/"),
        webhook_secret=webhook_secret,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        webhook_path=webhook_path,
        port=port,
        log_level=log_level,
    )


def setup_logging(level: str = "INFO") -> None:
    """Configure basic logging."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
