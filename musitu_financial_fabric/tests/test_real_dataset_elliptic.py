from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def write_elliptic_fixture(root: Path, *, broken_edge: bool = False) -> Path:
    data = root / "elliptic_bitcoin_dataset"
    data.mkdir()
    (data / "elliptic_txs_features.csv").write_text(
        "1001,1,0.1,0.2\n"
        "1002,1,0.3,0.4\n"
        "1003,2,0.5,0.6\n"
        "1004,2,0.7,0.8\n",
        encoding="utf-8",
    )
    (data / "elliptic_txs_classes.csv").write_text(
        "txId,class\n"
        "1001,1\n"
        "1002,2\n"
        "1003,unknown\n"
        "1004,2\n",
        encoding="utf-8",
    )
    endpoint = "9999" if broken_edge else "1004"
    (data / "elliptic_txs_edgelist.csv").write_text(
        "txId1,txId2\n"
        "1001,1002\n"
        "1002,1003\n"
        f"1003,{endpoint}\n",
        encoding="utf-8",
    )
    return root


def setup_modules(tmp_path):
    import app.db as db
    import app.audit as audit
    import app.sovereign as sovereign
    import app.real_dataset_evidence as evidence

    cfg = Settings(db_path=str(tmp_path / "elliptic.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    evidence.settings = cfg
    db.init_db()
    return db, evidence


def test_scan_elliptic_real_graph_counts_labels_edges_and_time_steps(tmp_path):
    _, evidence = setup_modules(tmp_path)
    root = write_elliptic_fixture(tmp_path / "raw")

    report = evidence.scan_elliptic_dataset(root)

    assert report["graph"]["node_count"] == 4
    assert report["graph"]["edge_count"] == 3
    assert report["graph"]["missing_edge_endpoint_count"] == 0
    assert report["labels"] == {"illicit": 1, "licit": 2, "unknown": 1}
    assert report["time_steps"]["min"] == 1
    assert report["time_steps"]["max"] == 2
    assert report["validation"]["graph_integrity"] is True
    assert report["validation"]["monetary_values_used"] is False
    assert len(report["dataset_fingerprint_sha256"]) == 64


def test_scan_elliptic_rejects_edge_to_unknown_transaction(tmp_path):
    _, evidence = setup_modules(tmp_path)
    root = write_elliptic_fixture(tmp_path / "raw", broken_edge=True)

    with pytest.raises(evidence.EvidenceError, match="edge endpoint"):
        evidence.scan_elliptic_dataset(root)


def test_replay_elliptic_illicit_labels_into_reference_disputes_only(tmp_path):
    db, evidence = setup_modules(tmp_path)
    root = write_elliptic_fixture(tmp_path / "raw")

    result = evidence.replay_elliptic_illicit_exceptions(root)

    assert result["transactions_scanned"] == 4
    assert result["illicit_labels_observed"] == 1
    assert result["reference_disputes_created"] == 1
    assert result["idempotency"]["identical_replay_same_id"] is True
    assert result["idempotency"]["conflicting_replay_failed_closed"] is True
    assert result["audit"]["valid"] is True
    assert result["side_effects"]["payment_intents"] == 0
    assert result["side_effects"]["ledger_postings"] == 0
    assert result["monetary_values_used"] is False
    assert result["fraud_accuracy_evaluated"] is False
    assert result["live_funds_moved"] is False

    with db.connect() as conn:
        assert int(conn.execute("SELECT COUNT(*) AS n FROM scheme_exceptions").fetchone()["n"]) == 1
