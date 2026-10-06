from __future__ import annotations

import pytest

from app import audit, db, sovereign
from app.config import Settings
from app.db import _PostgresConnection


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "exceptions.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def _participant():
    return sovereign.create_scheme_participant("Claimant PSP", "psp", "EXCPSP")


def test_scheme_exception_is_idempotent_audited_and_moves_no_funds(tmp_path):
    setup_env(tmp_path)
    claimant = _participant()

    first = sovereign.create_scheme_exception(
        "switch-txn-001",
        "dispute",
        claimant["id"],
        "goods-not-received",
        "exception-idem-1",
    )
    replay = sovereign.create_scheme_exception(
        "switch-txn-001",
        "dispute",
        claimant["id"],
        "goods-not-received",
        "exception-idem-1",
    )
    assert replay["id"] == first["id"]
    assert first["status"] == "open"

    evidence = sovereign.record_exception_evidence(
        first["id"], "merchant-correspondence-001", "claims-user"
    )
    replay_evidence = sovereign.record_exception_evidence(
        first["id"], "merchant-correspondence-001", "claims-user"
    )
    assert replay_evidence["id"] == evidence["id"]

    decided = sovereign.decide_scheme_exception(
        first["id"], "accepted", "scheme-operator", "authz-dispute-1"
    )
    assert decided["status"] == "accepted"

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"] == 0
    assert audit.verify_audit_chain()[0] is True


def test_exception_conflicts_invalid_kinds_and_terminal_transitions_fail_closed(tmp_path):
    setup_env(tmp_path)
    claimant = _participant()

    with pytest.raises(sovereign.SovereignError, match="kind"):
        sovereign.create_scheme_exception(
            "txn-bad", "chargeback", claimant["id"], "reason", "bad-kind"
        )

    case = sovereign.create_scheme_exception(
        "switch-txn-002",
        "refund_request",
        claimant["id"],
        "duplicate-charge",
        "exception-idem-2",
    )
    with pytest.raises(sovereign.SovereignError, match="conflicts"):
        sovereign.create_scheme_exception(
            "switch-txn-002",
            "refund_request",
            claimant["id"],
            "different-reason",
            "exception-idem-2",
        )

    sovereign.record_exception_evidence(case["id"], "receipt-001", "claims-user")
    with pytest.raises(sovereign.SovereignError, match="conflicting"):
        sovereign.record_exception_evidence(case["id"], "receipt-001", "other-user")

    rejected = sovereign.decide_scheme_exception(
        case["id"], "rejected", "scheme-operator", "authz-reject"
    )
    assert rejected["status"] == "rejected"

    with pytest.raises(sovereign.SovereignError, match="terminal"):
        sovereign.record_exception_evidence(case["id"], "late-evidence", "claims-user")
    with pytest.raises(sovereign.SovereignError, match="terminal"):
        sovereign.decide_scheme_exception(
            case["id"], "accepted", "scheme-operator", "authz-late"
        )


def test_exception_withdrawal_and_actor_requirements(tmp_path):
    setup_env(tmp_path)
    claimant = _participant()
    case = sovereign.create_scheme_exception(
        "switch-txn-003",
        "reversal_request",
        claimant["id"],
        "duplicate-transfer",
        "exception-idem-3",
    )
    with pytest.raises(sovereign.SovereignError, match="actor"):
        sovereign.decide_scheme_exception(case["id"], "withdrawn", "", "authz-withdraw")
    with pytest.raises(sovereign.SovereignError, match="authorization"):
        sovereign.decide_scheme_exception(case["id"], "withdrawn", "claims-user", "")

    withdrawn = sovereign.decide_scheme_exception(
        case["id"], "withdrawn", "claims-user", "authz-withdraw"
    )
    assert withdrawn["status"] == "withdrawn"


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return object()


def test_postgres_exception_idempotency_lookup_takes_per_key_lock_first():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)
    query = "SELECT * FROM scheme_exceptions WHERE idempotency_key=?"

    conn.execute(query, ("exception-idem-1",))

    assert raw.calls[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("exception-idem-1",),
    )
    assert raw.calls[1] == (
        "SELECT * FROM scheme_exceptions WHERE idempotency_key=%s",
        ("exception-idem-1",),
    )
