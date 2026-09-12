from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
SOURCE_POLICY = TARGET / "kubernetes-workload-binding-policy.json"
POLICY = TARGET / "kubernetes-controller-selector-satisfaction-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.kubernetes-controller-selector-satisfaction-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.kubernetes-workload-binding-policy.v1"
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
SELECTOR_REQUIRED = {"Deployment", "StatefulSet", "DaemonSet"}
SELECTOR_OPTIONAL = {"Job", "CronJob"}
ALLOWED_FIELDS = {"matchLabels", "matchExpressions"}
ALLOWED_OPERATORS = {"In", "NotIn", "Exists", "DoesNotExist"}


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


def _policy_errors(policy: object, source: object) -> list[str]:
    if not isinstance(policy, dict):
        return ["controller selector satisfaction policy root must be an object"]
    expected = {
        "schema_version": POLICY_SCHEMA,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "source_workload_binding_policy_schema_version": SOURCE_POLICY_SCHEMA,
        "selector_required_kinds": sorted(SELECTOR_REQUIRED),
        "selector_optional_kinds": sorted(SELECTOR_OPTIONAL),
        "allowed_selector_fields": sorted(ALLOWED_FIELDS),
        "allowed_expression_operators": sorted(ALLOWED_OPERATORS),
        "all_selector_requirements_must_match_template_labels": True,
    }
    errors: list[str] = []
    for field, wanted in expected.items():
        actual = policy.get(field)
        if field in {"selector_required_kinds", "selector_optional_kinds", "allowed_selector_fields", "allowed_expression_operators"} and isinstance(actual, list):
            actual = sorted(actual)
        if actual != wanted:
            errors.append(f"controller selector satisfaction policy {field} is invalid")
    if not isinstance(source, dict):
        return errors + ["source workload binding policy root must be an object"]
    if source.get("schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("source workload binding policy schema drifted")
    if source.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source workload binding policy is not anchored to the sealed runtime release")
    if sorted(source.get("selector_required_kinds") or []) != sorted(SELECTOR_REQUIRED):
        errors.append("required selector kinds drifted from workload binding authority")
    if sorted(source.get("selector_optional_kinds") or []) != sorted(SELECTOR_OPTIONAL):
        errors.append("optional selector kinds drifted from workload binding authority")
    return errors


def _documents(payload: object) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict):
        return [], ["rendered manifest root must be a Kubernetes object"]
    if payload.get("kind") != "List":
        return [payload], []
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return [], ["Kubernetes List must contain a non-empty items array"]
    docs: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            docs.append(item)
        else:
            errors.append(f"Kubernetes List item {index} must be an object")
    return docs, errors


def _template_and_selector(obj: dict[str, Any]) -> tuple[dict[str, Any] | None, object]:
    kind = obj.get("kind")
    spec = obj.get("spec")
    if not isinstance(spec, dict):
        return None, None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        template = spec.get("template")
        selector = spec.get("selector")
    elif kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else None
        template = job_spec.get("template") if isinstance(job_spec, dict) else None
        selector = job_spec.get("selector") if isinstance(job_spec, dict) else None
    else:
        return None, None
    metadata = template.get("metadata") if isinstance(template, dict) else None
    labels = metadata.get("labels") if isinstance(metadata, dict) else None
    return (labels if isinstance(labels, dict) else None), selector


def _selector_errors(labels: dict[str, Any], selector: object, *, required: bool, label: str) -> list[str]:
    if selector is None:
        return [f"{label} selector is required"] if required else []
    if not isinstance(selector, dict):
        return [f"{label} selector must be a LabelSelector object"]
    errors: list[str] = []
    extra_fields = set(selector) - ALLOWED_FIELDS
    if extra_fields:
        errors.append(f"{label} selector contains unsupported fields: {sorted(extra_fields)}")
    match_labels = selector.get("matchLabels")
    if not isinstance(match_labels, dict):
        errors.append(f"{label} selector.matchLabels must be an object")
    else:
        for key, value in match_labels.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                errors.append(f"{label} selector.matchLabels entries must be string key/value pairs")
            elif labels.get(key) != value:
                errors.append(f"{label} selector.matchLabels[{key!r}] is not satisfied by Pod-template labels")
    expressions = selector.get("matchExpressions", [])
    if expressions is None:
        expressions = []
    if not isinstance(expressions, list):
        return errors + [f"{label} selector.matchExpressions must be an array"]
    for index, expression in enumerate(expressions):
        prefix = f"{label} selector.matchExpressions[{index}]"
        if not isinstance(expression, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unexpected = set(expression) - {"key", "operator", "values"}
        if unexpected:
            errors.append(f"{prefix} contains unsupported fields: {sorted(unexpected)}")
        key = expression.get("key")
        operator = expression.get("operator")
        values = expression.get("values", [])
        if not isinstance(key, str) or not key:
            errors.append(f"{prefix}.key must be a non-empty string")
            continue
        if operator not in ALLOWED_OPERATORS:
            errors.append(f"{prefix}.operator must be one of {sorted(ALLOWED_OPERATORS)}")
            continue
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            errors.append(f"{prefix}.values must be an array of strings")
            continue
        if len(values) != len(set(values)):
            errors.append(f"{prefix}.values must not contain duplicates")
        if operator in {"In", "NotIn"} and not values:
            errors.append(f"{prefix}.values must be non-empty for {operator}")
            continue
        if operator in {"Exists", "DoesNotExist"} and values:
            errors.append(f"{prefix}.values must be empty for {operator}")
            continue
        present = key in labels
        actual = labels.get(key)
        satisfied = (
            (operator == "In" and present and actual in values)
            or (operator == "NotIn" and (not present or actual not in values))
            or (operator == "Exists" and present)
            or (operator == "DoesNotExist" and not present)
        )
        if not satisfied:
            errors.append(f"{prefix} is not satisfied by Pod-template labels")
    return errors


def _row_errors(row: dict[str, Any]) -> list[str]:
    path = _repo_file(row.get("manifest_path"))
    if path is None:
        return ["manifest_path must reference an existing repository file"]
    if path.suffix.lower() != ".json":
        return ["controller selector satisfaction qualification requires rendered JSON manifest"]
    try:
        payload = _load(path)
    except Exception as exc:
        return [f"rendered JSON manifest is unreadable or invalid ({type(exc).__name__})"]
    docs, errors = _documents(payload)
    workload_count = 0
    for index, obj in enumerate(docs):
        kind = obj.get("kind")
        if kind not in WORKLOAD_KINDS:
            continue
        workload_count += 1
        labels, selector = _template_and_selector(obj)
        if labels is None:
            errors.append(f"workload object {index} has no Pod-template labels")
            continue
        errors.extend(_selector_errors(labels, selector, required=kind in SELECTOR_REQUIRED, label=f"workload object {index} {kind}"))
    if workload_count == 0:
        errors.append("runtime manifest must contain at least one supported workload controller")
    return errors


def _self_test() -> list[str]:
    failures = _policy_errors(_load(POLICY), _load(SOURCE_POLICY))
    labels = {
        "app.kubernetes.io/part-of": "musitu-financial-fabric",
        "app.kubernetes.io/name": "runtime",
        "tier": "backend",
    }
    base_selector = {
        "matchLabels": {
            "app.kubernetes.io/part-of": "musitu-financial-fabric",
            "app.kubernetes.io/name": "runtime",
        }
    }
    good = dict(base_selector)
    good["matchExpressions"] = [
        {"key": "tier", "operator": "In", "values": ["backend"]},
        {"key": "tier", "operator": "NotIn", "values": ["frontend"]},
        {"key": "app.kubernetes.io/name", "operator": "Exists", "values": []},
        {"key": "missing", "operator": "DoesNotExist", "values": []},
    ]
    if _selector_errors(labels, good, required=True, label="self-test"):
        failures.append("valid full LabelSelector satisfaction was rejected")
    bad_cases = [
        {**base_selector, "matchExpressions": [{"key": "app.kubernetes.io/name", "operator": "NotIn", "values": ["runtime"]}]},
        {**base_selector, "matchExpressions": [{"key": "tier", "operator": "In", "values": ["frontend"]}]},
        {**base_selector, "matchExpressions": [{"key": "app.kubernetes.io/name", "operator": "DoesNotExist", "values": []}]},
        {**base_selector, "matchExpressions": [{"key": "missing", "operator": "Exists", "values": []}]},
        {"matchLabels": {**base_selector["matchLabels"], "tier": "frontend"}},
        {**base_selector, "matchExpressions": [{"key": "tier", "operator": "Any", "values": ["backend"]}]},
        {**base_selector, "matchExpressions": [{"key": "tier", "operator": "In", "values": []}]},
        {**base_selector, "source": "synthetic"},
    ]
    for candidate in bad_cases:
        if not _selector_errors(labels, candidate, required=True, label="self-test"):
            failures.append("self-test failed to reject an invalid or contradictory LabelSelector")
    if _selector_errors(labels, None, required=False, label="self-test Job"):
        failures.append("selector-optional workload without selector was rejected")
    return failures


def _contract_errors() -> tuple[list[str], tuple[int, int]]:
    errors = _policy_errors(_load(POLICY), _load(SOURCE_POLICY))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
    defaults = contract.get("defaults_for_unresolved_fields", {})
    runtimes = contract.get("runtimes")
    if not isinstance(runtimes, list):
        return errors + ["runtime contract runtimes must be a list"], (0, 0)
    resolved = 0
    unresolved = 0
    for row in runtimes:
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        ref = row.get("manifest_path", defaults.get("manifest_path"))
        if ref in (None, "", [], {}):
            unresolved += 1
            continue
        row_errors = _row_errors(row)
        if row_errors:
            runtime = str(row.get("key", "unknown"))
            errors.extend(f"{runtime}: {item}" for item in row_errors)
        else:
            resolved += 1
    return errors, (resolved, unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed full LabelSelector satisfaction gate for Kubernetes workload controllers.")
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
        print("PASS: Kubernetes controller selector satisfaction rejects contradictory matchExpressions, matchLabels/template drift, invalid operator/value cardinality, and unsupported selector fields")
        return 0
    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"KUBERNETES CONTROLLER SELECTOR SATISFACTION BLOCKER: {error}")
        return 2
    resolved, unresolved = counts
    print(f"PASS: kubernetes_controller_selector_satisfaction: validated {resolved} resolved manifests; {unresolved} remain unresolved")
    print("BOUNDARY: static controller LabelSelector satisfaction only; it does not prove Kubernetes API admission, controller reconciliation, Pod creation, scheduling, runtime health, deployment, production authorization, or independent validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
