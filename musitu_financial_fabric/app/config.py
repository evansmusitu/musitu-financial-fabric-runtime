from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as distribution_version


_PROVEN_PRODUCTION_PYTHONS = {(3, 12, 14), (3, 13, 15)}
_PROVEN_RUNTIME_DEPENDENCIES = {
    "annotated-doc": "0.0.5",
    "annotated-types": "0.8.0",
    "anyio": "4.15.1",
    "certifi": "2026.7.22",
    "click": "8.5.0",
    "defusedxml": "0.7.1",
    "fastapi": "0.141.1",
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "idna": "3.19",
    "psycopg": "3.3.5",
    "psycopg-binary": "3.3.5",
    "pydantic": "2.13.5",
    "pydantic-core": "2.46.5",
    "starlette": "1.6.0",
    "tigerbeetle": "0.17.8",
    "typing-extensions": "4.16.0",
    "typing-inspection": "0.4.4",
    "uvicorn": "0.52.4",
}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = _str(name, default)
    return tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))


def _csv_upper(name: str, default: str = "") -> tuple[str, ...]:
    raw = _str(name, default)
    return tuple(dict.fromkeys(part.strip().upper() for part in raw.split(",") if part.strip()))


def _assert_proven_production_runtime() -> None:
    python_version = tuple(sys.version_info[:3])
    if python_version not in _PROVEN_PRODUCTION_PYTHONS:
        allowed = ", ".join(".".join(map(str, value)) for value in sorted(_PROVEN_PRODUCTION_PYTHONS))
        raise ValueError(
            f"production Python runtime {'.'.join(map(str, python_version))} is outside evidence-locked versions: {allowed}"
        )
    for package, expected in _PROVEN_RUNTIME_DEPENDENCIES.items():
        try:
            actual = distribution_version(package)
        except PackageNotFoundError as exc:
            raise ValueError(f"production dependency {package} is missing; expected {expected}") from exc
        if actual != expected:
            raise ValueError(
                f"production dependency {package}=={actual} is outside evidence lock; expected {package}=={expected}"
            )


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: _str("MUSITU_DB_PATH", "./musitu_network.db"))
    metadata_db_url: str = field(default_factory=lambda: _str("MUSITU_METADATA_DB_URL"))
    metadata_db_connect_timeout_seconds: int = field(default_factory=lambda: int(_str("MUSITU_METADATA_DB_CONNECT_TIMEOUT_SECONDS", "5")))
    metadata_db_statement_timeout_seconds: int = field(default_factory=lambda: int(_str("MUSITU_METADATA_DB_STATEMENT_TIMEOUT_SECONDS", "10")))
    metadata_db_lock_timeout_seconds: int = field(default_factory=lambda: int(_str("MUSITU_METADATA_DB_LOCK_TIMEOUT_SECONDS", "5")))
    environment: str = field(default_factory=lambda: _str("MUSITU_ENV", "sandbox").lower())
    live_funds_enabled: bool = field(default_factory=lambda: _bool("MUSITU_LIVE_FUNDS_ENABLED", False))
    production_mode: str = field(default_factory=lambda: _str("MUSITU_PRODUCTION_MODE", "shadow").lower())
    production_enabled_rails: tuple[str, ...] = field(default_factory=lambda: _csv("MUSITU_PRODUCTION_ENABLED_RAILS"))
    production_enabled_currencies: tuple[str, ...] = field(default_factory=lambda: _csv_upper("MUSITU_PRODUCTION_ENABLED_CURRENCIES"))
    max_request_body_bytes: int = field(default_factory=lambda: int(_str("MUSITU_MAX_REQUEST_BODY_BYTES", "1048576")))

    authorization_manifest_path: str = field(default_factory=lambda: _str("MUSITU_AUTHORIZATION_MANIFEST_PATH"))
    authorization_manifest_sha256: str = field(default_factory=lambda: _str("MUSITU_AUTHORIZATION_MANIFEST_SHA256").lower())
    deployment_evidence_manifest_path: str = field(default_factory=lambda: _str("MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_PATH"))
    deployment_evidence_manifest_sha256: str = field(default_factory=lambda: _str("MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256").lower())
    target_environment_id: str = field(default_factory=lambda: _str("MUSITU_TARGET_ENVIRONMENT_ID"))
    build_commit: str = field(default_factory=lambda: _str("MUSITU_BUILD_COMMIT").lower())
    release_image_digest: str = field(default_factory=lambda: _str("MUSITU_RELEASE_IMAGE_DIGEST").lower())

    ledger_backend: str = field(default_factory=lambda: _str("MUSITU_LEDGER_BACKEND", "sqlite").lower())
    tigerbeetle_cluster_id: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_CLUSTER_ID", "0")))
    tigerbeetle_addresses: str = field(default_factory=lambda: _str("MUSITU_TIGERBEETLE_ADDRESSES"))
    tigerbeetle_operation_timeout_seconds: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_OPERATION_TIMEOUT_SECONDS", "5")))
    tigerbeetle_account_code: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_ACCOUNT_CODE", "100")))
    tigerbeetle_transfer_code: int = field(default_factory=lambda: int(_str("MUSITU_TIGERBEETLE_TRANSFER_CODE", "100")))

    auth_introspection_url: str = field(default_factory=lambda: _str("MUSITU_AUTH_INTROSPECTION_URL"))
    auth_client_id: str = field(default_factory=lambda: _str("MUSITU_AUTH_CLIENT_ID"))
    auth_client_secret: str = field(default_factory=lambda: _str("MUSITU_AUTH_CLIENT_SECRET"))
    auth_required_scope: str = field(default_factory=lambda: _str("MUSITU_AUTH_REQUIRED_SCOPE", "musitu.payments"))
    auth_expected_audience: str = field(default_factory=lambda: _str("MUSITU_AUTH_EXPECTED_AUDIENCE"))
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
    ecocash_callback_url: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CALLBACK_URL"))
    ecocash_client_id: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CLIENT_ID"))
    ecocash_client_secret: str = field(default_factory=lambda: _str("MUSITU_ECOCASH_CLIENT_SECRET"))
    max_single_payment_minor: int = field(default_factory=lambda: int(_str("MUSITU_MAX_SINGLE_PAYMENT_MINOR", "1000000")))

    def __post_init__(self) -> None:
        invalid_currency = next(
            (
                code
                for code in self.production_enabled_currencies
                if len(code) != 3 or not code.isascii() or not code.isalpha() or code != code.upper()
            ),
            None,
        )
        if invalid_currency is not None:
            raise ValueError("production currencies must use uppercase ASCII three-letter codes")
        if self.uses_postgres:
            if not 1 <= self.metadata_db_connect_timeout_seconds <= 30:
                raise ValueError("PostgreSQL connect timeout must be between 1 and 30 seconds")
            if not 1 <= self.metadata_db_statement_timeout_seconds <= 60:
                raise ValueError("PostgreSQL statement timeout must be between 1 and 60 seconds")
            if not 1 <= self.metadata_db_lock_timeout_seconds <= 30:
                raise ValueError("PostgreSQL lock timeout must be between 1 and 30 seconds")
            if self.metadata_db_lock_timeout_seconds > self.metadata_db_statement_timeout_seconds:
                raise ValueError("PostgreSQL lock timeout must not exceed statement timeout")
        if self.environment == "production" and self.uses_postgres and self.ledger_backend == "tigerbeetle":
            if not 1 <= self.tigerbeetle_operation_timeout_seconds <= 30:
                raise ValueError("production TigerBeetle operation timeout must be between 1 and 30 seconds")
            _assert_proven_production_runtime()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def uses_postgres(self) -> bool:
        return self.metadata_db_url.startswith(("postgresql://", "postgres://"))

    @property
    def expected_auth_audience(self) -> str:
        return self.auth_expected_audience or self.auth_client_id


settings = Settings()