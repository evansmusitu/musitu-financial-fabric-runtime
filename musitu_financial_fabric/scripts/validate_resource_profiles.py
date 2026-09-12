from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "resource-profile-policy.json"
BENCHMARK_PLAN = TARGET / "resource-benchmark-plan.json"
SELF_TEST_EVIDENCE = TARGET / ".validation" / "resource-profile-self-test-evidence.txt"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_errors(payload: object, *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label} must be an object"]
    if payload.get("status") != "passed":
        errors.append(f"{label}.status must be passed")
    evidence = _repo_file(payload.get("evidence_ref"))
    if evidence is None:
        errors.append(f"{label}.evidence_ref must reference an existing repository file")
    declared = str(payload.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append(f"{label}.evidence_sha256 is missing or malformed")
    elif evidence is not None and _sha256(evidence) != declared:
        errors.append(f"{label} evidence SHA-256 does not match retained bytes")
    return errors


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["resource profile policy root must be an object"]
    if policy.get("schema_version") != "mff.resource-profile-policy.v1":
        errors.append("resource profile policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("resource profile policy is not anchored to the sealed runtime release")
    if policy.get("benchmark_plan_schema_version") != "mff.resource-benchmark-plan.v1":
        errors.append("resource profile policy benchmark plan schema is invalid")
    if policy.get("benchmark_evidence_schema_version") != "mff.runtime-benchmark-evidence.v1":
        errors.append("resource profile policy benchmark evidence schema is invalid")
    if policy.get("profile_schema_version") != "mff.resource-profile.v1":
        errors.append("resource profile schema is invalid")
    if policy.get("benchmark_status_required_for_resolution") != "measured":
        errors.append("resource profile policy does not require measured benchmark status")
    if policy.get("target_validation_status_required_for_resolution") != "passed":
        errors.append("resource profile policy does not require passed target validation")
    for field in ("required_fields", "required_compute_fields", "required_sizing_basis_fields"):
        values = policy.get(field)
        if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values):
            errors.append(f"resource profile policy {field} is invalid")
    return errors


def _benchmark_plan_errors(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    plan = _load(BENCHMARK_PLAN)
    if plan.get("schema_version") != policy.get("benchmark_plan_schema_version"):
        errors.append("resource benchmark plan schema does not match resource profile policy")
    if plan.get("benchmark_status_required_for_deployability") != "measured":
        errors.append("resource benchmark plan does not require measured status")
    if plan.get("benchmark_evidence_schema_version") != policy.get("benchmark_evidence_schema_version"):
        errors.append("resource benchmark evidence schema does not match resource profile policy")
    return errors


def _benchmark_binding_errors(
    key: str,
    row: dict[str, Any],
    profile: dict[str, Any],
    policy: dict[str, Any],
    benchmark_payload: object | None = None,
) -> list[str]:
    errors: list[str] = []
    if row.get("benchmark_status") != policy.get("benchmark_status_required_for_resolution"):
        errors.append("contract row benchmark_status is not measured")
    benchmark_ref = row.get("benchmark_evidence_ref")
    if profile.get("benchmark_evidence_ref") != benchmark_ref:
        errors.append("resource profile benchmark_evidence_ref does not match contract row")
    if benchmark_payload is None:
        path = _repo_file(benchmark_ref)
        if path is None:
            errors.append("benchmark_evidence_ref must reference an existing repository file")
            return errors
        try:
            benchmark_payload = _load(path)
        except Exception as exc:
            errors.append(f"benchmark evidence is unreadable or invalid JSON ({type(exc).__name__})")
            return errors
    if not isinstance(benchmark_payload, dict):
        return errors + ["benchmark evidence root must be an object"]
    if benchmark_payload.get("schema_version") != policy.get("benchmark_evidence_schema_version"):
        errors.append("benchmark evidence schema_version is invalid")
    if benchmark_payload.get("runtime_key") != key:
        errors.append("benchmark evidence runtime_key does not match resource profile")
    if benchmark_payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("benchmark evidence is not bound to the sealed runtime release")
    if benchmark_payload.get("image_digest") != row.get("image_digest"):
        errors.append("benchmark evidence image_digest does not match contract row")
    if benchmark_payload.get("environment_id") != profile.get("environment_id"):
        errors.append("benchmark evidence environment_id does not match resource profile")
    if benchmark_payload.get("resource_profile") != row.get("resource_profile"):
        errors.append("benchmark evidence resource_profile does not match contract row")
    return errors


def _profile_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    policy: dict[str, Any],
    benchmark_payload: object | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["resource profile root must be an object"]
    if payload.get("schema_version") != policy.get("profile_schema_version"):
        errors.append("resource profile schema_version is invalid")
    for field in policy.get("required_fields", []):
        if field not in payload:
            errors.append(f"resource profile missing {field}")
    if payload.get("runtime_key") != key:
        errors.append("resource profile runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("resource profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest for resource binding")
    elif payload.get("image_digest") != digest:
        errors.append("resource profile image_digest does not match contract row")
    environment = payload.get("environment_id")
    if not isinstance(environment, str) or not environment.strip():
        errors.append("resource profile environment_id is missing")

    for block_name in ("requests", "limits"):
        block = payload.get(block_name)
        if not isinstance(block, dict):
            errors.append(f"resource profile {block_name} must be an object")
            continue
        for field in policy.get("required_compute_fields", []):
            value = block.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"resource profile {block_name}.{field} is missing")

    basis = payload.get("sizing_basis")
    if not isinstance(basis, dict):
        errors.append("resource profile sizing_basis must be an object")
    else:
        for field in policy.get("required_sizing_basis_fields", []):
            if field not in basis:
                errors.append(f"resource profile sizing_basis missing {field}")
        if basis.get("selected_from_measurements") is not True:
            errors.append("resource profile must be selected from retained measurements")
        if basis.get("failure_recovery_considered") is not True:
            errors.append("resource profile must document failure/recovery consideration")
        if not _nonempty(basis.get("headroom")):
            errors.append("resource profile sizing_basis.headroom is missing")
        if not isinstance(basis.get("rationale"), str) or not basis["rationale"].strip():
            errors.append("resource profile sizing_basis.rationale is missing")

    errors.extend(_benchmark_binding_errors(key, row, payload, policy, benchmark_payload))
    errors.extend(_evidence_errors(payload.get("target_validation"), label="target_validation"))
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    failures = _policy_errors(policy) + _benchmark_plan_errors(policy)
    if failures:
        return failures
    evidence_ref = str(SELF_TEST_EVIDENCE.relative_to(ROOT)).replace("\\", "/")
    evidence_sha = _sha256(SELF_TEST_EVIDENCE)
    digest = "sha256:" + ("1" * 64)
    resource_ref = "deploy/musitu-financial-fabric/provider-neutral/self-test-resource-profile.json"
    benchmark_ref = "deploy/musitu-financial-fabric/provider-neutral/self-test-benchmark-evidence.json"
    row = {
        "image_digest": digest,
        "resource_profile": resource_ref,
        "benchmark_status": "measured",
        "benchmark_evidence_ref": benchmark_ref,
    }
    benchmark = {
        "schema_version": "mff.runtime-benchmark-evidence.v1",
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "resource_profile": resource_ref,
    }
    profile = {
        "schema_version": "mff.resource-profile.v1",
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "benchmark_evidence_ref": benchmark_ref,
        "requests": {"cpu": "synthetic", "memory": "synthetic"},
        "limits": {"cpu": "synthetic", "memory": "synthetic"},
        "sizing_basis": {
            "selected_from_measurements": True,
            "headroom": {"source": "synthetic-self-test"},
            "failure_recovery_considered": True,
            "rationale": "synthetic self-test only",
        },
        "target_validation": {
            "status": "passed",
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence_sha,
        },
    }
    if _profile_errors("self-test", row, profile, policy, benchmark):
        failures.append("valid synthetic resource profile was rejected")

    mutations: list[tuple[str, str, object]] = [
        ("runtime drift", "runtime_key", "wrong-runtime"),
        ("release drift", "authoritative_runtime_base_commit", "0" * 40),
        ("image drift", "image_digest", "sha256:" + ("2" * 64)),
        ("benchmark ref drift", "benchmark_evidence_ref", "wrong-benchmark.json"),
    ]
    for label, field, value in mutations:
        candidate = json.loads(json.dumps(profile))
        candidate[field] = value
        if not _profile_errors("self-test", row, candidate, policy, benchmark):
            failures.append(f"resource profile self-test failed to reject {label}")

    candidate_row = dict(row)
    candidate_row["benchmark_status"] = "unmeasured"
    if not _profile_errors("self-test", candidate_row, profile, policy, benchmark):
        failures.append("resource profile self-test failed to reject unmeasured benchmark status")

    candidate = json.loads(json.dumps(profile))
    candidate["sizing_basis"]["selected_from_measurements"] = False
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject non-measured sizing basis")

    candidate = json.loads(json.dumps(profile))
    candidate["sizing_basis"]["failure_recovery_considered"] = False
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject missing failure/recovery consideration")

    candidate = json.loads(json.dumps(profile))
    candidate["requests"]["cpu"] = ""
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject empty compute request")

    candidate = json.loads(json.dumps(profile))
    candidate["target_validation"]["evidence_sha256"] = "0" * 64
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject target evidence hash mismatch")

    bad_benchmark = dict(benchmark)
    bad_benchmark["environment_id"] = "wrong-target"
    if not _profile_errors("self-test", row, profile, policy, bad_benchmark):
        failures.append("resource profile self-test failed to reject benchmark environment drift")
    return failures


def _contract_errors() -> tuple[list[str], int, int]:
    errors: list[str] = []
    policy = _load(POLICY)
    errors.extend(_policy_errors(policy))
    errors.extend(_benchmark_plan_errors(policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, 0, 0
    defaults = contract.get("defaults_for_unresolved_fields", {})
    resolved = unresolved = 0
    for row in contract.get("runtimes", []):
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))
        resource_ref = row.get("resource_profile", defaults.get("resource_profile"))
        if resource_ref in (None, "", [], {}):
            unresolved += 1
            continue
        path = _repo_file(resource_ref)
        if path is None:
            errors.append(f"{key}: resource_profile is not an existing repository file")
            continue
        try:
            payload = _load(path)
        except Exception as exc:
            errors.append(f"{key}: resource profile is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        profile_errors = _profile_errors(key, row, payload, policy)
        errors.extend(f"{key}: resource_profile: {error}" for error in profile_errors)
        if not profile_errors:
            resolved += 1
    return errors, resolved, unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral measured resource profiles.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        failures = _self_test()
        if failures:
            for failure in failures:
                print(f"SELF-TEST FAILURE: {failure}")
            return 4
        print("PASS: resource profile validator rejects unmeasured sizing, benchmark drift, incomplete compute assignments, and unbound target evidence")
        return 0
    errors, resolved, unresolved = _contract_errors()
    if errors:
        for error in errors:
            print(f"RESOURCE PROFILE BLOCKER: {error}")
        return 2
    print(f"PASS: resource_profile: validated {resolved} resolved profiles; {unresolved} remain unresolved")
    print("BOUNDARY: no CPU/memory assignment, production sizing, benchmark result, or target execution is inferred from unresolved profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
