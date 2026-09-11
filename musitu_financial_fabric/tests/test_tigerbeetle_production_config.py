from __future__ import annotations

import pytest

from app.config import Settings
from app.production import ProductionGateError, enforce_safe_startup, production_readiness


def _cfg(**overrides):
    values = dict(
        environment="production",
        live_funds_enabled=False,
        production_mode="shadow",
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_cluster_id=1,
        tigerbeetle_addresses="127.0.0.1:3000",
        tigerbeetle_account_code=100,
        tigerbeetle_transfer_code=100,
        auth_introspection_url="https://identity.invalid/introspect",
        auth_client_id="musitu",
        auth_client_secret="secret",
        authz_gate_url="https://authz.invalid/decision",
        risk_gate_url="https://risk.invalid/decision",
        webhook_secret="x" * 64,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("field", "check_key", "value"),
    [
        ("tigerbeetle_account_code", "tigerbeetle_account_code", 0),
        ("tigerbeetle_account_code", "tigerbeetle_account_code", 65536),
        ("tigerbeetle_transfer_code", "tigerbeetle_transfer_code", 0),
        ("tigerbeetle_transfer_code", "tigerbeetle_transfer_code", 65536),
    ],
)
def test_readiness_rejects_invalid_tigerbeetle_codes(field, check_key, value):
    cfg = _cfg(**{field: value})
    result = production_readiness(cfg)
    assert any(row["key"] == check_key and not row["ok"] for row in result["checks"])
    assert result["ready_for_live_funds"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tigerbeetle_account_code", 0, "account code"),
        ("tigerbeetle_account_code", 65536, "account code"),
        ("tigerbeetle_transfer_code", 0, "transfer code"),
        ("tigerbeetle_transfer_code", 65536, "transfer code"),
    ],
)
def test_startup_rejects_invalid_tigerbeetle_codes(field, value, message):
    cfg = _cfg(**{field: value})
    with pytest.raises(ProductionGateError, match=message):
        enforce_safe_startup(cfg)
