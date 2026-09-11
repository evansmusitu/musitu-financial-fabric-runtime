from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: _str("MUSITU_DB_PATH", "./musitu_network.db"))
    metadata_db_url: str = field(default_factory=lambda: _str("MUSITU_METADATA_DB_URL"))
    environment: str = field(default_factory=lambda: _str("MUSITU_ENV", "sandbox").lower())
    live_funds_enabled: bool = field(default_factory=lambda: _bool("MUSITU_LIVE_FUNDS_ENABLED", False))
    production_mode: str = field(default_factory=lambda: _str("MUSITU_PRODUCTION_MODE", "shadow").lower())

    authorization_manifest_path: str = field(default_factory=lambda: _str("MUSITU_AUTHORIZATION_MANIFEST_PATH"))
    authorization_manifest_sha256: str = field(default_factory=lambda: _str("MUSITU_AUTHORIZATION_MANIFEST_SHA256").lower())

    ledger_backend: str = field(default_factory=lambda: _str("MUSITU_LEDGER_BACKEND", "sqlite").lower())
    tigerbeetle_cluster_id: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_CLUSTER_ID", "0")))
    tigerbeetle_addresses: str = field(default_factory=lambda: _str("MUSITU_TIGERBEETLE_ADDRESSES"))
    tigerbeetle_account_code: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_ACCOUNT_CODE", "100")))
    tigerbeetle_transfer_code: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_TRANSFER_CODE", "100")))

    auth_introspection_url: str = field(default_factory=lambda: _str("MUSITU_AUTH_INTROSPECTION_URL"))
    auth_client_id: str = field(default_factory=lambda: _str("MUSITU_AUTH_CLIENT_ID"))
    auth_client_secret: str = field(default_factory=lambda: _str("MUSITU_AUTH_CLIENT_SECRET"))
    auth_required_scope: str = field(default_factory=lambda: _str("MUSITU_AUTH_REQUIRED_SCOPE", "musitu.payments"))
    authz_gate_url: str = field(default_factory=lambda: _str("MUSITU_AUTHZ_GATE_URL"))
    authz_gate_token: str = field(default_factory=lambda: _str("MUSITU_AUTHZ_GATE_TOKEN"))

    risk_gate_url: str = field(default_factory=lambda: _str("MUSITU_RISK_GATE_URL"))
    risk_gate_token: str = field(default_factory=lambda: _str("MUSITU_RISK_GATE_TOKEN"))

    webhook_secret: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_WEBHOOK_SECRET", "sandbox-secret-change-me"))
    ecocash_contract_confirmed: bool = field(default_factory=lambda: _bool("MUSITU_ECOCASH_CONTRACT_CONFIRMED", False))
    ecocash_contract_version: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CONTRACT_VERSION"))
    ecocash_api_base: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_API_BASE"))
    ecocash_oauth_path: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_OAUTH_PATH"))
    ecocash_payment_path: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_PAYMENT_PATH"))
    ecocash_client_id: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CLIENT_ID"))
    ecocash_client_secret: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CLIENT_SECRET"))
    max_single_payment_minor: int = field(default_factory=lambda: int(_str("MUSITU_MAX_SINGLE_PAYMENT_MINOR", "1000000")))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def uses_postgres(self) -> bool:
        return self.metadata_db_url.startswith(("postgresql://", "postgres://"))


settings = Settings()
