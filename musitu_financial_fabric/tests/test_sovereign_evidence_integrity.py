from __future__ import annotations

import importlib

import pytest

from app.config import Settings


def setup_modules(tmp_path):
    import app.db as db
    import app.audit as audit
    import app.sovereign as sovereign
    import app.sovereign_evidence as evidence

    cfg = Settings(db_path=str(tmp_path / "evidence-integrity.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    importlib.reload(evidence)
    db.init_db()
    return db, audit, sovereign, evidence


def sample_registration(evidence, *, evidence_ref="operator:zimswitch:spec-v1", sha="a" * 64):
    return evidence.register_country_profile_evidence(
        "zimbabwe-2026",
        "national_switch_message_interface",
        evidence_ref=evidence_ref,
        source_authority="Zimswitch Technologies",
        source_version="v1",
        source_location="operator-secure-room/spec-v1.pdf",
        source_sha256=sha,
        actor="evidence-intake",
    )


def test_external_evidence_registration_is_hash_bound_and_idempotent(tmp_path):
    _, audit, _, evidence = setup_modules(tmp_path)

    first = sample_registration(evidence)
    second = sample_registration(evidence)

    assert first == second
    assert first["status"] == "registered"
    assert first["source_sha256"] == "a" * 64
    assert first["source_authority"] == "Zimswitch Technologies"
    assert audit.verify_audit_chain()[0] is True

    with pytest.raises(evidence.SovereignEvidenceError, match="sha-256"):
        sample_registration(evidence, evidence_ref="operator:bad-hash", sha="not-a-hash")


def test_conflicting_reuse_of_evidence_reference_fails_closed(tmp_path):
    _, _, _, evidence = setup_modules(tmp_path)
    sample_registration(evidence)

    with pytest.raises(evidence.SovereignEvidenceError, match="conflicting"):
        sample_registration(evidence, sha="b" * 64)


def test_unverified_evidence_cannot_clear_country_dependency(tmp_path):
    _, _, sovereign, evidence = setup_modules(tmp_path)
    record = sample_registration(evidence)

    with pytest.raises(evidence.SovereignEvidenceError, match="externally verified"):
        evidence.promote_country_profile_dependency_from_evidence(
            "zimbabwe-2026",
            "national_switch_message_interface",
            record["id"],
            actor="operator-intake",
            authorization_decision_id="promote-1",
        )

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert "national_switch_message_interface" in gate["blockers"]


def test_verified_evidence_can_promote_only_its_matching_dependency(tmp_path):
    _, audit, sovereign, evidence = setup_modules(tmp_path)
    record = sample_registration(evidence)

    verified = evidence.verify_country_profile_evidence(
        record["id"],
        actor="evidence-reviewer",
        authorization_decision_id="verify-1",
    )
    assert verified["status"] == "externally_verified"

    with pytest.raises(evidence.SovereignEvidenceError, match="dependency"):
        evidence.promote_country_profile_dependency_from_evidence(
            "zimbabwe-2026",
            "authoritative_mai_allocation",
            record["id"],
            actor="operator-intake",
            authorization_decision_id="promote-wrong",
        )

    promoted = evidence.promote_country_profile_dependency_from_evidence(
        "zimbabwe-2026",
        "national_switch_message_interface",
        record["id"],
        actor="operator-intake",
        authorization_decision_id="promote-1",
    )
    assert promoted["status"] == "externally_verified"
    assert promoted["evidence_record_id"] == record["id"]
    assert promoted["source_sha256"] == "a" * 64

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    item = gate["dependencies"]["national_switch_message_interface"]
    assert item["status"] == "externally_verified"
    assert item["evidence_ref"].startswith("evidence-record:")
    assert item["evidence_record_id"] == record["id"]
    assert item["source_sha256"] == "a" * 64
    assert audit.verify_audit_chain()[0] is True


def test_revoked_evidence_cannot_be_reused_for_promotion(tmp_path):
    _, _, sovereign, evidence = setup_modules(tmp_path)
    record = sample_registration(evidence)
    evidence.verify_country_profile_evidence(
        record["id"],
        actor="evidence-reviewer",
        authorization_decision_id="verify-1",
    )
    evidence.revoke_country_profile_evidence(
        record["id"],
        actor="evidence-reviewer",
        authorization_decision_id="revoke-1",
        reason="superseded",
    )

    with pytest.raises(evidence.SovereignEvidenceError, match="externally verified"):
        evidence.promote_country_profile_dependency_from_evidence(
            "zimbabwe-2026",
            "national_switch_message_interface",
            record["id"],
            actor="operator-intake",
            authorization_decision_id="promote-after-revoke",
        )

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert "national_switch_message_interface" in gate["blockers"]


def test_evidence_table_exists_in_both_metadata_schemas():
    from app.db import POSTGRES_SCHEMA, SQLITE_SCHEMA

    needle = "CREATE TABLE IF NOT EXISTS country_profile_evidence_records "
    assert SQLITE_SCHEMA.count(needle) == 1
    assert POSTGRES_SCHEMA.count(needle) == 1


def test_free_form_external_verification_cannot_bypass_evidence_ledger(tmp_path):
    _, _, sovereign, _ = setup_modules(tmp_path)

    with pytest.raises(sovereign.SovereignError, match="evidence record"):
        sovereign.set_country_profile_dependency(
            "zimbabwe-2026",
            "national_switch_message_interface",
            "externally_verified",
            evidence_ref="free-form-operator-claim",
            actor="operator",
            authorization_decision_id="legacy-bypass",
        )

    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert "national_switch_message_interface" in gate["blockers"]
