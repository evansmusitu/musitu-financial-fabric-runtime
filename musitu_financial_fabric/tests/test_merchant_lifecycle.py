from __future__ import annotations

import json

import pytest

from app import audit, db, merchant_lifecycle
from app.config import Settings


def _prepare(tmp_path, monkeypatch, *, status="pending_review", production=True):
    cfg = Settings(db_path=str(tmp_path / "merchant.db"), environment="production" if production else "sandbox")
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(merchant_lifecycle, "settings", cfg)
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_review", "Reviewed Merchant", status, "2026-09-11T00:00:00Z"),
        )
    return cfg


def test_pending_review_can_be_activated_with_audited_evidence(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    merchant = merchant_lifecycle.review_merchant(
        merchant_id="mrc_review",
        target_status="active",
        evidence_ref="KYC-CASE-123",
        actor="compliance-user-1",
        authorization_decision_id="authz-456",
    )

    assert merchant["status"] == "active"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE event_type='merchant.reviewed' AND entity_id='mrc_review'"
        ).fetchone()
    assert row is not None
    body = json.loads(row["body_json"])
    assert body["previous_status"] == "pending_review"
    assert body["target_status"] == "active"
    assert body["evidence_ref"] == "KYC-CASE-123"
    assert body["actor"] == "compliance-user-1"
    assert body["authorization_decision_id"] == "authz-456"
    assert audit.verify_audit_chain()[0] is True


def test_production_activation_requires_actor_and_authz_decision(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    with pytest.raises(merchant_lifecycle.MerchantLifecycleError, match="actor"):
        merchant_lifecycle.review_merchant(
            merchant_id="mrc_review",
            target_status="active",
            evidence_ref="KYC-CASE-123",
            actor="",
            authorization_decision_id="authz-456",
        )

    with pytest.raises(merchant_lifecycle.MerchantLifecycleError, match="authorization decision"):
        merchant_lifecycle.review_merchant(
            merchant_id="mrc_review",
            target_status="active",
            evidence_ref="KYC-CASE-123",
            actor="compliance-user-1",
            authorization_decision_id="",
        )


def test_activation_requires_external_evidence_reference(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    with pytest.raises(merchant_lifecycle.MerchantLifecycleError, match="evidence"):
        merchant_lifecycle.review_merchant(
            merchant_id="mrc_review",
            target_status="active",
            evidence_ref="",
            actor="compliance-user-1",
            authorization_decision_id="authz-456",
        )


def test_illegal_transition_fails_closed(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, status="active")

    with pytest.raises(merchant_lifecycle.MerchantLifecycleError, match="not allowed"):
        merchant_lifecycle.review_merchant(
            merchant_id="mrc_review",
            target_status="rejected",
            evidence_ref="CASE-999",
            actor="compliance-user-1",
            authorization_decision_id="authz-999",
        )

    with db.connect() as conn:
        status = conn.execute("SELECT status FROM merchants WHERE id='mrc_review'").fetchone()["status"]
    assert status == "active"


def test_active_merchant_can_be_suspended_and_reactivated(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, status="active")

    suspended = merchant_lifecycle.review_merchant(
        merchant_id="mrc_review",
        target_status="suspended",
        evidence_ref="RISK-HOLD-1",
        actor="risk-user-1",
        authorization_decision_id="authz-hold",
    )
    assert suspended["status"] == "suspended"

    reactivated = merchant_lifecycle.review_merchant(
        merchant_id="mrc_review",
        target_status="active",
        evidence_ref="RISK-CLEAR-2",
        actor="risk-user-2",
        authorization_decision_id="authz-clear",
    )
    assert reactivated["status"] == "active"


def test_repeat_same_target_is_idempotent(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, status="active")

    merchant = merchant_lifecycle.review_merchant(
        merchant_id="mrc_review",
        target_status="active",
        evidence_ref="CASE-RETRY",
        actor="compliance-user-1",
        authorization_decision_id="authz-retry",
    )

    assert merchant["status"] == "active"
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE event_type='merchant.reviewed'").fetchone()["n"]
    assert int(count) == 0
