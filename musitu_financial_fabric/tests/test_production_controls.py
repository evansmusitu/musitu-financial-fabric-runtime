from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.ledger import _transfer_legs
from app.production import ProductionGateError, assert_live_funds_allowed, enforce_safe_startup, production_readiness


def _base_production(**overrides):
    values = dict(
        environment="production",
        live_funds_enabled=True,
        production_mode="pilot",
        production_enabled_rails=("ecocash",),
        production_enabled_currencies=("USD",),
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_cluster_id=1,
        tigerbeetle_addresses="127.0.0.1:3000",
        auth_introspection_url="https://identity.invalid/introspect",
        auth_client_id="musitu",
        auth_client_secret="test-client-secret",
        authz_gate_url="https://authz.invalid/decision",
        risk_gate_url="https://risk.invalid/decision",
        webhook_secret="x" * 64,
        ecocash_contract_confirmed=True,
        ecocash_contract_version="test-contract-v1",
        ecocash_api_base="https://ecocash.invalid",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_callback_url="https://musitu.invalid/v1/webhooks/ecocash",
        ecocash_client_id="test-client",
        ecocash_client_secret="test-secret",
        max_single_payment_minor=1000,
    )
    values.update(overrides)
    return Settings(**values)


def _approved_manifest(
    tmp_path,
    *,
    funds_scope: str = "pilot",
    launch_rails: list[str] | None = None,
    launch_currencies: list[str] | None = None,
    launch_max: int = 1000,
    include_launch_scope: bool = True,
    include_expiry: bool = True,
    expires_at: str | None = None,
) -> tuple[str, str]:
    manifest = {
        "funds_scope": funds_scope,
        "evidence": {
            "regulator": {"status": "approved", "evidence_ref": "RBZ-REF"},
            "sponsor_bank": {"status": "approved", "evidence_ref": "BANK-REF"},
            "data_protection": {"status": "approved", "evidence_ref": "DPA-REF"},
            "independent_security": {"status": "approved", "evidence_ref": "PENTEST-REF"},
            "rail_provider": {"status": "approved", "evidence_ref": "RAIL-CONTRACT-REF"},
        },
    }
    if include_launch_scope:
        manifest["launch_scope"] = {
            "rails": ["ecocash"] if launch_rails is None else launch_rails,
            "currencies": ["USD"] if launch_currencies is None else launch_currencies,
            "max_single_payment_minor": launch_max,
        }
    if include_expiry:
        manifest["expires_at"] = expires_at or (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    path = tmp_path / f"authorization-{funds_scope}.json"
    raw = json.dumps(manifest, sort_keys=True).encode()
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_live_funds_closed_without_external_evidence():
    cfg = _base_production()
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    with pytest.raises(ProductionGateError):
        assert_live_funds_allowed(cfg)


def test_pinned_approved_manifest_opens_pilot_control_gate(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="pilot")
    cfg = _base_production(
        production_mode="pilot",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    assert production_readiness(cfg)["ready_for_live_funds"] is True
    assert_live_funds_allowed(cfg)


def test_shadow_mode_never_opens_live_funds(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="production")
    cfg = _base_production(
        production_mode="shadow",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "production_mode" and not row["ok"] for row in result["checks"])
    assert any(row["key"] == "authorized_funds_scope" and not row["ok"] for row in result["checks"])
    with pytest.raises(ProductionGateError):
        assert_live_funds_allowed(cfg)


def test_pilot_authorization_cannot_open_live_runtime(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="pilot")
    cfg = _base_production(
        production_mode="live",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorized_funds_scope" and not row["ok"] for row in result["checks"])
    with pytest.raises(ProductionGateError):
        assert_live_funds_allowed(cfg)


def test_production_authorization_can_open_live_runtime(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="production")
    cfg = _base_production(
        production_mode="live",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    assert production_readiness(cfg)["ready_for_live_funds"] is True
    assert_live_funds_allowed(cfg)


def test_live_funds_reject_reserved_tigerbeetle_test_cluster(tmp_path):
    path, digest = _approved_manifest(tmp_path)
    cfg = _base_production(
        tigerbeetle_cluster_id=0,
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "tigerbeetle_cluster_id" and not row["ok"] for row in result["checks"])
    with pytest.raises(ProductionGateError, match="tigerbeetle_cluster_id"):
        assert_live_funds_allowed(cfg)


def test_live_funds_require_an_implemented_enabled_rail(tmp_path):
    path, digest = _approved_manifest(tmp_path)
    cfg = _base_production(
        production_enabled_rails=("bank",),
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "production_rails" and not row["ok"] for row in result["checks"])


def test_live_funds_require_complete_ecocash_connector(tmp_path):
    path, digest = _approved_manifest(tmp_path)
    cfg = _base_production(
        ecocash_client_secret="",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "ecocash_connector" and not row["ok"] for row in result["checks"])


def test_live_funds_require_dedicated_ecocash_callback(tmp_path):
    path, digest = _approved_manifest(tmp_path)
    cfg = _base_production(
        ecocash_callback_url="",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "ecocash_connector" and not row["ok"] for row in result["checks"])


def test_authorization_manifest_must_pin_launch_scope(tmp_path):
    path, digest = _approved_manifest(tmp_path, include_launch_scope=False)
    cfg = _base_production(authorization_manifest_path=path, authorization_manifest_sha256=digest)
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    failed = {row["key"] for row in result["checks"] if not row["ok"]}
    assert {"authorized_rails", "authorized_currencies", "authorized_single_payment_limit"}.issubset(failed)


def test_authorization_manifest_requires_explicit_expiry(tmp_path):
    path, digest = _approved_manifest(tmp_path, include_expiry=False)
    cfg = _base_production(authorization_manifest_path=path, authorization_manifest_sha256=digest)
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorization_not_expired" and not row["ok"] for row in result["checks"])


def test_expired_authorization_manifest_fails_closed(tmp_path):
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    path, digest = _approved_manifest(tmp_path, expires_at=expired)
    cfg = _base_production(authorization_manifest_path=path, authorization_manifest_sha256=digest)
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorization_not_expired" and not row["ok"] for row in result["checks"])


def test_runtime_rail_cannot_exceed_pinned_launch_scope(tmp_path):
    path, digest = _approved_manifest(tmp_path, launch_rails=[])
    cfg = _base_production(authorization_manifest_path=path, authorization_manifest_sha256=digest)
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorized_rails" and not row["ok"] for row in result["checks"])


def test_runtime_currency_cannot_exceed_pinned_launch_scope(tmp_path):
    path, digest = _approved_manifest(tmp_path, launch_currencies=["USD"])
    cfg = _base_production(
        production_enabled_currencies=("USD", "EUR"),
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorized_currencies" and not row["ok"] for row in result["checks"])


def test_runtime_payment_ceiling_cannot_exceed_pinned_launch_scope(tmp_path):
    path, digest = _approved_manifest(tmp_path, launch_max=1000)
    cfg = _base_production(
        max_single_payment_minor=1001,
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorized_single_payment_limit" and not row["ok"] for row in result["checks"])


def test_manifest_tampering_fails_closed(tmp_path):
    path = tmp_path / "authorization.json"
    original = b'{"funds_scope":"pilot","evidence":{}}'
    path.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    path.write_text('{"funds_scope":"production","evidence":{}}')
    cfg = _base_production(
        authorization_manifest_path=str(path),
        authorization_manifest_sha256=digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(row["key"] == "authorization_manifest" and not row["ok"] for row in result["checks"])


def test_production_startup_rejects_sqlite():
    cfg = _base_production(metadata_db_url="")
    with pytest.raises(ProductionGateError, match="PostgreSQL"):
        enforce_safe_startup(cfg)


def test_production_startup_rejects_unknown_mode():
    cfg = _base_production(production_mode="anything-else", live_funds_enabled=False)
    with pytest.raises(ProductionGateError, match="MUSITU_PRODUCTION_MODE"):
        enforce_safe_startup(cfg)


def test_production_startup_rejects_reserved_tigerbeetle_test_cluster():
    cfg = _base_production(tigerbeetle_cluster_id=0, live_funds_enabled=False)
    with pytest.raises(ProductionGateError, match="cluster 0 is reserved"):
        enforce_safe_startup(cfg)


def test_multi_posting_decomposes_to_balanced_transfer_legs():
    postings = [("a", -70), ("b", -30), ("c", 25), ("d", 75)]
    legs = _transfer_legs(postings)
    assert sum(amount for _, _, amount in legs) == 100
    debit_totals = {}
    credit_totals = {}
    for debit, credit, amount in legs:
        debit_totals[debit] = debit_totals.get(debit, 0) + amount
        credit_totals[credit] = credit_totals.get(credit, 0) + amount
    assert debit_totals == {"a": 70, "b": 30}
    assert credit_totals == {"c": 25, "d": 75}