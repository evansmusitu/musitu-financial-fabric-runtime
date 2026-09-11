from __future__ import annotations

import pytest

from app import audit, db, ledger, settlement
from app.config import Settings


def _prepare(tmp_path, monkeypatch, *, status: str = "pending"):
    db_cfg = Settings(db_path=str(tmp_path / "settlement.db"), environment="sandbox")
    production_cfg = Settings(db_path=str(tmp_path / "settlement.db"), environment="production")
    monkeypatch.setattr(db, "settings", db_cfg)
    monkeypatch.setattr(audit, "settings", db_cfg)
    monkeypatch.setattr(ledger, "settings", db_cfg)
    monkeypatch.setattr(settlement, "settings", production_cfg)
    monkeypatch.setattr(settlement, "assert_live_funds_allowed", lambda: None)
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_settle", "Settlement Merchant", "active", "2026-09-11T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_settle", "merchant", "mrc_settle", "USD", "settlement", "active", "2026-09-11T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO payment_intents
               (id,merchant_id,destination_account_id,amount_minor,currency,rail,payer_ref,description,status,external_reference,idempotency_key,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "pay_settle",
                "mrc_settle",
                "acct_settle",
                100,
                "USD",
                "ecocash",
                "payer",
                None,
                status,
                "eco_settle",
                "idem_settle",
                "2026-09-11T00:00:00+00:00",
                "2026-09-11T00:00:00+00:00",
            ),
        )
    return db_cfg


def test_success_claim_blocks_competing_failure_after_settlement_starts(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    real_post = settlement.post
    observed = {}

    def racing_post(*args, **kwargs):
        with db.connect() as conn:
            observed["status_before_ledger"] = conn.execute(
                "SELECT status FROM payment_intents WHERE id='pay_settle'"
            ).fetchone()["status"]
        with pytest.raises(settlement.ProviderSettlementError, match="settlement is in progress"):
            settlement.provider_fail(
                provider="ecocash",
                payment_id="pay_settle",
                provider_event_id="evt_fail_race",
            )
        return real_post(*args, **kwargs)

    monkeypatch.setattr(settlement, "post", racing_post)
    payment = settlement.provider_succeed(
        provider="ecocash",
        payment_id="pay_settle",
        provider_event_id="evt_success",
    )

    assert observed["status_before_ledger"] == "settling"
    assert payment["status"] == "succeeded"
    assert ledger.balance("acct_settle") == 100


def test_settling_state_is_idempotently_recoverable(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, status="settling")

    first = settlement.provider_succeed(
        provider="ecocash",
        payment_id="pay_settle",
        provider_event_id="evt_recover_1",
    )
    second = settlement.provider_succeed(
        provider="ecocash",
        payment_id="pay_settle",
        provider_event_id="evt_recover_2",
    )

    assert first["status"] == "succeeded"
    assert second["status"] == "succeeded"
    assert ledger.balance("acct_settle") == 100
    with db.connect() as conn:
        journals = conn.execute(
            "SELECT COUNT(*) AS n FROM journal_entries WHERE reference='payment:pay_settle'"
        ).fetchone()["n"]
    assert int(journals) == 1


def test_failure_can_win_before_success_claim_but_success_cannot_post_afterward(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    failed = settlement.provider_fail(
        provider="ecocash",
        payment_id="pay_settle",
        provider_event_id="evt_fail_first",
    )
    assert failed["status"] == "failed"

    with pytest.raises(settlement.ProviderSettlementError, match="cannot settle payment in status failed"):
        settlement.provider_succeed(
            provider="ecocash",
            payment_id="pay_settle",
            provider_event_id="evt_success_late",
        )
    assert ledger.balance("acct_settle") == 0
