from __future__ import annotations

from app import audit, db, sovereign
from app.config import Settings
from app.sovereign_uat import run_reference_uat


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "reference-uat.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def test_reference_uat_composes_sovereign_controls_without_moving_funds(tmp_path):
    setup_env(tmp_path)

    result = run_reference_uat("rbz-evaluation")

    assert result["scenario"] == "rbz-evaluation"
    assert result["payer"]["certification_status"] == "approved"
    assert result["payee"]["certification_status"] == "approved"
    assert result["request_to_pay"]["status"] == "accepted"
    assert result["switch"]["instruction"]["amount_minor"] == 1250
    assert result["switch"]["submission_status"] == "blocked_unconfigured"
    assert result["clearing"]["balanced"] is True
    assert result["clearing"]["sum_minor"] == 0
    assert result["clearing"]["external_settlement_verified"] is False
    assert result["exception"]["status"] == "accepted"
    assert result["country_gate"]["profile_key"] == "zimbabwe-2026"
    assert result["country_gate"]["production_enabled"] is False
    assert result["country_gate"]["external_dependencies_ready"] is False
    assert result["country_gate"]["blockers"]
    assert result["audit"]["valid"] is True
    assert result["side_effects"]["payment_intents"] == 0
    assert result["side_effects"]["ledger_postings"] == 0
    assert result["live_funds_moved"] is False
    assert result["production_authorized"] is False
