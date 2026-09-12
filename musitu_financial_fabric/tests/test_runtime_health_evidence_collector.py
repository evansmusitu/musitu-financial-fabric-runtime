from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_runtime_health_evidence.py"
spec = importlib.util.spec_from_file_location("runtime_health_collector", SCRIPT)
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(collector)

COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
TARGET = "prod-zimbabwe-primary-01"
TEST_COMPONENTS = (
    SimpleNamespace(key="postgres", required=True, kind="runtime"),
    SimpleNamespace(key="tigerbeetle", required=True, kind="runtime"),
    SimpleNamespace(key="protocol", required=True, kind="protocol"),
)


def _healthy_rows():
    return [
        {"key": "postgres", "name": "PostgreSQL", "required": True, "state": "healthy", "status_code": 200, "kind": "runtime"},
        {"key": "tigerbeetle", "name": "TigerBeetle", "required": True, "state": "healthy", "status_code": 204, "kind": "runtime"},
        {"key": "protocol", "name": "Protocol", "required": True, "state": "declared", "kind": "protocol"},
    ]


def test_build_evidence_passes_only_exact_healthy_runtime_inventory():
    evidence = collector.build_evidence(
        target_environment_id=TARGET,
        commit_sha=COMMIT,
        image_digest=IMAGE,
        probe_result={"all_required_runtime_healthy": True, "components": _healthy_rows()},
        observed_at=datetime(2026, 9, 12, 7, 0, tzinfo=timezone.utc),
        components=TEST_COMPONENTS,
    )
    assert evidence["result"]["status"] == "passed"
    assert evidence["result"]["all_required_runtime_healthy"] is True
    assert evidence["result"]["expected_required_runtime_count"] == 2
    assert evidence["result"]["missing_required_runtime_keys"] == []
    assert evidence["target_environment_id"] == TARGET
    assert evidence["release"] == {"commit_sha": COMMIT, "image_digest": IMAGE}


def test_missing_required_runtime_fails_even_if_probe_summary_claims_healthy():
    rows = _healthy_rows()
    rows = [row for row in rows if row["key"] != "tigerbeetle"]
    evidence = collector.build_evidence(
        target_environment_id=TARGET,
        commit_sha=COMMIT,
        image_digest=IMAGE,
        probe_result={"all_required_runtime_healthy": True, "components": rows},
        components=TEST_COMPONENTS,
    )
    assert evidence["result"]["status"] == "failed"
    assert evidence["result"]["missing_required_runtime_keys"] == ["tigerbeetle"]


def test_unhealthy_required_runtime_fails_closed():
    rows = _healthy_rows()
    rows[0] = {**rows[0], "state": "unreachable", "error": "ConnectError"}
    evidence = collector.build_evidence(
        target_environment_id=TARGET,
        commit_sha=COMMIT,
        image_digest=IMAGE,
        probe_result={"all_required_runtime_healthy": False, "components": rows},
        components=TEST_COMPONENTS,
    )
    assert evidence["result"]["status"] == "failed"
    assert evidence["result"]["all_required_runtime_healthy"] is False


def test_duplicate_required_runtime_fails_closed():
    rows = _healthy_rows() + [_healthy_rows()[0]]
    evidence = collector.build_evidence(
        target_environment_id=TARGET,
        commit_sha=COMMIT,
        image_digest=IMAGE,
        probe_result={"all_required_runtime_healthy": True, "components": rows},
        components=TEST_COMPONENTS,
    )
    assert evidence["result"]["status"] == "failed"
    assert evidence["result"]["duplicate_required_runtime_keys"] == ["postgres"]


@pytest.mark.parametrize(
    ("target", "commit", "image"),
    [
        ("", COMMIT, IMAGE),
        (TARGET, "abc", IMAGE),
        (TARGET, COMMIT, "sha256:abc"),
    ],
)
def test_identity_inputs_are_strict(target, commit, image):
    with pytest.raises(ValueError):
        collector.build_evidence(
            target_environment_id=target,
            commit_sha=commit,
            image_digest=image,
            probe_result={"all_required_runtime_healthy": True, "components": _healthy_rows()},
            components=TEST_COMPONENTS,
        )


def test_persist_evidence_hash_and_fragment_are_consistent(tmp_path):
    evidence = collector.build_evidence(
        target_environment_id=TARGET,
        commit_sha=COMMIT,
        image_digest=IMAGE,
        probe_result={"all_required_runtime_healthy": True, "components": _healthy_rows()},
        observed_at=datetime(2026, 9, 12, 7, 0, tzinfo=timezone.utc),
        components=TEST_COMPONENTS,
    )
    output = tmp_path / "health.json"
    digest, sha_path, fragment_path = collector.persist_evidence(output, evidence)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert sha_path.read_text() == f"{digest}  health.json\n"
    fragment = json.loads(fragment_path.read_text())
    assert fragment["required_runtime_health"]["status"] == "passed"
    assert fragment["required_runtime_health"]["evidence_ref"] == f"sha256:{digest}"
