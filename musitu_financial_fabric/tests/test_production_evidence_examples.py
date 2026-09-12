from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTROL_ROOT = _REPO_ROOT / "control" / "musitu-financial-fabric"

_AUTHORIZATION_KEYS = {
    "regulator",
    "sponsor_bank",
    "data_protection",
    "independent_security",
    "rail_provider",
}
_DEPLOYMENT_KEYS = {
    "dark_deployment",
    "required_runtime_health",
    "monitoring_alerting",
    "postgres_backup_restore",
    "tigerbeetle_recovery",
    "provider_reconciliation",
    "activation_rollback_drill",
}
_KILL_KEYS = {"network", "provider", "settlement"}


def _load(name: str) -> dict:
    return json.loads((_CONTROL_ROOT / name).read_text(encoding="utf-8"))


def test_production_authorization_example_requires_row_byte_pins() -> None:
    example = _load("production-authorization-manifest.example.json")
    evidence = example["evidence"]
    assert set(evidence) == _AUTHORIZATION_KEYS
    for row in evidence.values():
        assert {"status", "evidence_ref", "evidence_sha256"} <= set(row)
        assert row["status"] == "pending"
        assert row["evidence_ref"] == ""
        assert row["evidence_sha256"] == ""


def test_production_deployment_example_requires_row_byte_pins() -> None:
    example = _load("production-deployment-evidence-manifest.example.json")
    evidence = example["evidence"]
    assert set(evidence) == _DEPLOYMENT_KEYS
    for row in evidence.values():
        assert {"status", "evidence_ref", "evidence_sha256"} <= set(row)
        assert row["status"] == "pending"
        assert row["evidence_ref"] == ""
        assert row["evidence_sha256"] == ""

    kill_controls = example["independent_kill_controls"]
    assert set(kill_controls) == _KILL_KEYS
    for row in kill_controls.values():
        assert {"status", "independent_of_application", "evidence_ref", "evidence_sha256"} <= set(row)
        assert row["status"] == "pending"
        assert row["independent_of_application"] is False
        assert row["evidence_ref"] == ""
        assert row["evidence_sha256"] == ""
