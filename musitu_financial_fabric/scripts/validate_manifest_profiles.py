from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "manifest-profile-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_file(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute():
        return None
    resolved = (ROOT / relative).resolve()
    root = ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["manifest profile policy root must be an object"]
    if policy.get("schema_version") != "mff.manifest-profile-policy.v1":
        errors.append("manifest profile policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("manifest profile policy is not anchored to the sealed runtime release")
    if policy.get("manifest_evidence_schema_version") != "mff.runtime-manifest-evidence.v1":
        errors.append("manifest evidence schema version is invalid")
    if policy.get("manifest_root") != "deploy/musitu-financial-fabric/provider-neutral/manifests":
        errors.append("manifest root policy is invalid")
    if set(policy.get("allowed_manifest_extensions") or []) != {".json", ".yaml", ".yml"}:
        errors.append("manifest extension policy must allow exactly JSON/YAML/YML")
    if policy.get("descriptor_suffix") != ".evidence.json":
        errors.append("manifest descriptor suffix is invalid")
    if policy.get("required_namespace") != "musitu-financial-fabric-target-staging":
        errors.append("manifest namespace policy is invalid")
    if policy.get("benchmark_status_required_for_resolution") != "measured":
        errors.append("manifest policy does not require measured benchmark status")
    if policy.get("rendered_output_required") is not True:
        errors.append("manifest policy does not require rendered output")
    refs = policy.get("required_profile_refs")
    expected_refs = {
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
    }
    if set(refs or []) != expected_refs:
        errors.append("manifest required profile reference set is invalid")
    if policy.get("target_validation_status_required_for_resolution") != "passed":
        errors.append("manifest policy does not require passed target validation")
    return errors


def _manifest_path_errors(key: str, value: object, policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    path = _repo_file(value)
    if path is None:
        return ["manifest_path must reference an existing repository file"]
    relative = Path(_relative(path))
    root = Path(str(policy["manifest_root"]))
    expected_parent = root / key
    if relative.parent != expected_parent:
        errors.append(f"manifest_path must be directly under {expected_parent.as_posix()}")
    if relative.suffix.lower() not in set(policy["allowed_manifest_extensions"]):
        errors.append("manifest_path extension is not allowed")
    if relative.name.endswith(str(policy["descriptor_suffix"])):
        errors.append("manifest_path cannot point to its evidence descriptor")
    return errors


def _target_validation_errors(payload: object, *, environment_id: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["target_validation must be an object"]
    if payload.get("status") != "passed":
        errors.append("target_validation.status must be passed")
    if payload.get("environment_id") != environment_id:
        errors.append("target_validation.environment_id does not match manifest environment_id")
    for field in ("method", "verifier", "trust_model"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"target_validation.{field} is missing")
    evidence = _repo_file(payload.get("evidence_ref"))
    if evidence is None:
        errors.append("target_validation.evidence_ref must reference an existing repository file")
    declared = str(payload.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append("target_validation.evidence_sha256 is missing or malformed")
    elif evidence is not None and _sha256(evidence) != declared:
        errors.append("target_validation evidence SHA-256 does not match retained bytes")
    return errors


def _descriptor_errors(
    key: str,
    row: dict[str, Any],
    manifest_path: Path,
    descriptor: object,
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(descriptor, dict):
        return ["manifest evidence descriptor root must be an object"]
    if descriptor.get("schema_version") != policy.get("manifest_evidence_schema_version"):
        errors.append("manifest evidence schema_version is invalid")
    if descriptor.get("runtime_key") != key:
        errors.append("manifest evidence runtime_key does not match contract row")
    if descriptor.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("manifest evidence is not bound to the sealed runtime release")
    manifest_ref = _relative(manifest_path)
    if descriptor.get("manifest_path") != manifest_ref:
        errors.append("manifest evidence manifest_path does not match exact manifest file")
    declared_manifest_sha = str(descriptor.get("manifest_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared_manifest_sha):
        errors.append("manifest evidence manifest_sha256 is missing or malformed")
    elif _sha256(manifest_path) != declared_manifest_sha:
        errors.append("manifest evidence SHA-256 does not match exact manifest bytes")
    expected_format = manifest_path.suffix.lower().lstrip(".")
    if descriptor.get("manifest_format") != expected_format:
        errors.append("manifest evidence format does not match manifest extension")
    if descriptor.get("rendered_output") is not True:
        errors.append("manifest evidence must declare rendered_output=true")
    if descriptor.get("namespace") != policy.get("required_namespace"):
        errors.append("manifest evidence namespace does not match staging namespace")
    environment_id = descriptor.get("environment_id")
    if not isinstance(environment_id, str) or not environment_id.strip():
        errors.append("manifest evidence environment_id is missing")
        environment_id = ""
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest for manifest binding")
    elif descriptor.get("image_digest") != digest:
        errors.append("manifest evidence image_digest does not match contract row")
    if row.get("benchmark_status") != policy.get("benchmark_status_required_for_resolution"):
        errors.append("contract row benchmark_status is not measured")
    refs = descriptor.get("profile_refs")
    if not isinstance(refs, dict):
        errors.append("manifest evidence profile_refs must be an object")
    else:
        required_refs = list(policy.get("required_profile_refs", []))
        if set(refs) != set(required_refs):
            errors.append("manifest evidence profile_refs key set is invalid")
        for field in required_refs:
            contract_value = row.get(field)
            if contract_value in (None, "", [], {}):
                errors.append(f"contract row has unresolved {field}")
                continue
            if refs.get(field) != contract_value:
                errors.append(f"manifest evidence {field} does not match contract row")
            if _repo_file(contract_value) is None:
                errors.append(f"contract row {field} is not an existing repository file")
    errors.extend(_target_validation_errors(descriptor.get("target_validation"), environment_id=environment_id))
    return errors


def _row_errors(key: str, row: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    value = row.get("manifest_path")
    errors = _manifest_path_errors(key, value, policy)
    manifest_path = _repo_file(value)
    if manifest_path is None or errors:
        return errors
    descriptor_value = f"{_relative(manifest_path)}{policy['descriptor_suffix']}"
    descriptor_path = _repo_file(descriptor_value)
    if descriptor_path is None:
        return errors + ["manifest evidence descriptor is missing"]
    try:
        descriptor = _load(descriptor_path)
    except Exception as exc:
        return errors + [f"manifest evidence descriptor is unreadable or invalid JSON ({type(exc).__name__})"]
    errors.extend(_descriptor_errors(key, row, manifest_path, descriptor, policy))
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    failures = _policy_errors(policy)
    if failures:
        return failures
    key = "__validator_self_test__"
    directory = TARGET / "manifests" / key
    directory.mkdir(parents=True, exist_ok=False)
    try:
        manifest = directory / "workload.yaml"
        manifest.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: manifest-validator-self-test\n", encoding="utf-8")
        evidence = directory / "target-validation.txt"
        evidence.write_text("manifest validator self-test only\n", encoding="utf-8")
        evidence_ref = _relative(evidence)
        profile_ref = evidence_ref
        digest = "sha256:" + ("1" * 64)
        row: dict[str, Any] = {
            "manifest_path": _relative(manifest),
            "image_digest": digest,
            "benchmark_status": "measured",
        }
        for field in policy["required_profile_refs"]:
            row[field] = profile_ref
        descriptor = {
            "schema_version": policy["manifest_evidence_schema_version"],
            "runtime_key": key,
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "manifest_path": _relative(manifest),
            "manifest_sha256": _sha256(manifest),
            "manifest_format": "yaml",
            "rendered_output": True,
            "namespace": policy["required_namespace"],
            "environment_id": "self-test-target",
            "image_digest": digest,
            "profile_refs": {field: profile_ref for field in policy["required_profile_refs"]},
            "target_validation": {
                "status": "passed",
                "environment_id": "self-test-target",
                "method": "validator-self-test",
                "verifier": "validator-self-test",
                "trust_model": "synthetic-self-test-only",
                "evidence_ref": evidence_ref,
                "evidence_sha256": _sha256(evidence),
            },
        }
        descriptor_path = Path(f"{manifest}{policy['descriptor_suffix']}")
        descriptor_path.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if _row_errors(key, row, policy):
            failures.append("valid synthetic manifest evidence was rejected")

        bad_row = dict(row)
        bad_row["manifest_path"] = _relative(POLICY)
        if not _row_errors(key, bad_row, policy):
            failures.append("manifest self-test failed to reject unrelated repository file")

        bad = json.loads(json.dumps(descriptor))
        bad["manifest_sha256"] = "0" * 64
        descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
        if not _row_errors(key, row, policy):
            failures.append("manifest self-test failed to reject manifest byte-hash drift")

        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        bad = json.loads(json.dumps(descriptor))
        bad["profile_refs"]["resource_profile"] = "wrong-resource-profile.json"
        descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
        if not _row_errors(key, row, policy):
            failures.append("manifest self-test failed to reject profile reference drift")

        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        bad = json.loads(json.dumps(descriptor))
        bad["target_validation"]["status"] = "pending"
        descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
        if not _row_errors(key, row, policy):
            failures.append("manifest self-test failed to reject unpassed target validation")

        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        bad = json.loads(json.dumps(descriptor))
        bad["image_digest"] = "sha256:" + ("2" * 64)
        descriptor_path.write_text(json.dumps(bad), encoding="utf-8")
        if not _row_errors(key, row, policy):
            failures.append("manifest self-test failed to reject image drift")

        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        bad_row = dict(row)
        bad_row["benchmark_status"] = "unmeasured"
        if not _row_errors(key, bad_row, policy):
            failures.append("manifest self-test failed to reject unmeasured benchmark state")

        json_manifest = directory / "workload.json"
        json_manifest.write_text('{"apiVersion":"v1","kind":"ConfigMap"}\n', encoding="utf-8")
        json_row = dict(row)
        json_row["manifest_path"] = _relative(json_manifest)
        json_descriptor = json.loads(json.dumps(descriptor))
        json_descriptor["manifest_path"] = _relative(json_manifest)
        json_descriptor["manifest_sha256"] = _sha256(json_manifest)
        json_descriptor["manifest_format"] = "json"
        Path(f"{json_manifest}{policy['descriptor_suffix']}").write_text(json.dumps(json_descriptor), encoding="utf-8")
        if _row_errors(key, json_row, policy):
            failures.append("manifest self-test failed to accept JSON rendered output")
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        manifests_root = TARGET / "manifests"
        try:
            manifests_root.rmdir()
        except OSError:
            pass
    return failures


def _contract_errors() -> tuple[list[str], int, int]:
    policy = _load(POLICY)
    errors = _policy_errors(policy)
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
        value = row.get("manifest_path", defaults.get("manifest_path"))
        if value in (None, "", [], {}):
            unresolved += 1
            continue
        row_copy = dict(row)
        for field, default in defaults.items():
            row_copy.setdefault(field, default)
        row_errors = _row_errors(key, row_copy, policy)
        errors.extend(f"{key}: manifest_path: {error}" for error in row_errors)
        if not row_errors:
            resolved += 1
    return errors, resolved, unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral runtime manifest evidence.")
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
        print("PASS: manifest validator accepts rendered JSON/YAML byte bindings and rejects unrelated files, profile drift, image drift, unmeasured state, and unpassed target evidence")
        return 0
    errors, resolved, unresolved = _contract_errors()
    if errors:
        for error in errors:
            print(f"MANIFEST PROFILE BLOCKER: {error}")
        return 2
    print(f"PASS: manifest_path: validated {resolved} resolved manifests; {unresolved} remain unresolved")
    print("BOUNDARY: no workload kind, YAML semantics, Kubernetes admission, target health, or deployment is inferred from unresolved manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
