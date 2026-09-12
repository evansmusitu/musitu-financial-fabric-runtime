from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "musitu_financial_fabric" / "stack" / "required-components.json"
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
NAMESPACE = TARGET / "foundation" / "namespace.json"
NETWORK = TARGET / "foundation" / "default-deny-network-policy.json"
QUOTA = TARGET / "foundation" / "no-workloads-quota.json"
KUSTOMIZATION = TARGET / "kustomization.yaml"
BENCHMARK = TARGET / "resource-benchmark-plan.json"

OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_COUNT = 26
EXPECTED_NAMESPACE = "musitu-financial-fabric-target-staging"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
BENCHMARK_EVIDENCE_SCHEMA = "mff.runtime-benchmark-evidence.v1"
EXPECTED_KUSTOMIZATION = (
    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
    "kind: Kustomization\n"
    "resources:\n"
    "  - foundation/namespace.json\n"
    "  - foundation/default-deny-network-policy.json\n"
    "  - foundation/no-workloads-quota.json\n"
)
DEPLOYMENT_FIELDS = (
    "manifest_path",
    "image_digest",
    "provenance_ref",
    "resource_profile",
    "probe_profile",
    "network_profile",
    "workload_identity_profile",
    "secret_profile",
    "persistence_profile",
    "backup_restore_profile",
    "disruption_budget_profile",
    "anti_affinity_profile",
    "benchmark_evidence_ref",
)
REFERENCE_FIELDS = tuple(field for field in DEPLOYMENT_FIELDS if field != "image_digest")
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
REQUIRED_EVIDENCE_BINDINGS = (
    "runtime_key",
    "authoritative_runtime_base_commit",
    "image_digest",
    "manifest_path",
    "resource_profile",
    "environment_id",
    "executed_at",
    "measurement_toolchain",
    "raw_evidence_sha256",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_runtime_map() -> dict[str, str]:
    stack = _load(STACK)
    rows = [row for row in stack.get("components", []) if row.get("required") is True and row.get("kind") == "runtime"]
    mapping = {str(row.get("key")): str(row.get("health_env")) for row in rows}
    if len(rows) != EXPECTED_COUNT or len(mapping) != EXPECTED_COUNT:
        raise AssertionError(f"authoritative required-runtime boundary is not exactly {EXPECTED_COUNT}")
    if any(not key or not env or env == "None" for key, env in mapping.items()):
        raise AssertionError("required runtime inventory has an empty key or health_env")
    return mapping


def _repo_file_reference(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    relative = Path(value.strip())
    if relative.is_absolute():
        return False
    root = ROOT.resolve()
    resolved = (ROOT / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return resolved.is_file()


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _benchmark_payload_errors(key: str, row: dict[str, Any], payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["benchmark evidence root must be an object"]
    if payload.get("schema_version") != BENCHMARK_EVIDENCE_SCHEMA:
        errors.append("benchmark evidence schema version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("benchmark evidence runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("benchmark evidence is not bound to the sealed runtime release")
    image_digest = row.get("image_digest")
    if not isinstance(image_digest, str) or not OCI_DIGEST.fullmatch(image_digest):
        errors.append("contract row lacks a valid immutable image digest for benchmark binding")
    elif payload.get("image_digest") != image_digest:
        errors.append("benchmark evidence image_digest does not match contract row")
    if payload.get("manifest_path") != row.get("manifest_path"):
        errors.append("benchmark evidence manifest_path does not match contract row")
    if payload.get("resource_profile") != row.get("resource_profile"):
        errors.append("benchmark evidence resource_profile does not match contract row")
    if not isinstance(payload.get("environment_id"), str) or not payload["environment_id"].strip():
        errors.append("benchmark evidence environment_id is missing")
    executed_at = payload.get("executed_at")
    try:
        parsed = datetime.fromisoformat(str(executed_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except (TypeError, ValueError):
        errors.append("benchmark evidence executed_at must be an offset-aware ISO-8601 timestamp")
    toolchain = payload.get("measurement_toolchain")
    if not isinstance(toolchain, dict) or not toolchain or any(not str(k).strip() or not str(v).strip() for k, v in toolchain.items()):
        errors.append("benchmark evidence measurement_toolchain must be a non-empty mapping")
    raw_sha = str(payload.get("raw_evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(raw_sha):
        errors.append("benchmark evidence raw_evidence_sha256 is missing or malformed")
    load_model = payload.get("load_model")
    if not isinstance(load_model, dict):
        errors.append("benchmark evidence load_model must be an object")
    else:
        for field in REQUIRED_LOAD_MODEL:
            if not _nonempty(load_model.get(field)):
                errors.append(f"benchmark evidence load_model missing {field}")
    measurements = payload.get("measurements")
    if not isinstance(measurements, dict):
        errors.append("benchmark evidence measurements must be an object")
    else:
        for field in REQUIRED_MEASUREMENTS:
            if not _nonempty(measurements.get(field)):
                errors.append(f"benchmark evidence measurements missing {field}")
    return errors


def _benchmark_self_test() -> list[str]:
    digest = "sha256:" + ("1" * 64)
    row = {
        "image_digest": digest,
        "manifest_path": "deploy/example.json",
        "resource_profile": "deploy/resource-profile.json",
    }
    payload: dict[str, Any] = {
        "schema_version": BENCHMARK_EVIDENCE_SCHEMA,
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "manifest_path": row["manifest_path"],
        "resource_profile": row["resource_profile"],
        "environment_id": "self-test-target",
        "executed_at": "2026-09-12T00:00:00+00:00",
        "measurement_toolchain": {"driver": "validator-self-test", "version": "1"},
        "raw_evidence_sha256": "2" * 64,
        "load_model": {field: "self-test" for field in REQUIRED_LOAD_MODEL},
        "measurements": {field: "self-test" for field in REQUIRED_MEASUREMENTS},
    }
    errors = _benchmark_payload_errors("self-test", row, payload)
    if errors:
        return [f"valid synthetic benchmark evidence rejected: {errors}"]
    mutations: list[tuple[str, str, object]] = [
        ("runtime_key", "runtime_key", "wrong-runtime"),
        ("authoritative_runtime_base_commit", "authoritative_runtime_base_commit", "0" * 40),
        ("image_digest", "image_digest", "sha256:" + ("3" * 64)),
        ("raw_evidence_sha256", "raw_evidence_sha256", "bad"),
        ("executed_at", "executed_at", "2026-09-12T00:00:00"),
    ]
    failures: list[str] = []
    for label, field, value in mutations:
        candidate = json.loads(json.dumps(payload))
        candidate[field] = value
        if not _benchmark_payload_errors("self-test", row, candidate):
            failures.append(f"benchmark self-test failed to reject {label} drift")
    missing_load = json.loads(json.dumps(payload))
    del missing_load["load_model"][REQUIRED_LOAD_MODEL[0]]
    if not _benchmark_payload_errors("self-test", row, missing_load):
        failures.append("benchmark self-test failed to reject incomplete load model")
    missing_measurement = json.loads(json.dumps(payload))
    del missing_measurement["measurements"][REQUIRED_MEASUREMENTS[0]]
    if not _benchmark_payload_errors("self-test", row, missing_measurement):
        failures.append("benchmark self-test failed to reject incomplete measurement set")
    return failures


def validate_structure() -> list[str]:
    errors: list[str] = []
    try:
        authoritative = _required_runtime_map()
    except Exception as exc:
        return [f"authoritative inventory invalid: {exc}"]

    contract = _load(CONTRACT)
    rows = contract.get("runtimes", [])
    keys = [str(row.get("key", "")) for row in rows if isinstance(row, dict)]
    contract_map = {str(row.get("key")): str(row.get("health_env")) for row in rows if isinstance(row, dict)}
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("contract is not anchored to the sealed authoritative release commit")
    if contract.get("expected_required_runtime_count") != EXPECTED_COUNT:
        errors.append("contract expected runtime count is not 26")
    if len(rows) != EXPECTED_COUNT or len(set(keys)) != EXPECTED_COUNT:
        errors.append("contract does not contain exactly 26 unique runtime rows")
    if set(contract_map) != set(authoritative):
        errors.append("contract runtime keys do not exactly match authoritative required-runtime keys")
    for key, expected_env in authoritative.items():
        if contract_map.get(key) != expected_env:
            errors.append(f"{key}: health_env does not match authoritative registry")

    declared_fields = contract.get("required_deployment_fields")
    if declared_fields != list(DEPLOYMENT_FIELDS):
        errors.append("contract required deployment fields do not exactly match validator policy")
    defaults = contract.get("defaults_for_unresolved_fields", {})
    if not isinstance(defaults, dict):
        errors.append("contract unresolved defaults are not an object")
    else:
        for field in DEPLOYMENT_FIELDS:
            if field not in defaults:
                errors.append(f"contract unresolved defaults omit {field}")
            elif defaults.get(field) is not None:
                errors.append(f"contract unresolved default for {field} is not null")
        if defaults.get("benchmark_status") != "unmeasured":
            errors.append("contract unresolved benchmark default is not unmeasured")

    namespace = _load(NAMESPACE)
    labels = namespace.get("metadata", {}).get("labels", {})
    if namespace.get("kind") != "Namespace" or namespace.get("metadata", {}).get("name") != EXPECTED_NAMESPACE:
        errors.append("namespace identity is invalid")
    if labels.get("musitu.io/staging-only") != "true" or labels.get("musitu.io/production-authorized") != "false":
        errors.append("namespace claim-boundary labels are not fail closed")
    for mode in ("enforce", "audit", "warn"):
        if labels.get(f"pod-security.kubernetes.io/{mode}") != "restricted":
            errors.append(f"namespace Pod Security {mode} is not restricted")

    network = _load(NETWORK)
    spec = network.get("spec", {})
    if network.get("kind") != "NetworkPolicy" or network.get("metadata", {}).get("namespace") != EXPECTED_NAMESPACE:
        errors.append("default-deny NetworkPolicy identity is invalid")
    if spec.get("podSelector") != {}:
        errors.append("default-deny NetworkPolicy does not select all pods")
    if set(spec.get("policyTypes", [])) != {"Ingress", "Egress"}:
        errors.append("default-deny NetworkPolicy must cover ingress and egress")
    if spec.get("ingress") != [] or spec.get("egress") != []:
        errors.append("default-deny NetworkPolicy unexpectedly permits traffic")

    quota = _load(QUOTA)
    if quota.get("kind") != "ResourceQuota" or quota.get("metadata", {}).get("namespace") != EXPECTED_NAMESPACE:
        errors.append("zero-workload quota identity is invalid")
    if quota.get("spec", {}).get("hard", {}).get("pods") != "0":
        errors.append("zero-workload quota is not fail closed at pods=0")

    if not KUSTOMIZATION.is_file():
        errors.append("kustomization.yaml is missing")
    elif KUSTOMIZATION.read_text(encoding="utf-8") != EXPECTED_KUSTOMIZATION:
        errors.append("kustomization composition does not exactly preserve the fail-closed foundation")
    if not BENCHMARK.is_file():
        errors.append("resource benchmark plan is missing")
    else:
        benchmark = _load(BENCHMARK)
        if benchmark.get("benchmark_status_required_for_deployability") != "measured":
            errors.append("benchmark plan does not require measured status")
        if benchmark.get("benchmark_evidence_schema_version") != BENCHMARK_EVIDENCE_SCHEMA:
            errors.append("benchmark plan evidence schema version does not match validator policy")
        if benchmark.get("required_load_model") != list(REQUIRED_LOAD_MODEL):
            errors.append("benchmark plan load-model requirements do not exactly match validator policy")
        if benchmark.get("required_measurements") != list(REQUIRED_MEASUREMENTS):
            errors.append("benchmark plan measurement requirements do not exactly match validator policy")
        if benchmark.get("required_evidence_bindings") != list(REQUIRED_EVIDENCE_BINDINGS):
            errors.append("benchmark plan evidence bindings do not exactly match validator policy")

    return errors


def deployability_blockers() -> list[str]:
    blockers = validate_structure()
    if blockers:
        return blockers

    contract = _load(CONTRACT)
    defaults = contract.get("defaults_for_unresolved_fields", {})

    for row in contract.get("runtimes", []):
        key = str(row.get("key", "unknown"))
        for field in DEPLOYMENT_FIELDS:
            value = row.get(field, defaults.get(field))
            if value in (None, "", [], {}):
                blockers.append(f"{key}: unresolved {field}")
        digest = row.get("image_digest", defaults.get("image_digest"))
        if digest not in (None, "") and not OCI_DIGEST.fullmatch(str(digest)):
            blockers.append(f"{key}: image_digest is not immutable sha256")
        for field in REFERENCE_FIELDS:
            value = row.get(field, defaults.get(field))
            if value not in (None, "", [], {}) and not _repo_file_reference(value):
                blockers.append(f"{key}: {field} is not an existing repository-relative file")
        status = row.get("benchmark_status", defaults.get("benchmark_status"))
        if status != "measured":
            blockers.append(f"{key}: benchmark_status is not measured")
        else:
            evidence_ref = row.get("benchmark_evidence_ref", defaults.get("benchmark_evidence_ref"))
            if _repo_file_reference(evidence_ref):
                try:
                    evidence = _load((ROOT / str(evidence_ref).strip()).resolve())
                except Exception as exc:
                    blockers.append(f"{key}: benchmark evidence is unreadable or invalid JSON ({type(exc).__name__})")
                else:
                    for error in _benchmark_payload_errors(key, row, evidence):
                        blockers.append(f"{key}: {error}")

    quota = _load(QUOTA)
    if quota.get("spec", {}).get("hard", {}).get("pods") == "0":
        blockers.append("foundation: zero-pod fail-closed quota still active")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the MUSITU provider-neutral target staging contract.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--structure", action="store_true")
    mode.add_argument("--deployable", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        errors = _benchmark_self_test()
        if errors:
            for error in errors:
                print(f"SELF-TEST FAILURE: {error}")
            return 4
        print("PASS: benchmark evidence validator accepts exact bindings and rejects drift/incomplete evidence")
        return 0

    if args.structure:
        errors = validate_structure()
        if errors:
            for error in errors:
                print(f"STRUCTURE BLOCKER: {error}")
            return 2
        print("PASS: exact 26-runtime contract and fail-closed provider-neutral foundation are structurally valid")
        print("PASS: contract is pinned to the sealed release and Kustomize composition preserves all fail-closed foundation resources")
        print("PASS: resolved deployment/profile fields must reference existing repository files")
        print("PASS: benchmark evidence policy is bound to runtime/image/manifest/profile/environment/load/measurement evidence")
        print("BOUNDARY: static architecture only; no deployment or production authorization is implied")
        return 0

    blockers = deployability_blockers()
    if blockers:
        print(f"NOT DEPLOYABLE: {len(blockers)} unresolved fail-closed conditions")
        for blocker in blockers:
            print(f"DEPLOYABILITY BLOCKER: {blocker}")
        return 3
    print("PASS: provider-neutral target contract is deployable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
