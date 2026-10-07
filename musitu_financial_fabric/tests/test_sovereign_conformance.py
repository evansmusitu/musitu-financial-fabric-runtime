from __future__ import annotations

import pytest

from app import audit, db, sovereign
from app.config import Settings
from app.sovereign_conformance import (
    GENERIC_ADAPTER_BEHAVIORS,
    build_regulator_evaluation_pack,
    evaluate_country_adapter_manifest,
)
from app.sovereign_uat import run_reference_uat


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "conformance.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def _complete_manifest():
    return {
        "authority": "external-authority-reference",
        "interface_version": "reference-v1",
        "source_evidence_ref": "external-spec-evidence-001",
        "behaviors": {
            key: {"supported": True, "mapping_ref": f"mapping:{key}"}
            for key in GENERIC_ADAPTER_BEHAVIORS
        },
    }


def test_reference_manifest_fails_closed_until_internal_and_external_requirements_are_met(tmp_path):
    setup_env(tmp_path)

    manifest = {
        "authority": "reference-only",
        "interface_version": "draft",
        "source_evidence_ref": "draft-spec",
        "behaviors": {},
    }
    result = evaluate_country_adapter_manifest("zimbabwe-2026", manifest)

    assert result["structurally_valid"] is True
    assert set(result["missing_behaviors"]) == set(GENERIC_ADAPTER_BEHAVIORS)
    assert result["country_external_dependencies_ready"] is False
    assert result["country_blockers"]
    assert result["adapter_ready"] is False
    assert result["production_enabled"] is False
    assert result["regulatory_authorized"] is False


def test_supported_behavior_requires_mapping_evidence(tmp_path):
    setup_env(tmp_path)
    manifest = _complete_manifest()
    first = GENERIC_ADAPTER_BEHAVIORS[0]
    manifest["behaviors"][first] = {"supported": True, "mapping_ref": ""}

    with pytest.raises(ValueError, match="mapping"):
        evaluate_country_adapter_manifest("zimbabwe-2026", manifest)


def test_complete_manifest_plus_external_evidence_is_adapter_ready_but_not_production_authorized(tmp_path):
    setup_env(tmp_path)
    for index, key in enumerate(sovereign.country_profile_gate("zimbabwe-2026")["dependencies"]):
        sovereign.set_country_profile_dependency(
            "zimbabwe-2026",
            key,
            "externally_verified",
            evidence_ref=f"external-evidence-{index}",
            actor="operator",
            authorization_decision_id=f"authz-{index}",
        )

    result = evaluate_country_adapter_manifest("zimbabwe-2026", _complete_manifest())

    assert result["structurally_valid"] is True
    assert result["missing_behaviors"] == []
    assert result["country_external_dependencies_ready"] is True
    assert result["adapter_ready"] is True
    assert result["production_enabled"] is False
    assert result["regulatory_authorized"] is False


def test_regulator_evaluation_pack_preserves_claim_boundaries_and_no_fund_movement(tmp_path):
    setup_env(tmp_path)
    uat = run_reference_uat("phase4-evaluation")
    pack = build_regulator_evaluation_pack("zimbabwe-2026", _complete_manifest(), uat)

    assert pack["profile_key"] == "zimbabwe-2026"
    assert pack["uat"]["live_funds_moved"] is False
    assert pack["uat"]["production_authorized"] is False
    assert pack["adapter_conformance"]["production_enabled"] is False
    assert pack["adapter_conformance"]["regulatory_authorized"] is False
    assert pack["claim_boundaries"]["rbz_approved"] is False
    assert pack["claim_boundaries"]["zimswitch_authorized"] is False
    assert pack["claim_boundaries"]["emvco_certified"] is False
    assert pack["claim_boundaries"]["nipl_superiority_proven"] is False
    assert pack["production_authorized"] is False
