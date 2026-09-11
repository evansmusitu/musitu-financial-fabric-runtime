from __future__ import annotations

from dataclasses import dataclass

import pytest

from app import db, reconciliation
from app.config import Settings


@dataclass
class _TBAccount:
    id: int
    debits_posted: int
    credits_posted: int


class _Client:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error
        self.closed = False

    def lookup_accounts(self, ids):
        if self.error:
            raise self.error
        wanted = set(ids)
        return [row for row in self.rows if row.id in wanted]

    def close(self):
        self.closed = True


def _prepare(tmp_path, monkeypatch, *, postings=(100, -100)):
    cfg = Settings(
        db_path=str(tmp_path / "reconcile.db"),
        environment="production",
        ledger_backend="tigerbeetle",
        tigerbeetle_addresses="127.0.0.1:3000",
    )
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(reconciliation, "settings", cfg)
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_a", "system", "a", "USD", "rail_clearing", "active", "2026-09-11T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_b", "merchant", "b", "USD", "settlement", "active", "2026-09-11T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO journal_entries(id,reference,memo,created_at) VALUES (?,?,?,?)",
            ("jrnl_test", "test:reconcile", "test", "2026-09-11T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO ledger_postings(journal_id,account_id,delta_minor) VALUES (?,?,?)",
            ("jrnl_test", "acct_a", int(postings[0])),
        )
        conn.execute(
            "INSERT INTO ledger_postings(journal_id,account_id,delta_minor) VALUES (?,?,?)",
            ("jrnl_test", "acct_b", int(postings[1])),
        )
    return cfg


def _row(account_id: str, balance: int) -> _TBAccount:
    if balance >= 0:
        return _TBAccount(reconciliation._u128(account_id), 0, balance)
    return _TBAccount(reconciliation._u128(account_id), -balance, 0)


def test_monetary_truth_consistent_when_mirror_matches(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    client = _Client([_row("acct_a", 100), _row("acct_b", -100)])
    monkeypatch.setattr(reconciliation, "_tb_client", lambda: (object(), client))

    result = reconciliation.reconcile_monetary_truth()

    assert result["consistent"] is True
    assert result["accounts_checked"] == 2
    assert result["missing_accounts"] == []
    assert result["mismatches"] == []
    assert client.closed is True


def test_monetary_truth_detects_balance_divergence(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    client = _Client([_row("acct_a", 99), _row("acct_b", -100)])
    monkeypatch.setattr(reconciliation, "_tb_client", lambda: (object(), client))

    result = reconciliation.reconcile_monetary_truth()

    assert result["consistent"] is False
    assert result["mismatches"] == [
        {
            "account_id": "acct_a",
            "currency": "USD",
            "expected_balance_minor": 100,
            "actual_balance_minor": 99,
            "delta_minor": -1,
        }
    ]


def test_monetary_truth_detects_missing_tigerbeetle_account(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    client = _Client([_row("acct_a", 100)])
    monkeypatch.setattr(reconciliation, "_tb_client", lambda: (object(), client))

    result = reconciliation.reconcile_monetary_truth()

    assert result["consistent"] is False
    assert result["missing_accounts"] == [{"account_id": "acct_b", "currency": "USD"}]


def test_monetary_truth_lookup_error_fails_closed(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    client = _Client(error=RuntimeError("simulated outage"))
    monkeypatch.setattr(reconciliation, "_tb_client", lambda: (object(), client))

    result = reconciliation.reconcile_monetary_truth()

    assert result["consistent"] is False
    assert result["error"] == "tigerbeetle_lookup:RuntimeError"
    assert client.closed is True


def test_reference_ledger_is_not_applicable_without_database_access(monkeypatch):
    cfg = Settings(environment="sandbox", ledger_backend="sqlite")
    monkeypatch.setattr(reconciliation, "settings", cfg)

    result = reconciliation.reconcile_monetary_truth()

    assert result["applicable"] is False
    assert result["consistent"] is True
    assert result["accounts_checked"] == 0


@pytest.mark.asyncio
async def test_readiness_fails_closed_on_monetary_truth_divergence(monkeypatch):
    from app import main

    cfg = Settings(environment="production", live_funds_enabled=True, ledger_backend="tigerbeetle")
    monkeypatch.setattr(main, "settings", cfg)

    async def healthy_components():
        return {"all_required_runtime_healthy": True, "components": []}

    monkeypatch.setattr(main, "probe_components", healthy_components)
    monkeypatch.setattr(main, "_audit_readiness", lambda: {"valid": True, "events": 1, "broken_at": None})
    monkeypatch.setattr(main, "production_readiness", lambda: {"ready_for_live_funds": True, "checks": []})
    monkeypatch.setattr(
        main,
        "reconcile_monetary_truth",
        lambda: {
            "applicable": True,
            "backend": "tigerbeetle",
            "consistent": False,
            "accounts_checked": 2,
            "missing_accounts": [],
            "mismatches": [{"account_id": "acct_a"}],
        },
    )

    snapshot = await main._readiness_snapshot()

    assert snapshot["service_ready"] is False
    assert snapshot["production_funds_gate"] is False
    assert snapshot["monetary_truth"]["consistent"] is False
