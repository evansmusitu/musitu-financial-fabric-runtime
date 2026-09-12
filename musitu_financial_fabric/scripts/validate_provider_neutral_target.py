from __future__ import annotations

import argparse
import json
import re
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
EXPECTED_COUNT = 26
EXPECTED_NAMESPACE = "musitu-financial-fabric-target-staging"
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
    if contract.get("expected_required_runtime_count") != EXPECTED_COUNT:
        errors.append("contract expected runtime count is not 26")
    if len(rows) != EXPECTED_COUNT or len(set(keys)) != EXPECTED_COUNT:
        errors.append("contract does not contain exactly 26 unique runtime rows")
    if set(contract_map) != set(authoritative):
        errors.append("contract runtime keys do not exactly match authoritative required-runtime keys")
    for key, expected_env in authoritative.items():
        if contract_map.get(key) != expected_env:
            errors.append(f"{key}: health_env does not match authoritative registry")

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
    if not BENCHMARK.is_file():
        errors.append("resource benchmark plan is missing")
    else:
        benchmark = _load(BENCHMARK)
        if benchmark.get("benchmark_status_required_for_deployability") != "measured":
            errors.append("benchmark plan does not require measured status")

    return errors


def deployability_blockers() -> list[str]:
    blockers = validate_structure()
    if blockers:
        return blockers

    contract = _load(CONTRACT)
    defaults = contract.get("defaults_for_unresolved_fields", {})
    if any(defaults.get(field) is not None for field in DEPLOYMENT_FIELDS):
        blockers.append("contract unresolved defaults are not null")
    if defaults.get("benchmark_status") != "unmeasured":
        blockers.append("contract unresolved benchmark default is not unmeasured")

    for row in contract.get("runtimes", []):
        key = str(row.get("key", "unknown"))
        for field in DEPLOYMENT_FIELDS:
            value = row.get(field, defaults.get(field))
            if value in (None, "", [], {}):
                blockers.append(f"{key}: unresolved {field}")
        digest = row.get("image_digest", defaults.get("image_digest"))
        if digest not in (None, "") and not OCI_DIGEST.fullmatch(str(digest)):
            blockers.append(f"{key}: image_digest is not immutable sha256")
        status = row.get("benchmark_status", defaults.get("benchmark_status"))
        if status != "measured":
            blockers.append(f"{key}: benchmark_status is not measured")

    quota = _load(QUOTA)
    if quota.get("spec", {}).get("hard", {}).get("pods") == "0":
        blockers.append("foundation: zero-pod fail-closed quota still active")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the MUSITU provider-neutral target staging contract.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--structure", action="store_true")
    mode.add_argument("--deployable", action="store_true")
    args = parser.parse_args()

    if args.structure:
        errors = validate_structure()
        if errors:
            for error in errors:
                print(f"STRUCTURE BLOCKER: {error}")
            return 2
        print("PASS: exact 26-runtime contract and fail-closed provider-neutral foundation are structurally valid")
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
