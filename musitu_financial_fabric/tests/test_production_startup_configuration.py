from __future__ import annotations

import pytest

from app.config import Settings
from app.production import ProductionGateError, enforce_safe_startup, production_readiness


def _cfg(**overrides) -> Settings:
    values = dict(
        environment="production",
        live_funds_enabled=False,
        production_mode="shadow",
        production_enabled_rails=("ecocash",),
        production_enabled_currencies=("USD",),
        max_request_body_bytes=1024,
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_cluster_id=1,
        tigerbeetle_addresses="127.0.0.1:3000",
        auth_introspection_url="https://identity.invalid/introspect",
        auth_client_id="musitu",
        auth_client_secret="secret",
        auth_required_scope="musitu.payments",
        authz_gate_url="https://authz.invalid/decision",
        risk_gate_url="https://risk.invalid/decision",
        webhook_secret="x" * 64,
        ecocash_api_base="https://ecocash.invalid",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_callback_url="https://musitu.invalid/v1/webhooks/ecocash",
    )
    values.update(overrides)
    return Settings(**values)


def _failed_keys(cfg: Settings) -> set[str]:
    return {row["key"] for row in production_readiness(cfg)["checks"] if not row["ok"]}


def test_valid_shadow_software_configuration_passes_startup_guard():
    enforce_safe_startup(_cfg())


def test_nonpositive_request_body_limit_fails_startup_and_readiness():
    cfg = _cfg(max_request_body_bytes=0)
    with pytest.raises(ProductionGateError, match="request body limit"):
        enforce_safe_startup(cfg)
    assert "request_body_limit" in _failed_keys(cfg)


def test_payment_limit_above_postgres_bigint_fails_startup_and_readiness():
    cfg = _cfg(max_single_payment_minor=1 << 63)
    with pytest.raises(ProductionGateError, match="PostgreSQL BIGINT"):
        enforce_safe_startup(cfg)
    assert "single_payment_limit" in _failed_keys(cfg)


def test_postgres_bigint_payment_limit_boundary_is_accepted():
    enforce_safe_startup(_cfg(max_single_payment_minor=(1 << 63) - 1))


def test_blank_required_auth_scope_fails_startup_and_readiness():
    cfg = _cfg(auth_required_scope="   ")
    with pytest.raises(ProductionGateError, match="scope"):
        enforce_safe_startup(cfg)
    assert "auth_required_scope" in _failed_keys(cfg)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ecocash_oauth_path", "https://attacker.invalid/oauth", "OAuth endpoint"),
        ("ecocash_oauth_path", "//attacker.invalid/oauth", "OAuth endpoint"),
        ("ecocash_payment_path", "https://attacker.invalid/payments", "payment endpoint"),
        ("ecocash_payment_path", "//attacker.invalid/payments", "payment endpoint"),
    ],
)
def test_ecocash_endpoint_host_escape_fails_startup_and_readiness(field, value, message):
    cfg = _cfg(**{field: value})
    with pytest.raises(ProductionGateError, match=message):
        enforce_safe_startup(cfg)
    assert "ecocash_endpoint_paths" in _failed_keys(cfg)
