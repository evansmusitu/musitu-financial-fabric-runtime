from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
SOURCE_POLICY = TARGET / "kubernetes-manifest-semantics-policy.json"
POLICY = TARGET / "kubernetes-workload-binding-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.kubernetes-workload-binding-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.kubernetes-manifest-semantics-policy.v1"
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
SELECTOR_REQUIRED = {"Deployment", "StatefulSet", "DaemonSet"}
SELECTOR_OPTIONAL = {"Job", "CronJob"}


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
        return ["Kubernetes workload binding policy root must be an object"]
    expected = {
        "schema_version": POLICY_SCHEMA,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "source_manifest_semantics_policy_schema_version": SOURCE_POLICY_SCHEMA,
        "required_namespace": "musitu-financial-fabric-target-staging",
        "required_part_of_label": {"key": "app.kubernetes.io/part-of", "value": "musitu-financial-fabric"},
        "required_runtime_label_key": "app.kubernetes.io/name",
        "selector_required_kinds": sorted(SELECTOR_REQUIRED),
        "selector_optional_kinds": sorted(SELECTOR_OPTIONAL),
    }
    errors: list[str] = []
    for field, expected_value in expected.items():
        actual = policy.get(field)
        if field in {"selector_required_kinds", "selector_optional_kinds"}:
            actual = sorted(actual) if isinstance(actual, list) else actual
        if actual != expected_value:
            errors.append(f"Kubernetes workload binding policy {field} is invalid")
    if not isinstance(source, dict):
        return errors + ["source Kubernetes manifest semantics policy root must be an object"]
    if source.get("schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("source Kubernetes manifest semantics policy schema drifted")
    if source.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source Kubernetes manifest semantics policy is not anchored to the sealed runtime release")
    if source.get("required_namespace") != policy.get("required_namespace"):
        errors.append("workload binding namespace drifted from source manifest policy")
    if source.get("required_part_of_label") != policy.get("required_part_of_label"):
        errors.append("workload binding part-of label drifted from source manifest policy")
    if source.get("required_runtime_label_key") != policy.get("required_runtime_label_key"):
        errors.append("workload binding runtime label drifted from source manifest policy")
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


def _template(obj: dict[str, Any]) -> dict[str, Any] | None:
    kind = obj.get("kind")
    spec = obj.get("spec")
    if not isinstance(spec, dict):
        return None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        value = spec.get("template")
        return value if isinstance(value, dict) else None
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else None
        value = job_spec.get("template") if isinstance(job_spec, dict) else None
        return value if isinstance(value, dict) else None
    return None


def _selector(obj: dict[str, Any]) -> object:
    kind = obj.get("kind")
    spec = obj.get("spec")
    if not isinstance(spec, dict):
        return None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        return spec.get("selector")
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else None
        return job_spec.get("selector") if isinstance(job_spec, dict) else None
    return None


def _identity(policy: dict[str, Any], key: str) -> dict[str, str]:
    part = policy["required_part_of_label"]
    return {part["key"]: part["value"], policy["required_runtime_label_key"]: key}


def _binding_errors(key: str, obj: dict[str, Any], index: int, policy: dict[str, Any]) -> list[str]:
    kind = obj.get("kind")
    if kind not in WORKLOAD_KINDS:
        return []
    errors: list[str] = []
    expected = _identity(policy, key)
    template = _template(obj)
    if template is None:
        return [f"workload object {index} has no supported PodTemplateSpec"]
    metadata = template.get("metadata")
    if not isinstance(metadata, dict):
        return [f"workload object {index} Pod template metadata must be an object"]
    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        return [f"workload object {index} Pod template labels must be an object"]
    for label_key, value in expected.items():
        if labels.get(label_key) != value:
            errors.append(f"workload object {index} Pod template label {label_key} does not match runtime identity")

    selector = _selector(obj)
    if kind in SELECTOR_REQUIRED and not isinstance(selector, dict):
        errors.append(f"workload object {index} {kind} selector must be an object")
        return errors
    if selector is None:
        return errors
    if not isinstance(selector, dict):
        return errors + [f"workload object {index} selector must be an object when provided"]
    match_labels = selector.get("matchLabels")
    if not isinstance(match_labels, dict):
        return errors + [f"workload object {index} selector.matchLabels must be an object"]
    for label_key, value in expected.items():
        if match_labels.get(label_key) != value:
            errors.append(f"workload object {index} selector label {label_key} does not match runtime identity")
        if labels.get(label_key) != match_labels.get(label_key):
            errors.append(f"workload object {index} selector/template label {label_key} mismatch")
    return errors


def _row_errors(key: str, row: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    path = _repo_file(row.get("manifest_path"))
    if path is None:
        return ["manifest_path must reference an existing repository file"]
    if path.suffix.lower() != ".json":
        return ["Kubernetes workload binding qualification requires rendered JSON manifest"]
    try:
        payload = _load(path)
    except Exception as exc:
        return [f"rendered JSON manifest is unreadable or invalid ({type(exc).__name__})"]
    docs, errors = _documents(payload)
    workload_count = 0
    for index, obj in enumerate(docs):
        if obj.get("kind") in WORKLOAD_KINDS:
            workload_count += 1
        errors.extend(_binding_errors(key, obj, index, policy))
    if workload_count == 0:
        errors.append("runtime manifest must contain at least one supported workload controller")
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source)
    if failures:
        return failures
    key = "__workload_binding_self_test__"
    directory = TARGET / "manifests" / key
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "workload.json"
    row = {"manifest_path": path.relative_to(ROOT).as_posix()}
    identity = _identity(policy, key)

    def base() -> dict[str, Any]:
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "binding-self-test", "labels": dict(identity)},
            "spec": {
                "selector": {"matchLabels": dict(identity)},
                "template": {
                    "metadata": {"labels": dict(identity)},
                    "spec": {"containers": [{"name": "runtime", "image": "example.invalid/runtime@sha256:" + "1" * 64}]},
                },
            },
        }

    try:
        path.write_text(json.dumps(base()), encoding="utf-8")
        if _row_errors(key, row, policy):
            failures.append("valid synthetic workload identity binding was rejected")
        cases: list[tuple[str, dict[str, Any]]] = []
        bad = base()
        del bad["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/part-of"]
        cases.append(("missing Pod-template part-of label", bad))
        bad = base()
        bad["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"] = "wrong"
        cases.append(("Pod-template runtime label drift", bad))
        bad = base()
        bad["spec"]["selector"]["matchLabels"]["app.kubernetes.io/name"] = "wrong"
        cases.append(("controller selector runtime drift", bad))
        bad = base()
        del bad["spec"]["selector"]["matchLabels"]["app.kubernetes.io/part-of"]
        cases.append(("controller selector missing part-of identity", bad))
        bad = base()
        del bad["spec"]["selector"]
        cases.append(("required controller selector missing", bad))
        for label, candidate in cases:
            path.write_text(json.dumps(candidate), encoding="utf-8")
            if not _row_errors(key, row, policy):
                failures.append(f"self-test failed to reject {label}")
        job = base()
        job["apiVersion"] = "batch/v1"
        job["kind"] = "Job"
        del job["spec"]["selector"]
        path.write_text(json.dumps(job), encoding="utf-8")
        if _row_errors(key, row, policy):
            failures.append("self-test rejected Job with runtime-bound template and omitted API-generated selector")
        return failures
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            (TARGET / "manifests").rmdir()
        except OSError:
            pass


def _contract_errors() -> tuple[list[str], tuple[int, int]]:
    policy = _load(POLICY)
    source = _load(SOURCE_POLICY)
    errors = _policy_errors(policy, source)
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        return errors + ["runtime contract is not anchored to the sealed release"], (0, 0)
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
        key = str(row.get("key", "unknown"))
        ref = row.get("manifest_path", defaults.get("manifest_path"))
        if ref in (None, "", [], {}):
            unresolved += 1
            continue
        row_errors = _row_errors(key, row, policy)
        if row_errors:
            errors.extend(f"{key}: {item}" for item in row_errors)
        else:
            resolved += 1
    return errors, (resolved, unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed controller-to-Pod workload identity binding validator.")
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
        print("PASS: Kubernetes workload binding rejects Pod-template identity drift and controller selector/runtime mismatches")
        return 0
    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"KUBERNETES WORKLOAD BINDING BLOCKER: {error}")
        return 2
    resolved, unresolved = counts
    print(f"PASS: kubernetes_workload_binding: validated {resolved} resolved manifests; {unresolved} remain unresolved")
    print("BOUNDARY: static controller-to-Pod identity binding only; it does not prove API admission, controller reconciliation, scheduler placement, runtime health, deployment, production authorization, or independent validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
