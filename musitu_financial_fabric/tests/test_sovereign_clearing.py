from __future__ import annotations

import pytest

from app import audit, db, sovereign
from app.config import Settings
from app.db import _PostgresConnection


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "clearing.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def _participants():
    debtor = sovereign.create_scheme_participant("Debtor Bank", "bank", "CLRDEBT")
    creditor = sovereign.create_scheme_participant("Creditor PSP", "psp", "CLRCRED")
    third = sovereign.create_scheme_participant("Third Bank", "bank", "CLRTHIRD")
    return debtor, creditor, third


def test_clearing_cycle_nets_to_zero_and_has_no_payment_side_effect(tmp_path):
    setup_env(tmp_path)
    debtor, creditor, third = _participants()
    cycle = sovereign.open_settlement_cycle("generic-instant-payments", "cycle-001", "USD")
    assert cycle["status"] == "open"

    first = sovereign.record_clearing_obligation(
        cycle["id"], debtor["id"], creditor["id"], 1000, "external-001"
    )
    replay = sovereign.record_clearing_obligation(
        cycle["id"], debtor["id"], creditor["id"], 1000, "external-001"
    )
    assert replay["id"] == first["id"]
    sovereign.record_clearing_obligation(
        cycle["id"], creditor["id"], third["id"], 250, "external-002"
    )

    positions = sovereign.calculate_net_positions(cycle["id"])
    assert positions["currency"] == "USD"
    assert positions["balanced"] is True
    assert positions["sum_minor"] == 0
    assert positions["positions_minor"][debtor["id"]] == -1000
    assert positions["positions_minor"][creditor["id"]] == 750
    assert positions["positions_minor"][third["id"]] == 250

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"] == 0
    assert audit.verify_audit_chain()[0] is True


def test_clearing_conflicts_and_closed_cycle_fail_closed(tmp_path):
    setup_env(tmp_path)
    debtor, creditor, third = _participants()
    cycle = sovereign.open_settlement_cycle("generic", "cycle-002", "USD")
    sovereign.record_clearing_obligation(
        cycle["id"], debtor["id"], creditor["id"], 500, "same-ref"
    )

    with pytest.raises(sovereign.SovereignError, match="conflicts"):
        sovereign.record_clearing_obligation(
            cycle["id"], debtor["id"], third["id"], 500, "same-ref"
        )
    with pytest.raises(sovereign.SovereignError, match="distinct"):
        sovereign.record_clearing_obligation(
            cycle["id"], debtor["id"], debtor["id"], 100, "self-ref"
        )
    with pytest.raises(sovereign.SovereignError, match="evidence"):
        sovereign.close_settlement_cycle(cycle["id"], "", "operator", "authz-close")

    closed = sovereign.close_settlement_cycle(
        cycle["id"], "external-settlement-proof-001", "operator", "authz-close"
    )
    assert closed["status"] == "closed"
    assert closed["settlement_evidence_ref"] == "external-settlement-proof-001"
    assert closed["external_settlement_verified"] is False

    with pytest.raises(sovereign.SovereignError, match="closed"):
        sovereign.record_clearing_obligation(
            cycle["id"], creditor["id"], debtor["id"], 100, "after-close"
        )
    with pytest.raises(sovereign.SovereignError, match="closed"):
        sovereign.close_settlement_cycle(
            cycle["id"], "another-proof", "operator", "authz-close-2"
        )


def test_cycle_currency_and_reference_validation(tmp_path):
    setup_env(tmp_path)
    with pytest.raises(sovereign.SovereignError, match="currency"):
        sovereign.open_settlement_cycle("generic", "cycle-bad", "US1")

    first = sovereign.open_settlement_cycle("generic", "unique-cycle", "USD")
    assert first["currency"] == "USD"
    with pytest.raises(sovereign.SovereignError, match="cycle reference"):
        sovereign.open_settlement_cycle("generic", "unique-cycle", "USD")


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return object()


def test_postgres_clearing_external_ref_lookup_takes_per_ref_lock_first():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)
    query = "SELECT * FROM scheme_clearing_obligations WHERE external_ref=?"

    conn.execute(query, ("clear-ref-1",))

    assert raw.calls[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("clear-ref-1",),
    )
    assert raw.calls[1] == (
        "SELECT * FROM scheme_clearing_obligations WHERE external_ref=%s",
        ("clear-ref-1",),
    )
