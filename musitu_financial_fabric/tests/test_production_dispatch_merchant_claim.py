from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import audit, db, service
from app.config import Settings


def _selected():
    return SimpleNamespace(
        rail="ecocash",
        score=1.0,
        cost_bps=0,
        latency_ms=1,
        success_probability=1.0,
    )


def _configure_sqlite_production(tmp_path, monkeypatch):
    cfg = Settings(db_path=str(tmp_path / "dispatch-claim.db"), environment="production")
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(service, "settings", cfg)
    db.init_db()
    return cfg


def _claim(**overrides):
    values = dict(
        payment_id="pay_claim",
        merchant_id="mrc_claim",
        destination_account_id="acct_claim",
        amount_minor=100,
        currency="USD",
        selected=_selected(),
        requested_rail="ecocash",
        payer_ref="payer",
        description="claim test",
        idempotency_key="idem_claim",
        request_hash="hash-claim",
        risk_score=1,
        risk_decision_id="risk-claim",
        ts="2026-09-11T18:00:00+00:00",
    )
    values.update(overrides)
    return service._persist_production_dispatch(**values)


def test_dispatch_claim_rejects_merchant_suspended_after_initial_validation(tmp_path, monkeypatch):
    _configure_sqlite_production(tmp_path, monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_claim", "Claim Merchant", "suspended", "2026-09-11T17:00:00+00:00"),
        )

    with pytest.raises(service.PaymentError, match="not active at production dispatch claim"):
        _claim()

    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM payment_intents WHERE id=?", ("pay_claim",)).fetchone()["n"]
    assert int(count) == 0


def test_active_merchant_dispatch_claim_still_commits_atomically(tmp_path, monkeypatch):
    _configure_sqlite_production(tmp_path, monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_claim", "Claim Merchant", "active", "2026-09-11T17:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_claim", "merchant", "mrc_claim", "USD", "settlement", "active", "2026-09-11T17:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO payment_idempotency
               (idempotency_key,request_hash,status,payment_id,created_at,updated_at)
               VALUES (?,?,'reserved',NULL,?,?)""",
            ("idem_claim", "hash-claim", "2026-09-11T17:00:00+00:00", "2026-09-11T17:00:00+00:00"),
        )

    _claim()

    with db.connect() as conn:
        payment = conn.execute("SELECT status FROM payment_intents WHERE id=?", ("pay_claim",)).fetchone()
        idem = conn.execute(
            "SELECT status,payment_id FROM payment_idempotency WHERE idempotency_key=?",
            ("idem_claim",),
        ).fetchone()
    assert payment["status"] == "dispatching"
    assert idem["status"] == "committed"
    assert idem["payment_id"] == "pay_claim"
