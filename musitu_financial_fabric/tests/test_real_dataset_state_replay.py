from __future__ import annotations

import importlib

from app.config import Settings


ARFF = """@relation credit-card-fraud-detection
@attribute Time numeric
@attribute V1 numeric
@attribute Amount numeric
@attribute Class numeric
@data
0,0.1,10.00,0
1,0.2,20.00,1
2,0.3,0.00,0
3,0.4,5.50,0
"""


def setup_modules(tmp_path):
    import app.db as db
    import app.audit as audit
    import app.sovereign as sovereign
    import app.real_dataset_evidence as evidence

    cfg = Settings(db_path=str(tmp_path / "replay.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    evidence.settings = cfg
    db.init_db()
    return db, audit, sovereign, evidence


def test_real_dataset_state_replay_exercises_clearing_disputes_and_no_fund_side_effects(tmp_path):
    db, audit, _, evidence = setup_modules(tmp_path)
    path = tmp_path / "ulb.arff"
    path.write_text(ARFF, encoding="utf-8")

    result = evidence.replay_ulb_state(path)

    assert result["source_rows_processed"] == 4
    assert result["obligations_recorded"] == 3
    assert result["zero_amount_rows_skipped"] == 1
    assert result["fraud_labels_observed"] == 1
    assert result["reference_disputes_created"] == 1
    assert result["idempotency"]["identical_replay_same_id"] is True
    assert result["idempotency"]["conflicting_replay_failed_closed"] is True
    assert result["net_positions"]["balanced"] is True
    assert result["net_positions"]["obligation_count"] == 3
    assert result["audit"]["valid"] is True
    assert result["side_effects"]["payment_intents"] == 0
    assert result["side_effects"]["ledger_postings"] == 0
    assert result["live_funds_moved"] is False
    assert result["production_authorized"] is False

    with db.connect() as conn:
        assert int(conn.execute("SELECT COUNT(*) AS n FROM scheme_exceptions").fetchone()["n"]) == 1


def test_real_dataset_state_replay_limit_is_source_row_limit(tmp_path):
    _, _, _, evidence = setup_modules(tmp_path)
    path = tmp_path / "ulb.arff"
    path.write_text(ARFF, encoding="utf-8")

    result = evidence.replay_ulb_state(path, limit=2)

    assert result["source_rows_processed"] == 2
    assert result["obligations_recorded"] == 2
    assert result["fraud_labels_observed"] == 1
