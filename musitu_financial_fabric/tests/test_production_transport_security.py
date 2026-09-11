from __future__ import annotations

import pytest

from app.config import Settings
from app.production import ProductionGateError, enforce_safe_startup, production_readiness


def _cfg(**overrides):
    values = dict(
        environment="production",
        live_funds_enabled=False,
        production_mode="shadow",
        production_enabled_rails=("ecocash",),
        production_enabled_currencies=("USD",),
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_addresses="127.0.0.1:3000",
        auth_introspection_url="https://identity.invalid/introspect",
        auth_client_id="musitu",
        auth_client_secret="secret",
        authz_gate_url="https://authz.invalid/decision",
        risk_gate_url="https://risk.invalid/decision",
        webhook_secret="x" * 64,
        ecocash_contract_confirmed=True,
        ecocash_contract_version="contract-v1",
        ecocash_api_base="https://ecocash.invalid",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_client_id="client",
        ecocash_client_secret="secret",
        max_single_payment_minor=1000,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("field", "url", "message"),
    [
        ("auth_introspection_url", "http://identity.example/introspect", "identity introspection"),
        ("authz_gate_url", "http://authz.example/decision", "authorization gate"),
        ("risk_gate_url", "http://risk.example/decision", "risk gate"),
    ],
)
def test_production_rejects_plaintext_external_control_plane(field, url, message):
    cfg = _cfg(**{field: url})
    with pytest.raises(ProductionGateError, match=message):
        enforce_safe_startup(cfg)


def test_production_allows_plaintext_only_for_loopback_sidecars():
    cfg = _cfg(
        auth_introspection_url="http://127.0.0.1:8080/introspect",
        authz_gate_url="http://localhost:8181/decision",
        risk_gate_url="http://[::1]:9000/decision",
    )
    enforce_safe_startup(cfg)


def test_production_rejects_plaintext_ecocash_api():
    cfg = _cfg(ecocash_api_base="http://ecocash.example")
    with pytest.raises(ProductionGateError, match="EcoCash API requires HTTPS"):
        enforce_safe_startup(cfg)


def test_remote_postgres_requires_explicit_tls():
    cfg = _cfg(metadata_db_url="postgresql://musitu:test@db.example/musitu")
    with pytest.raises(ProductionGateError, match="explicit TLS"):
        enforce_safe_startup(cfg)


def test_remote_postgres_with_verify_full_is_accepted():
    cfg = _cfg(metadata_db_url="postgresql://musitu:test@db.example/musitu?sslmode=verify-full")
    enforce_safe_startup(cfg)


def test_readiness_reports_transport_failures():
    cfg = _cfg(
        live_funds_enabled=True,
        production_mode="pilot",
        auth_introspection_url="http://identity.example/introspect",
        metadata_db_url="postgresql://musitu:test@db.example/musitu",
    )
    result = production_readiness(cfg)
    failed = {row["key"] for row in result["checks"] if not row["ok"]}
    assert "auth_introspection_transport" in failed
    assert "metadata_transport" in failed
    assert result["ready_for_live_funds"] is False
