from __future__ import annotations

import importlib

from app.config import Settings


def setup_modules(tmp_path):
    import app.db as db
    import app.audit as audit
    import app.sovereign as sovereign
    import app.sovereign_public_evidence as public_evidence

    cfg = Settings(db_path=str(tmp_path / "public-evidence.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    importlib.reload(public_evidence)
    db.init_db()
    return sovereign, public_evidence


def test_zimbabwe_public_evidence_sets_reference_status_without_clearing_blockers(tmp_path):
    sovereign, public_evidence = setup_modules(tmp_path)

    applied = public_evidence.apply_zimbabwe_public_reference_evidence(
        actor="public-evidence-audit",
        authorization_decision_id="reference-only-20261007",
    )

    assert len(applied) == 5
    gate = sovereign.country_profile_gate("zimbabwe-2026")
    assert set(gate["blockers"]) == set(public_evidence.ZIMBABWE_PUBLIC_EVIDENCE)
    assert gate["external_dependencies_ready"] is False
    assert gate["production_enabled"] is False
    for key, item in gate["dependencies"].items():
        assert item["status"] == "reference"
        assert item["evidence_ref"]


def test_zimbabwe_public_evidence_is_idempotent_and_uses_official_sources(tmp_path):
    sovereign, public_evidence = setup_modules(tmp_path)

    first = public_evidence.apply_zimbabwe_public_reference_evidence(
        actor="public-evidence-audit",
        authorization_decision_id="reference-only-20261007",
    )
    second = public_evidence.apply_zimbabwe_public_reference_evidence(
        actor="public-evidence-audit",
        authorization_decision_id="reference-only-20261007",
    )

    assert first == second
    for key, evidence in public_evidence.ZIMBABWE_PUBLIC_EVIDENCE.items():
        assert evidence["source_url"].startswith(
            ("https://www.rbz.co.zw/", "https://zimswitch.co.zw/")
        )
        assert evidence["status"] == "reference"
        assert evidence["limitation"]
