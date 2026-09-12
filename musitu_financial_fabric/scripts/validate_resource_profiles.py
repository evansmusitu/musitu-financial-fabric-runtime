from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "resource-profile-policy.json"
BENCHMARK_PLAN = TARGET / "resource-benchmark-plan.json"
SELF_TEST_EVIDENCE = TARGET / ".validation" / "resource-profile-self-test-evidence.txt"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
BENCHMARK_SEMANTIC_PROFILE = "mff.benchmark-semantic-profile.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
QUANTITY_RE = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    r"(?P<suffix>Ki|Mi|Gi|Ti|Pi|Ei|m|k|M|G|T|P|E|[eE][+-]?\d+)?$"
)
MAX_QUANTITY_MAGNITUDE = Decimal(2**63 - 1)
DECIMAL_FACTORS = {
    "": Decimal(1),
    "m": Decimal("0.001"),
    "k": Decimal(10) ** 3,
    "M": Decimal(10) ** 6,
    "G": Decimal(10) ** 9,
    "T": Decimal(10) ** 12,
    "P": Decimal(10) ** 15,
    "E": Decimal(10) ** 18,
}
BINARY_FACTORS = {
    "Ki": Decimal(2) ** 10,
    "Mi": Decimal(2) ** 20,
    "Gi": Decimal(2) ** 30,
    "Ti": Decimal(2) ** 40,
    "Pi": Decimal(2) ** 50,
    "Ei": Decimal(2) ** 60,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


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


def _quantity_policy_errors(policy: dict[str, Any]) -> list[str]:
    expected = {
        "grammar": "kubernetes_quantity",
        "positive_for_resolution": True,
        "reject_server_side_rounding": True,
        "cpu_minimum_unit": "1m",
        "memory_base_unit": "byte",
        "requests_must_not_exceed_limits": True,
        "maximum_magnitude": str(2**63 - 1),
    }
    if policy.get("compute_quantity_policy") != expected:
        return ["resource profile compute_quantity_policy is invalid"]
    return []


def _headroom_policy_errors(policy: dict[str, Any]) -> list[str]:
    expected = {
        "basis_percentile": "p95",
        "cpu_measurement": "cpu_p95",
        "cpu_measurement_unit": "cores",
        "memory_measurement": "memory_rss_p95",
        "memory_measurement_unit": "bytes",
        "ratios_must_be_non_negative": True,
        "limits_must_cover_measurement_plus_headroom": True,
    }
    if policy.get("headroom_policy") != expected:
        return ["resource profile headroom_policy is invalid"]
    if policy.get("required_headroom_fields") != ["basis_percentile", "cpu_ratio", "memory_ratio"]:
        return ["resource profile required_headroom_fields are invalid"]
    return []


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["resource profile policy root must be an object"]
    if policy.get("schema_version") != "mff.resource-profile-policy.v3":
        errors.append("resource profile policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("resource profile policy is not anchored to the sealed runtime release")
    if policy.get("benchmark_plan_schema_version") != "mff.resource-benchmark-plan.v1":
        errors.append("resource profile policy benchmark plan schema is invalid")
    if policy.get("benchmark_evidence_schema_version") != "mff.runtime-benchmark-evidence.v1":
        errors.append("resource profile policy benchmark evidence schema is invalid")
    if policy.get("benchmark_semantic_profile_version") != BENCHMARK_SEMANTIC_PROFILE:
        errors.append("resource profile benchmark semantic profile is invalid")
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
    errors.extend(_quantity_policy_errors(policy))
    errors.extend(_headroom_policy_errors(policy))
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
    if plan.get("benchmark_semantic_profile_version") != policy.get("benchmark_semantic_profile_version"):
        errors.append("resource benchmark semantic profile does not match resource profile policy")
    return errors


def _quantity_value(value: object, *, resource: str) -> tuple[Decimal | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, f"{resource} quantity is missing"
    text = value.strip()
    match = QUANTITY_RE.fullmatch(text)
    if match is None:
        return None, f"{resource} quantity is not a supported Kubernetes Quantity"
    try:
        number = Decimal(match.group("number"))
    except InvalidOperation:
        return None, f"{resource} quantity number is invalid"

    suffix = match.group("suffix") or ""
    if suffix in DECIMAL_FACTORS:
        factor = DECIMAL_FACTORS[suffix]
    elif suffix in BINARY_FACTORS:
        factor = BINARY_FACTORS[suffix]
    else:
        factor = Decimal(10) ** int(suffix[1:])

    base_value = number * factor
    if base_value <= 0:
        return None, f"{resource} quantity must be greater than zero for a resolved resource profile"
    if abs(base_value) > MAX_QUANTITY_MAGNITUDE:
        return None, f"{resource} quantity exceeds Kubernetes Quantity magnitude bound"

    if resource == "cpu":
        milli_cpu = base_value * Decimal(1000)
        if milli_cpu != milli_cpu.to_integral_value():
            return None, "cpu quantity has precision finer than 1m"
    elif resource == "memory":
        if base_value != base_value.to_integral_value():
            return None, "memory quantity must resolve to a whole number of bytes"
    else:
        return None, f"unsupported compute resource {resource}"
    return base_value, None


def _compute_values(
    payload: dict[str, Any], policy: dict[str, Any]
) -> tuple[list[str], dict[tuple[str, str], Decimal]]:
    errors: list[str] = []
    parsed: dict[tuple[str, str], Decimal] = {}
    for block_name in ("requests", "limits"):
        block = payload.get(block_name)
        if not isinstance(block, dict):
            errors.append(f"resource profile {block_name} must be an object")
            continue
        for field in policy.get("required_compute_fields", []):
            value, error = _quantity_value(block.get(field), resource=field)
            if error is not None:
                errors.append(f"resource profile {block_name}.{field}: {error}")
            elif value is not None:
                parsed[(block_name, field)] = value

    if policy.get("compute_quantity_policy", {}).get("requests_must_not_exceed_limits") is True:
        for field in policy.get("required_compute_fields", []):
            request = parsed.get(("requests", field))
            limit = parsed.get(("limits", field))
            if request is not None and limit is not None and request > limit:
                errors.append(f"resource profile requests.{field} must not exceed limits.{field}")
    return errors, parsed


def _benchmark_binding_errors(
    key: str,
    row: dict[str, Any],
    profile: dict[str, Any],
    policy: dict[str, Any],
    benchmark_payload: object | None = None,
) -> tuple[list[str], object | None]:
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
            return errors, None
        try:
            benchmark_payload = _load(path)
        except Exception as exc:
            errors.append(f"benchmark evidence is unreadable or invalid JSON ({type(exc).__name__})")
            return errors, None
    if not isinstance(benchmark_payload, dict):
        return errors + ["benchmark evidence root must be an object"], benchmark_payload
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
    return errors, benchmark_payload


def _headroom_errors(
    basis: object,
    benchmark_payload: object,
    compute_values: dict[tuple[str, str], Decimal],
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(basis, dict):
        return errors
    headroom = basis.get("headroom")
    if not isinstance(headroom, dict):
        return ["resource profile sizing_basis.headroom must be an object"]
    for field in policy.get("required_headroom_fields", []):
        if field not in headroom:
            errors.append(f"resource profile sizing_basis.headroom missing {field}")
    expected_percentile = policy.get("headroom_policy", {}).get("basis_percentile")
    if headroom.get("basis_percentile") != expected_percentile:
        errors.append(f"resource profile sizing_basis.headroom.basis_percentile must be {expected_percentile}")

    ratios: dict[str, Decimal] = {}
    for name in ("cpu_ratio", "memory_ratio"):
        value = _number(headroom.get(name))
        if value is None:
            errors.append(f"resource profile sizing_basis.headroom.{name} must be a finite JSON number")
        elif value < 0:
            errors.append(f"resource profile sizing_basis.headroom.{name} must be non-negative")
        else:
            ratios[name] = value

    if not isinstance(benchmark_payload, dict):
        errors.append("resource profile cannot bind headroom without benchmark evidence object")
        return errors
    measurements = benchmark_payload.get("measurements")
    if not isinstance(measurements, dict):
        errors.append("benchmark evidence measurements must be an object for headroom binding")
        return errors

    headroom_policy = policy.get("headroom_policy", {})
    specifications = (
        (
            "cpu",
            str(headroom_policy.get("cpu_measurement", "")),
            str(headroom_policy.get("cpu_measurement_unit", "")),
            "cpu_ratio",
        ),
        (
            "memory",
            str(headroom_policy.get("memory_measurement", "")),
            str(headroom_policy.get("memory_measurement_unit", "")),
            "memory_ratio",
        ),
    )
    for resource, measurement_name, expected_unit, ratio_name in specifications:
        metric = measurements.get(measurement_name)
        if not isinstance(metric, dict):
            errors.append(f"benchmark evidence missing structured {measurement_name} for headroom binding")
            continue
        measured = _number(metric.get("value"))
        if measured is None or measured < 0:
            errors.append(f"benchmark evidence {measurement_name}.value must be a non-negative finite number")
            continue
        if metric.get("unit") != expected_unit:
            errors.append(f"benchmark evidence {measurement_name}.unit must be {expected_unit}")
            continue
        ratio = ratios.get(ratio_name)
        limit = compute_values.get(("limits", resource))
        if ratio is None or limit is None:
            continue
        required_limit = measured * (Decimal(1) + ratio)
        if limit < required_limit:
            errors.append(
                f"resource profile limits.{resource} does not cover {measurement_name} plus declared headroom"
            )
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

    compute_errors, parsed_compute = _compute_values(payload, policy)
    errors.extend(compute_errors)

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
        if not isinstance(basis.get("rationale"), str) or not basis["rationale"].strip():
            errors.append("resource profile sizing_basis.rationale is missing")

    binding_errors, bound_benchmark = _benchmark_binding_errors(
        key, row, payload, policy, benchmark_payload
    )
    errors.extend(binding_errors)
    errors.extend(_headroom_errors(basis, bound_benchmark, parsed_compute, policy))
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
        "measurements": {
            "cpu_p95": {"value": 0.6, "unit": "cores"},
            "memory_rss_p95": {"value": 700000000, "unit": "bytes"},
        },
    }
    profile = {
        "schema_version": "mff.resource-profile.v1",
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "benchmark_evidence_ref": benchmark_ref,
        "requests": {"cpu": "0.5", "memory": "256Mi"},
        "limits": {"cpu": "1", "memory": "1Gi"},
        "sizing_basis": {
            "selected_from_measurements": True,
            "headroom": {
                "basis_percentile": "p95",
                "cpu_ratio": 0.25,
                "memory_ratio": 0.25,
            },
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

    quantity_mutations = [
        ("malformed cpu quantity", "requests", "cpu", "synthetic"),
        ("sub-millicpu precision", "requests", "cpu", "0.0005"),
        ("fractional millicpu", "requests", "cpu", "0.5m"),
        ("fractional-byte memory", "requests", "memory", "400m"),
        ("malformed memory suffix", "requests", "memory", "256MB"),
        ("zero cpu quantity", "requests", "cpu", "0"),
    ]
    for label, block, field, value in quantity_mutations:
        candidate = json.loads(json.dumps(profile))
        candidate[block][field] = value
        if not _profile_errors("self-test", row, candidate, policy, benchmark):
            failures.append(f"resource profile self-test failed to reject {label}")

    candidate = json.loads(json.dumps(profile))
    candidate["requests"]["cpu"] = "2"
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject cpu request above limit")

    candidate = json.loads(json.dumps(profile))
    candidate["requests"]["memory"] = "2Gi"
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject memory request above limit")

    candidate = json.loads(json.dumps(profile))
    candidate["sizing_basis"]["headroom"] = {"source": "placeholder"}
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject placeholder headroom")

    candidate = json.loads(json.dumps(profile))
    candidate["sizing_basis"]["headroom"]["basis_percentile"] = "p99"
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject wrong headroom percentile basis")

    candidate = json.loads(json.dumps(profile))
    candidate["sizing_basis"]["headroom"]["cpu_ratio"] = -0.1
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject negative CPU headroom")

    candidate = json.loads(json.dumps(profile))
    candidate["limits"]["cpu"] = "700m"
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject CPU limit below p95 plus headroom")

    candidate = json.loads(json.dumps(profile))
    candidate["limits"]["memory"] = "800Mi"
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject memory limit below p95 plus headroom")

    bad_benchmark = json.loads(json.dumps(benchmark))
    bad_benchmark["measurements"]["cpu_p95"]["unit"] = "millicores"
    if not _profile_errors("self-test", row, profile, policy, bad_benchmark):
        failures.append("resource profile self-test failed to reject benchmark CPU unit drift")

    bad_benchmark = json.loads(json.dumps(benchmark))
    del bad_benchmark["measurements"]["memory_rss_p95"]
    if not _profile_errors("self-test", row, profile, policy, bad_benchmark):
        failures.append("resource profile self-test failed to reject missing benchmark memory p95")

    candidate = json.loads(json.dumps(profile))
    candidate["target_validation"]["evidence_sha256"] = "0" * 64
    if not _profile_errors("self-test", row, candidate, policy, benchmark):
        failures.append("resource profile self-test failed to reject target evidence hash mismatch")

    bad_benchmark = json.loads(json.dumps(benchmark))
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
        print(
            "PASS: resource profile validator rejects unmeasured sizing, benchmark drift, "
            "invalid Kubernetes CPU/memory quantities, request-over-limit assignments, "
            "unbound or mathematically insufficient p95 headroom, incomplete compute assignments, "
            "and unbound target evidence"
        )
        return 0
    errors, resolved, unresolved = _contract_errors()
    if errors:
        for error in errors:
            print(f"RESOURCE PROFILE BLOCKER: {error}")
        return 2
    print(f"PASS: resource_profile: validated {resolved} resolved profiles; {unresolved} remain unresolved")
    print(
        "BOUNDARY: no CPU/memory assignment, production sizing, benchmark result, "
        "or target execution is inferred from unresolved profiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
