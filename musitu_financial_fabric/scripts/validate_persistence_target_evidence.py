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
POLICY = TARGET / "persistence-target-evidence-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.persistence-target-evidence-policy.v1"
PROFILE_SCHEMA = "mff.persistence-profile.v1"
DESCRIPTOR_SCHEMA = "mff.persistence-target-validation.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
COMMON_DIRECT_BINDINGS = [
    "runtime_key",
    "authoritative_runtime_base_commit",
    "image_digest",
    "environment_id",
    "classification",
    "method",
    "verifier",
    "trust_model",
]
STATEFUL_HASHED_BINDINGS = [
    "storage",
    "durability",
    "encryption_at_rest",
    "retention",
    "backup_restore_profile_ref",
    "recovery_objectives",
    "data_integrity_validation",
]
STATELESS_HASHED_BINDINGS = [
    "ephemeral_state_only",
    "reconstruction_source",
    "rationale",
]


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["persistence target-evidence policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("persistence target-evidence policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("persistence target-evidence policy is not anchored to the sealed runtime release")
    if policy.get("persistence_profile_schema_version") != PROFILE_SCHEMA:
        errors.append("persistence profile schema version is invalid")
    if policy.get("descriptor_schema_version") != DESCRIPTOR_SCHEMA:
        errors.append("persistence target-validation descriptor schema version is invalid")
    if set(policy.get("allowed_classifications") or []) != {"stateful", "stateless"}:
        errors.append("persistence target-evidence classification set is invalid")
    if policy.get("common_direct_bindings") != COMMON_DIRECT_BINDINGS:
        errors.append("persistence target-evidence common direct bindings are invalid")
    if policy.get("stateful_hashed_bindings") != STATEFUL_HASHED_BINDINGS:
        errors.append("persistence target-evidence stateful bindings are invalid")
    if policy.get("stateless_hashed_bindings") != STATELESS_HASHED_BINDINGS:
        errors.append("persistence target-evidence stateless bindings are invalid")
    return errors


def _evidence_errors(payload: object) -> tuple[list[str], Path | None]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["target_validation must be an object"], None
    if payload.get("status") != "passed":
        errors.append("target_validation.status must be passed")
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
    return errors, evidence


def _profile_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["persistence profile root must be an object"]
    if payload.get("schema_version") != policy.get("persistence_profile_schema_version"):
        errors.append("persistence profile schema_version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("persistence profile runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("persistence profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest for persistence evidence binding")
    elif payload.get("image_digest") != digest:
        errors.append("persistence profile image_digest does not match contract row")
    environment = payload.get("environment_id")
    if not isinstance(environment, str) or not environment.strip():
        errors.append("persistence profile environment_id is missing")
    classification = payload.get("classification")
    if classification not in set(policy.get("allowed_classifications") or []):
        errors.append("persistence profile classification is invalid")
    elif classification == "stateful":
        for field in policy.get("stateful_hashed_bindings", []):
            if payload.get(field) in (None, "", [], {}):
                errors.append(f"stateful persistence profile missing {field}")
    elif classification == "stateless":
        if payload.get("ephemeral_state_only") is not True:
            errors.append("stateless persistence profile must assert ephemeral_state_only=true")
        if payload.get("reconstruction_source") in (None, "", [], {}):
            errors.append("stateless persistence profile reconstruction_source is missing")
        if not isinstance(payload.get("rationale"), str) or not payload["rationale"].strip():
            errors.append("stateless persistence profile rationale is missing")

    evidence_errors, evidence_path = _evidence_errors(payload.get("target_validation"))
    errors.extend(evidence_errors)
    if evidence_path is None:
        return errors
    try:
        descriptor = _load(evidence_path)
    except Exception as exc:
        errors.append(f"target_validation evidence must be a JSON persistence descriptor ({type(exc).__name__})")
        return errors
    if not isinstance(descriptor, dict):
        return errors + ["persistence target-validation descriptor root must be an object"]
    if descriptor.get("schema_version") != policy.get("descriptor_schema_version"):
        errors.append("persistence target-validation descriptor schema_version is invalid")

    target_validation = payload.get("target_validation")
    direct = {
        "runtime_key": key,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": payload.get("image_digest"),
        "environment_id": environment,
        "classification": classification,
        "method": target_validation.get("method") if isinstance(target_validation, dict) else None,
        "verifier": target_validation.get("verifier") if isinstance(target_validation, dict) else None,
        "trust_model": target_validation.get("trust_model") if isinstance(target_validation, dict) else None,
    }
    for field in policy.get("common_direct_bindings", []):
        if field not in descriptor:
            errors.append(f"persistence target-validation descriptor missing {field}")
        elif descriptor.get(field) != direct.get(field):
            errors.append(f"persistence target-validation descriptor {field} does not match persistence profile")

    if classification == "stateful":
        hashed = policy.get("stateful_hashed_bindings", [])
    elif classification == "stateless":
        hashed = policy.get("stateless_hashed_bindings", [])
    else:
        hashed = []

    for field in hashed:
        descriptor_field = f"{field}_sha256"
        declared = str(descriptor.get(descriptor_field, "")).strip().lower()
        if not SHA256_HEX.fullmatch(declared):
            errors.append(f"persistence target-validation descriptor {descriptor_field} is missing or malformed")
            continue
        try:
            expected = _canonical_sha256(payload.get(field))
        except (TypeError, ValueError):
            errors.append(f"persistence profile {field} is not canonical-JSON hashable")
            continue
        if declared != expected:
            errors.append(f"persistence target-validation descriptor {descriptor_field} does not match persistence profile")
    return errors


def _write_json(path: Path, payload: object) -> str:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return _sha256(path)


def _self_test() -> list[str]:
    policy = _load(POLICY)
    failures = _policy_errors(policy)
    if failures:
        return failures
    digest = "sha256:" + ("1" * 64)
    row = {"image_digest": digest}
    descriptor_path = ROOT / ".mff-persistence-target-validation-self-test.tmp.json"

    def build_profile(classification: str) -> dict[str, Any]:
        base = {
            "schema_version": PROFILE_SCHEMA,
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "environment_id": "self-test-target",
            "classification": classification,
        }
        if classification == "stateful":
            base.update({
                "storage": {"kind": "synthetic-self-test"},
                "durability": "synthetic-self-test",
                "encryption_at_rest": "synthetic-self-test",
                "retention": "synthetic-self-test",
                "backup_restore_profile_ref": "synthetic/recovery.json",
                "recovery_objectives": {"rpo": "synthetic", "rto": "synthetic"},
                "data_integrity_validation": {"method": "synthetic-self-test"},
            })
        else:
            base.update({
                "ephemeral_state_only": True,
                "reconstruction_source": {"kind": "synthetic-self-test"},
                "rationale": "synthetic self-test only",
            })
        return base

    def descriptor_for(profile: dict[str, Any]) -> dict[str, Any]:
        descriptor = {
            "schema_version": DESCRIPTOR_SCHEMA,
            "runtime_key": profile["runtime_key"],
            "authoritative_runtime_base_commit": profile["authoritative_runtime_base_commit"],
            "image_digest": profile["image_digest"],
            "environment_id": profile["environment_id"],
            "classification": profile["classification"],
            "method": "validator-self-test",
            "verifier": "validator-self-test",
            "trust_model": "synthetic-self-test-only",
        }
        fields = STATEFUL_HASHED_BINDINGS if profile["classification"] == "stateful" else STATELESS_HASHED_BINDINGS
        for field in fields:
            descriptor[f"{field}_sha256"] = _canonical_sha256(profile.get(field))
        return descriptor

    try:
        for classification in ("stateful", "stateless"):
            profile = build_profile(classification)
            descriptor = descriptor_for(profile)
            evidence_sha = _write_json(descriptor_path, descriptor)
            profile["target_validation"] = {
                "status": "passed",
                "method": descriptor["method"],
                "verifier": descriptor["verifier"],
                "trust_model": descriptor["trust_model"],
                "evidence_ref": descriptor_path.relative_to(ROOT).as_posix(),
                "evidence_sha256": evidence_sha,
            }
            if _profile_errors("self-test", row, profile, policy):
                failures.append(f"valid synthetic {classification} persistence target descriptor was rejected")

            mutations = [
                ("runtime", "runtime_key", "wrong-runtime"),
                ("sealed release", "authoritative_runtime_base_commit", "0" * 40),
                ("image digest", "image_digest", "sha256:" + ("2" * 64)),
                ("environment", "environment_id", "wrong-target"),
                ("classification", "classification", "stateless" if classification == "stateful" else "stateful"),
                ("verification method", "method", "different-method"),
            ]
            for label, field, value in mutations:
                bad_descriptor = dict(descriptor)
                bad_descriptor[field] = value
                bad = json.loads(json.dumps(profile))
                bad["target_validation"]["evidence_sha256"] = _write_json(descriptor_path, bad_descriptor)
                if not _profile_errors("self-test", row, bad, policy):
                    failures.append(f"persistence target self-test failed to reject descriptor {label} drift")

            hashed_fields = STATEFUL_HASHED_BINDINGS if classification == "stateful" else STATELESS_HASHED_BINDINGS
            field = hashed_fields[0]
            bad_descriptor = dict(descriptor)
            bad_descriptor[f"{field}_sha256"] = "0" * 64
            bad = json.loads(json.dumps(profile))
            bad["target_validation"]["evidence_sha256"] = _write_json(descriptor_path, bad_descriptor)
            if not _profile_errors("self-test", row, bad, policy):
                failures.append(f"persistence target self-test failed to reject {classification} semantic hash drift")

            _write_json(descriptor_path, descriptor)
            bad = json.loads(json.dumps(profile))
            bad["target_validation"]["evidence_sha256"] = "0" * 64
            if not _profile_errors("self-test", row, bad, policy):
                failures.append("persistence target self-test failed to reject retained-byte hash mismatch")

        return failures
    finally:
        descriptor_path.unlink(missing_ok=True)


def _contract_errors() -> tuple[list[str], int, int]:
    errors: list[str] = []
    policy = _load(POLICY)
    errors.extend(_policy_errors(policy))
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
        ref = row.get("persistence_profile", defaults.get("persistence_profile"))
        if ref in (None, "", [], {}):
            unresolved += 1
            continue
        path = _repo_file(ref)
        if path is None:
            errors.append(f"{key}: persistence_profile is not an existing repository file")
            continue
        try:
            payload = _load(path)
        except Exception as exc:
            errors.append(f"{key}: persistence profile is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        profile_errors = _profile_errors(key, row, payload, policy)
        errors.extend(f"{key}: persistence_target_evidence: {error}" for error in profile_errors)
        if not profile_errors:
            resolved += 1
    return errors, resolved, unresolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate provider-neutral persistence target-evidence descriptors."
    )
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
            "PASS: persistence target-evidence validator rejects byte-valid but semantically "
            "unbound stateful/stateless descriptors and retained-byte drift"
        )
        return 0

    errors, resolved, unresolved = _contract_errors()
    if errors:
        for error in errors:
            print(f"PERSISTENCE TARGET EVIDENCE BLOCKER: {error}")
        return 2
    print(
        f"PASS: persistence_target_evidence: validated {resolved} resolved profiles; "
        f"{unresolved} remain unresolved"
    )
    print(
        "BOUNDARY: unresolved persistence evidence does not establish statefulness, storage behavior, "
        "restore success, Kubernetes admission, target health, deployment, or production authorization"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
