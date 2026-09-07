from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("MUSITU_DB_PATH", "./musitu_network.db")
    environment: str = os.getenv("MUSITU_ENV", "sandbox")
    live_funds_enabled: bool = _bool("MUSITU_LIVE_FUNDS_ENABLED", False)
    webhook_secret: str = os.getenv("MUSITU_ECOCASH_WEBHOOK_SECRET", "sandbox-secret-change-me")
    ecocash_api_base: str = os.getenv("MUSITU_ECOCASH_API_BASE", "")
    ecocash_oauth_path: str = os.getenv("MUSITU_ECOCASH_OAUTH_PATH", "")
    ecocash_payment_path: str = os.getenv("MUSITU_ECOCASH_PAYMENT_PATH", "")
    ecocash_client_id: str = os.getenv("MUSITU_ECOCASH_CLIENT_ID", "")
    ecocash_client_secret: str = os.getenv("MUSITU_ECOCASH_CLIENT_SECRET", "")
    max_single_payment_minor: int = int(os.getenv("MUSITU_MAX_SINGLE_PAYMENT_MINOR", "1000000"))


settings = Settings()
