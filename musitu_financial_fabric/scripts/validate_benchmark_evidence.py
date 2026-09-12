from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "benchmark-evidence-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
EVIDENCE_SCHEMA = "mff.runtime-benchmark-evidence.v1"
POLICY_SCHEMA = "mff.benchmark-evidence-policy.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_BINDINGS = (
    "runtime_key",
    "authoritative_runtime_base_commit",
    "image_digest",
    "manifest_path",
    "resource_profile",
    "environment_id",
    "executed_at",
    "measurement_toolchain",
    "raw_evidence_ref",
    "raw_evidence_sha256",
)
REQUIRED_LOAD_MODEL = (
    "request_or_message_rate",
    "concurrency",
    "payload_size_distribution",
    "read_write_mix",
    "dataset_or_state_size",
    "test_duration",
    "failure_or_restart_scenario",
)
REQUIRED_MEASUREMENTS = (
    "cpu_p50",
    "cpu_p95",
    "memory_rss_p50",
    "memory_rss_p95",
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "error_rate",
    "restart_recovery_time",
    "queue_or_backlog_depth_where_applicable",
    "storage_iops_and_latency_where_applicable",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_file(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute():
        return None
    root = ROOT.resolve()
    resolved = (ROOT / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _policy_errors() -> list[str]:
    errors: list[str] = []
    try:
        policy = _load(POLICY)
    except Exception as exc:
        return [f"benchmark policy unavailable or invalid JSON: {type(exc).__name__}"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("benchmark policy schema version is invalid")
    if policy.get("benchmark_evidence_schema_version") != EVIDENCE_SCHEMA:
        errors.append("benchmark evidence schema version does not match policy")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("benchmark policy is not bound to the sealed runtime release")
    if policy.get("required_bindings") != list(REQUIRED_BINDINGS):
        errors.append("benchmark policy required bindings do not exactly match validator policy")
    return errors


def evidence_errors(key: str, row: dict[str, Any], payload: object) -> list[str]:
    errors = _policy_errors()
    if not isinstance(payload, dict):
        return errors + ["benchmark evidence root must be an object"]
    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        errors.append("benchmark evidence schema version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("evidence is not bound to the sealed runtime release")

    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks an immutable image digest")
    elif payload.get("image_digest") != digest:
        errors.append("image_digest does not match contract row")
    if payload.get("manifest_path") != row.get("manifest_path"):
        errors.append("manifest_path does not match contract row")
    if payload.get("resource_profile") != row.get("resource_profile"):
        errors.append("resource_profile does not match contract row")
    if not isinstance(payload.get("environment_id"), str) or not payload["environment_id"].strip():
        errors.append("environment_id is missing")

    try:
        executed = datetime.fromisoformat(str(payload.get("executed_at", "")).replace("Z", "+00:00"))
        if executed.tzinfo is None:
            raise ValueError("timezone missing")
    except (TypeError, ValueError):
        errors.append("executed_at must be an offset-aware ISO-8601 timestamp")

    toolchain = payload.get("measurement_toolchain")
    if not isinstance(toolchain, dict) or not toolchain or any(not str(k).strip() or not str(v).strip() for k, v in toolchain.items()):
        errors.append("measurement_toolchain must be a non-empty mapping")

    raw_path = _repo_file(payload.get("raw_evidence_ref"))
    if raw_path is None:
        errors.append("raw_evidence_ref is not an existing repository-relative file")
    raw_sha = str(payload.get("raw_evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(raw_sha):
        errors.append("raw_evidence_sha256 is missing or malformed")
    elif raw_path is not None:
        actual = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if actual != raw_sha:
            errors.append("raw_evidence_sha256 does not match raw_evidence_ref bytes")

    load_model = payload.get("load_model")
    if not isinstance(load_model, dict):
        errors.append("load_model must be an object")
    else:
        for field in REQUIRED_LOAD_MODEL:
            if not _nonempty(load_model.get(field)):
                errors.append(f"load_model missing {field}")

    measurements = payload.get("measurements")
    if not isinstance(measurements, dict):
        errors.append("measurements must be an object")
    else:
        for field in REQUIRED_MEASUREMENTS:
            if not _nonempty(measurements.get(field)):
                errors.append(f"measurements missing {field}")
    return errors


def _self_test() -> list[str]:
    raw = ROOT / ".mff-benchmark-raw-self-test.tmp"
    raw.write_bytes(b"MUSITU benchmark raw evidence self-test\n")
    try:
        raw_ref = raw.relative_to(ROOT).as_posix()
        digest = "sha256:" + ("1" * 64)
        row = {
            "image_digest": digest,
            "manifest_path": "deploy/example.json",
            "resource_profile": "deploy/resource-profile.json",
        }
        payload: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA,
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "manifest_path": row["manifest_path"],
            "resource_profile": row["resource_profile"],
            "environment_id": "self-test-target",
            "executed_at": "2026-09-12T00:00:00+00:00",
            "measurement_toolchain": {"driver": "validator-self-test", "version": "1"},
            "raw_evidence_ref": raw_ref,
            "raw_evidence_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "load_model": {field: "self-test" for field in REQUIRED_LOAD_MODEL},
            "measurements": {field: "self-test" for field in REQUIRED_MEASUREMENTS},
        }
        errors = evidence_errors("self-test", row, payload)
        if errors:
            return [f"valid synthetic evidence rejected: {errors}"]

        failures: list[str] = []
        mutations: list[tuple[str, object]] = [
            ("runtime_key", "wrong-runtime"),
            ("authoritative_runtime_base_commit", "0" * 40),
            ("image_digest", "sha256:" + ("3" * 64)),
            ("executed_at", "2026-09-12T00:00:00"),
            ("raw_evidence_ref", "missing/raw-evidence.json"),
            ("raw_evidence_sha256", "4" * 64),
        ]
        for field, value in mutations:
            candidate = json.loads(json.dumps(payload))
            candidate[field] = value
            if not evidence_errors("self-test", row, candidate):
                failures.append(f"self-test failed to reject {field} drift")
        missing_load = json.loads(json.dumps(payload))
        del missing_load["load_model"][REQUIRED_LOAD_MODEL[0]]
        if not evidence_errors("self-test", row, missing_load):
            failures.append("self-test failed to reject incomplete load model")
        missing_measurement = json.loads(json.dumps(payload))
        del missing_measurement["measurements"][REQUIRED_MEASUREMENTS[0]]
        if not evidence_errors("self-test", row, missing_measurement):
            failures.append("self-test failed to reject incomplete measurement set")
        return failures
    finally:
        raw.unlink(missing_ok=True)


def _contract_errors() -> list[str]:
    errors = _policy_errors()
    contract = _load(CONTRACT)
    measured = 0
    for row in contract.get("runtimes", []):
        if not isinstance(row, dict) or row.get("benchmark_status", "unmeasured") != "measured":
            continue
        measured += 1
        key = str(row.get("key", "unknown"))
        evidence_path = _repo_file(row.get("benchmark_evidence_ref"))
        if evidence_path is None:
            errors.append(f"{key}: measured benchmark lacks an existing benchmark_evidence_ref")
            continue
        try:
            payload = _load(evidence_path)
        except Exception as exc:
            errors.append(f"{key}: benchmark evidence is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        errors.extend(f"{key}: {error}" for error in evidence_errors(key, row, payload))
    if not errors:
        print(f"PASS: raw benchmark evidence integrity gate validated {measured} measured runtime evidence rows")
        if measured == 0:
            print("BOUNDARY: no runtime currently claims measured benchmark status")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate byte-bound benchmark evidence for provider-neutral target staging.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    errors = _self_test() if args.self_test else _contract_errors()
    if errors:
        for error in errors:
            print(f"BENCHMARK EVIDENCE BLOCKER: {error}")
        return 5
    if args.self_test:
        print("PASS: raw benchmark evidence self-test accepts exact bytes and rejects missing/mismatched evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
