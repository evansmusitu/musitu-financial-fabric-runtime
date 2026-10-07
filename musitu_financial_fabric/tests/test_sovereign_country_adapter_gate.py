from __future__ import annotations

import pytest

from app import audit, db, sovereign
from app import sovereign_evidence as evidence
from app.config import Settings
from app.db import _PostgresConnection


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "country-gate.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def test_zimbabwe_country_gate_starts_blocked_and_reference_status_does_not_unblock(tmp_path):
    setup_env(tmp_path)
    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert gate["profile_key"] == "zimbabwe-2026"
    assert gate["external_dependencies_ready"] is False
    assert gate["production_enabled"] is False

    required = {
        "national_switch_message_interface",
        "authoritative_mai_allocation",
        "emvco_conformance",
        "participant_certification_pack",
        "settlement_finality_rules",
    }
    assert set(gate["dependencies"]) == required
    assert set(gate["blockers"]) == required
    assert all(item["status"] == "unconfigured" for item in gate["dependencies"].values())

    changed = sovereign.set_country_profile_dependency(
        "zimbabwe-2026",
        "national_switch_message_interface",
        "reference",
        evidence_ref="draft-interface-not-authoritative",
        actor="sandbox",
        authorization_decision_id="sandbox",
    )
    assert changed["status"] == "reference"

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert gate["external_dependencies_ready"] is False
    assert "national_switch_message_interface" in gate["blockers"]


def test_external_verification_requires_evidence_and_all_dependencies(tmp_path):
    setup_env(tmp_path)
    dependencies = list(sovereign.country_profile_gate("zimbabwe-2026")["dependencies"])

    with pytest.raises(sovereign.SovereignError, match="evidence"):
        sovereign.set_country_profile_dependency(
            "zimbabwe-2026",
            dependencies[0],
            "externally_verified",
            evidence_ref="",
            actor="operator",
            authorization_decision_id="authz-1",
        )

    for index, key in enumerate(dependencies):
        record = evidence.register_country_profile_evidence(
            "zimbabwe-2026",
            key,
            evidence_ref=f"external-evidence-{index}",
            source_authority="Test Operator",
            source_version="v1",
            source_location=f"operator-room/{key}.pdf",
            source_sha256=f"{index + 1:064x}",
            actor="operator-intake",
        )
        evidence.verify_country_profile_evidence(
            record["id"],
            actor="operator-reviewer",
            authorization_decision_id=f"verify-{index}",
        )
        verified = evidence.promote_country_profile_dependency_from_evidence(
            "zimbabwe-2026",
            key,
            record["id"],
            actor="operator",
            authorization_decision_id=f"authz-{index}",
        )
        assert verified["status"] == "externally_verified"
        assert verified["evidence_ref"].startswith("evidence-record:")
        assert verified["evidence_record_id"] == record["id"]

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert gate["external_dependencies_ready"] is True
    assert gate["blockers"] == []
    # External evidence readiness never self-enables a sovereign production rail.
    assert gate["production_enabled"] is False

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"] == 0
    assert audit.verify_audit_chain()[0] is True


def test_unknown_profile_dependency_and_unapproved_status_fail_closed(tmp_path):
    setup_env(tmp_path)
    with pytest.raises(sovereign.SovereignError, match="country profile"):
        sovereign.country_profile_gate("unknown-country")
    with pytest.raises(sovereign.SovereignError, match="dependency"):
        sovereign.set_country_profile_dependency(
            "zimbabwe-2026",
            "invented_switch_api",
            "reference",
            evidence_ref="x",
            actor="operator",
            authorization_decision_id="authz-x",
        )
    with pytest.raises(sovereign.SovereignError, match="status"):
        sovereign.set_country_profile_dependency(
            "zimbabwe-2026",
            "national_switch_message_interface",
            "approved",
            evidence_ref="x",
            actor="operator",
            authorization_decision_id="authz-x",
        )


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return object()


def test_postgres_country_dependency_lookup_takes_profile_dependency_lock_first():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)
    query = "SELECT * FROM country_profile_dependencies WHERE profile_key=? AND dependency_key=?"

    conn.execute(query, ("zimbabwe-2026", "emvco_conformance"))

    assert raw.calls[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("zimbabwe-2026:emvco_conformance",),
    )
    assert raw.calls[1] == (
        "SELECT * FROM country_profile_dependencies WHERE profile_key=%s AND dependency_key=%s",
        ("zimbabwe-2026", "emvco_conformance"),
    )
