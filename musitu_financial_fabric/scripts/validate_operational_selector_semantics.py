from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
SOURCE_POLICY = TARGET / "operational-profile-policy.json"
POLICY = TARGET / "operational-selector-semantics-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.operational-selector-semantics-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.operational-profile-policy.v1"
ALLOWED_FIELDS = {"matchLabels", "matchExpressions"}
ALLOWED_OPERATORS = {"In", "NotIn", "Exists", "DoesNotExist"}
LABEL_NAME = re.compile(r"^[A-Za-z0-9](?:[-_.A-Za-z0-9]{0,61}[A-Za-z0-9])?$")
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_file(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    rel = Path(value.strip())
    if rel.is_absolute():
        return None
    root = ROOT.resolve()
    resolved = (ROOT / rel).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _valid_label_key(value: object) -> bool:
    if not isinstance(value, str) or not value or value.count("/") > 1:
        return False
    if "/" in value:
        prefix, name = value.split("/", 1)
        if not prefix or len(prefix) > 253:
            return False
        if any(not DNS_LABEL.fullmatch(part) for part in prefix.split(".")):
            return False
    else:
        name = value
    return bool(LABEL_NAME.fullmatch(name))


def _valid_label_value(value: object) -> bool:
    return isinstance(value, str) and (value == "" or bool(LABEL_NAME.fullmatch(value)))


def _selector_errors(selector: object, *, require_nonempty: bool, label: str) -> list[str]:
    if not isinstance(selector, dict):
        return [f"{label} must be a Kubernetes LabelSelector object"]
    errors: list[str] = []
    unexpected = set(selector) - ALLOWED_FIELDS
    if unexpected:
        errors.append(f"{label} contains unsupported LabelSelector fields: {sorted(unexpected)}")
    match_labels = selector.get("matchLabels")
    match_expressions = selector.get("matchExpressions")
    has_requirement = False
    if match_labels is not None:
        if not isinstance(match_labels, dict):
            errors.append(f"{label}.matchLabels must be an object")
        else:
            if match_labels:
                has_requirement = True
            for key, value in match_labels.items():
                if not _valid_label_key(key):
                    errors.append(f"{label}.matchLabels contains invalid label key {key!r}")
                if not _valid_label_value(value):
                    errors.append(f"{label}.matchLabels[{key!r}] has invalid label value")
    if match_expressions is not None:
        if not isinstance(match_expressions, list):
            errors.append(f"{label}.matchExpressions must be an array")
        else:
            if match_expressions:
                has_requirement = True
            for index, expression in enumerate(match_expressions):
                prefix = f"{label}.matchExpressions[{index}]"
                if not isinstance(expression, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                extra = set(expression) - {"key", "operator", "values"}
                if extra:
                    errors.append(f"{prefix} contains unsupported fields: {sorted(extra)}")
                key = expression.get("key")
                operator = expression.get("operator")
                values = expression.get("values", [])
                if not _valid_label_key(key):
                    errors.append(f"{prefix}.key is not a valid label key")
                if operator not in ALLOWED_OPERATORS:
                    errors.append(f"{prefix}.operator must be one of {sorted(ALLOWED_OPERATORS)}")
                if not isinstance(values, list):
                    errors.append(f"{prefix}.values must be an array when provided")
                    continue
                if any(not _valid_label_value(value) for value in values):
                    errors.append(f"{prefix}.values contains an invalid label value")
                if len(values) != len(set(values)):
                    errors.append(f"{prefix}.values must not contain duplicates")
                if operator in {"In", "NotIn"} and not values:
                    errors.append(f"{prefix}.values must be non-empty for {operator}")
                if operator in {"Exists", "DoesNotExist"} and values:
                    errors.append(f"{prefix}.values must be empty for {operator}")
    if require_nonempty and not has_requirement:
        errors.append(f"{label} must contain at least one matchLabels or matchExpressions requirement")
    return errors


def _policy_errors(policy: object, source: object) -> list[str]:
    if not isinstance(policy, dict):
        return ["operational selector semantics policy root must be an object"]
    expected = {
        "schema_version": POLICY_SCHEMA,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "source_operational_profile_policy_schema_version": SOURCE_POLICY_SCHEMA,
        "allowed_selector_fields": sorted(ALLOWED_FIELDS),
        "allowed_expression_operators": sorted(ALLOWED_OPERATORS),
        "disruption_budget_selector_must_be_nonempty": True,
        "anti_affinity_empty_selector_allowed": True,
        "reject_duplicate_expression_values": True,
    }
    errors: list[str] = []
    for field, expected_value in expected.items():
        actual = policy.get(field)
        if field in {"allowed_selector_fields", "allowed_expression_operators"} and isinstance(actual, list):
            actual = sorted(actual)
        if actual != expected_value:
            errors.append(f"operational selector semantics policy {field} is invalid")
    if not isinstance(source, dict):
        return errors + ["source operational profile policy root must be an object"]
    if source.get("schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("source operational profile policy schema drifted")
    if source.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source operational profile policy is not anchored to the sealed runtime release")
    return errors


def _profile_selector_errors(field: str, path: Path) -> list[str]:
    try:
        payload = _load(path)
    except Exception as exc:
        return [f"{field} profile is unreadable or invalid JSON ({type(exc).__name__})"]
    if not isinstance(payload, dict):
        return [f"{field} profile root must be an object"]
    if payload.get("status") != "configured":
        return []
    errors: list[str] = []
    if field == "disruption_budget_profile":
        errors.extend(_selector_errors(payload.get("selector"), require_nonempty=True, label="disruption budget selector"))
    elif field == "anti_affinity_profile":
        constraints = payload.get("constraints")
        if not isinstance(constraints, list):
            return ["anti-affinity configured constraints must be an array"]
        for index, constraint in enumerate(constraints):
            if not isinstance(constraint, dict):
                errors.append(f"anti-affinity constraints[{index}] must be an object")
                continue
            errors.extend(
                _selector_errors(
                    constraint.get("label_selector"),
                    require_nonempty=False,
                    label=f"anti-affinity constraints[{index}].label_selector",
                )
            )
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source)
    if failures:
        return failures
    valid = [
        ({"matchLabels": {"app.kubernetes.io/name": "runtime"}}, True),
        ({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["backend"]}]}, True),
        ({"matchExpressions": [{"key": "present", "operator": "Exists", "values": []}]}, True),
        ({}, False),
    ]
    for selector, require_nonempty in valid:
        errors = _selector_errors(selector, require_nonempty=require_nonempty, label="self-test selector")
        if errors:
            failures.append(f"valid synthetic LabelSelector was rejected: {errors}")
    invalid = [
        ({"source": "self-test"}, True, "arbitrary selector field"),
        ({}, True, "empty disruption selector"),
        ({"matchLabels": {"bad key": "value"}}, True, "invalid label key"),
        ({"matchLabels": {"app": "bad value!"}}, True, "invalid label value"),
        ({"matchExpressions": [{"key": "tier", "operator": "Any", "values": ["backend"]}]}, True, "invalid operator"),
        ({"matchExpressions": [{"key": "tier", "operator": "In", "values": []}]}, True, "empty In values"),
        ({"matchExpressions": [{"key": "tier", "operator": "Exists", "values": ["backend"]}]}, True, "nonempty Exists values"),
        ({"matchExpressions": [{"key": "tier", "operator": "In", "values": ["backend", "backend"]}]}, True, "duplicate values"),
    ]
    for selector, require_nonempty, label in invalid:
        if not _selector_errors(selector, require_nonempty=require_nonempty, label="self-test selector"):
            failures.append(f"self-test failed to reject {label}")
    return failures


def _contract_errors() -> tuple[list[str], dict[str, tuple[int, int]]]:
    policy = _load(POLICY)
    source = _load(SOURCE_POLICY)
    errors = _policy_errors(policy, source)
    contract = _load(CONTRACT)
    defaults = contract.get("defaults_for_unresolved_fields", {})
    runtimes = contract.get("runtimes")
    counts = {
        "disruption_budget_profile": [0, 0],
        "anti_affinity_profile": [0, 0],
    }
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
    if not isinstance(runtimes, list):
        return errors + ["runtime contract runtimes must be a list"], {key: tuple(value) for key, value in counts.items()}
    for row in runtimes:
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        runtime = str(row.get("key", "unknown"))
        for field in counts:
            ref = row.get(field, defaults.get(field))
            if ref in (None, "", [], {}):
                counts[field][1] += 1
                continue
            path = _repo_file(ref)
            if path is None:
                errors.append(f"{runtime}: {field} must reference an existing repository file")
                continue
            profile_errors = _profile_selector_errors(field, path)
            if profile_errors:
                errors.extend(f"{runtime}: {field}: {item}" for item in profile_errors)
            else:
                counts[field][0] += 1
    return errors, {key: tuple(value) for key, value in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed Kubernetes LabelSelector semantics for operational profiles.")
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
        print("PASS: operational selector semantics rejects arbitrary/invalid LabelSelectors, all-Pod PDB selectors, invalid operators/value cardinality, and malformed label syntax")
        return 0
    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"OPERATIONAL SELECTOR BLOCKER: {error}")
        return 2
    for field in ("disruption_budget_profile", "anti_affinity_profile"):
        resolved, unresolved = counts[field]
        print(f"PASS: {field}_selector_semantics: validated {resolved} resolved profiles; {unresolved} remain unresolved")
    print("BOUNDARY: static LabelSelector semantics only; no Kubernetes admission, pod matching, scheduling, eviction behavior, deployment, production authorization, or independent validation is proved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
