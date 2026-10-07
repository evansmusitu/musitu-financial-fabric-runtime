from __future__ import annotations

import pytest

from app import audit, db, sovereign
from app.config import Settings


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "cert.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def test_certification_requires_all_mandatory_checks_and_does_not_activate_participant(tmp_path):
    setup_env(tmp_path)
    p = sovereign.create_scheme_participant("Bank", "bank", "CERTBANK")
    case = sovereign.create_certification_case(
        p["id"], "generic-instant-payments", "scheme-evaluation-1", ["security", "interop"]
    )
    assert case["status"] == "open"
    assert case["required_checks"] == ["interop", "security"]

    sovereign.record_certification_check(case["id"], "security", "passed", "sec-report", "tester")
    with pytest.raises(sovereign.SovereignError, match="mandatory"):
        sovereign.decide_certification(case["id"], "approved", "operator", "authz-1")

    first = sovereign.record_certification_check(case["id"], "interop", "passed", "interop-report", "tester")
    replay = sovereign.record_certification_check(case["id"], "interop", "passed", "interop-report", "tester")
    assert replay["id"] == first["id"]
    with pytest.raises(sovereign.SovereignError, match="conflicting"):
        sovereign.record_certification_check(case["id"], "interop", "failed", "different", "tester")

    approved = sovereign.decide_certification(case["id"], "approved", "operator", "authz-1")
    assert approved["status"] == "approved"
    with db.connect() as conn:
        participant = conn.execute("SELECT status FROM scheme_participants WHERE id=?", (p["id"],)).fetchone()
        assert participant["status"] == "sandbox"
        assert conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"] == 0
    assert audit.verify_audit_chain()[0] is True


def test_certification_terminal_and_unknown_check_fail_closed(tmp_path):
    setup_env(tmp_path)
    p = sovereign.create_scheme_participant("PSP", "psp", "CERTPSP")
    case = sovereign.create_certification_case(p["id"], "generic", "eval-2", ["security"])
    with pytest.raises(sovereign.SovereignError, match="required check"):
        sovereign.record_certification_check(case["id"], "not-required", "passed", "x", "tester")
    rejected = sovereign.decide_certification(case["id"], "rejected", "operator", "authz-r")
    assert rejected["status"] == "rejected"
    with pytest.raises(sovereign.SovereignError, match="terminal"):
        sovereign.record_certification_check(case["id"], "security", "passed", "sec", "tester")
