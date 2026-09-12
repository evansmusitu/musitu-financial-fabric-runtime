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
SOURCE_POLICY = TARGET / "recovery-profile-policy.json"
POLICY = TARGET / "recovery-design-evidence-policy.json"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.recovery-design-evidence-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.recovery-profile-policy.v2"
PROFILE_SCHEMA = "mff.runtime-recovery-profile.v1"
PROCEDURE_SCHEMA = "mff.recovery-procedure.v1"
PROJECTION = "canonical_profile_without_restore_or_restart_procedure_sha256"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_OBLIGATIONS = {
    "postgres": {
        "profile_mode": "backup_restore",
        "target_evidence_key": "postgres_backup_restore",
    },
    "tigerbeetle": {
        "profile_mode": "recovery",
        "target_evidence_key": "tigerbeetle_recovery",
    },
}
REQUIRED_SECTIONS = [
    "preconditions",
    "steps",
    "success_criteria",
    "integrity_verification",
    "failure_handling",
    "rollback_or_restart",
]
STEP_REQUIRED_FIELDS = ["step_id", "action", "verification"]
REQUIRED_METADATA = ["validation_method", "verifier", "trust_model"]


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


def _profile_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != "restore_or_restart_procedure_sha256"
    }


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _policy_errors(policy: object, source_policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["recovery design-evidence policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("recovery design-evidence policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("recovery design-evidence policy is not anchored to the sealed runtime release")
    if policy.get("source_recovery_policy_schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("recovery design-evidence source policy schema is invalid")
    if policy.get("recovery_profile_schema_version") != PROFILE_SCHEMA:
        errors.append("recovery design-evidence profile schema is invalid")
    if policy.get("procedure_schema_version") != PROCEDURE_SCHEMA:
        errors.append("recovery procedure schema is invalid")
    if policy.get("profile_semantics_projection") != PROJECTION:
        errors.append("recovery design-evidence profile projection is invalid")
    if policy.get("scoped_obligations") != EXPECTED_OBLIGATIONS:
        errors.append("recovery design-evidence scoped obligations are invalid")
    if policy.get("procedure_required_sections") != REQUIRED_SECTIONS:
        errors.append("recovery procedure required sections are invalid")
    if policy.get("step_required_fields") != STEP_REQUIRED_FIELDS:
        errors.append("recovery procedure step fields are invalid")
    if policy.get("procedure_required_metadata") != REQUIRED_METADATA:
        errors.append("recovery procedure validation metadata policy is invalid")

    if not isinstance(source_policy, dict):
        return errors + ["source recovery policy root must be an object"]
    if source_policy.get("schema_version") != policy.get("source_recovery_policy_schema_version"):
        errors.append("recovery design-evidence policy does not match source recovery policy schema")
    if source_policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source recovery policy is not anchored to the sealed runtime release")
    if source_policy.get("profile_schema_version") != PROFILE_SCHEMA:
        errors.append("source recovery profile schema drifted")
    if source_policy.get("scoped_obligations") != EXPECTED_OBLIGATIONS:
        errors.append("source recovery scoped obligations drifted")
    return errors


def _structured_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _procedure_errors(
    key: str,
    row: dict[str, Any],
    profile: object,
    obligation: dict[str, str],
    policy: dict[str, Any],
    source_policy_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["recovery profile root must be an object"]
    if profile.get("schema_version") != PROFILE_SCHEMA:
        errors.append("recovery profile schema_version is invalid")
    if profile.get("runtime_key") != key:
        errors.append("recovery profile runtime_key does not match contract row")
    if profile.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("recovery profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest for recovery design evidence")
    elif profile.get("image_digest") != digest:
        errors.append("recovery profile image_digest does not match contract row")
    if profile.get("profile_mode") != obligation["profile_mode"]:
        errors.append("recovery profile_mode does not match scoped obligation")
    if profile.get("target_evidence_key") != obligation["target_evidence_key"]:
        errors.append("recovery target_evidence_key does not match scoped obligation")
    if profile.get("evidence_status") != "design_only_unexecuted":
        errors.append("recovery profile must remain design_only_unexecuted")
    if profile.get("target_execution_evidence_required") is not True:
        errors.append("recovery profile must require separate target execution evidence")

    procedure = _repo_file(profile.get("restore_or_restart_procedure_ref"))
    if procedure is None:
        errors.append("restore_or_restart_procedure_ref must reference an existing repository file")
        return errors

    declared = str(profile.get("restore_or_restart_procedure_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append("restore_or_restart_procedure_sha256 is missing or malformed")
    elif _sha256(procedure) != declared:
        errors.append("restore/restart procedure SHA-256 does not match retained bytes")

    try:
        procedure_payload = _load(procedure)
    except Exception as exc:
        errors.append(f"restore/restart procedure must be structured JSON ({type(exc).__name__})")
        return errors
    if not isinstance(procedure_payload, dict):
        return errors + ["recovery procedure root must be an object"]

    direct = {
        "schema_version": policy.get("procedure_schema_version"),
        "runtime_key": key,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": profile.get("image_digest"),
        "recovery_profile_schema_version": profile.get("schema_version"),
        "profile_mode": profile.get("profile_mode"),
        "target_evidence_key": profile.get("target_evidence_key"),
        "manifest_path": profile.get("manifest_path"),
        "persistence_profile": profile.get("persistence_profile"),
        "source_recovery_policy_sha256": source_policy_sha256,
        "execution_status": "design_only_unexecuted",
    }
    for field, expected in direct.items():
        if procedure_payload.get(field) != expected:
            errors.append(f"recovery procedure {field} does not match recovery design authority")

    declared_design = str(procedure_payload.get("recovery_design_semantics_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared_design):
        errors.append("recovery procedure recovery_design_semantics_sha256 is missing or malformed")
    else:
        try:
            expected_design = _canonical_sha256(_profile_projection(profile))
        except (TypeError, ValueError):
            errors.append("recovery design is not canonical-JSON hashable")
        else:
            if declared_design != expected_design:
                errors.append("recovery procedure semantic hash does not match recovery design")

    if not _structured_list(procedure_payload.get("preconditions")):
        errors.append("recovery procedure preconditions must be a non-empty list of strings")
    steps = procedure_payload.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("recovery procedure steps must be a non-empty list")
    else:
        seen: set[str] = set()
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"recovery procedure step {index} must be an object")
                continue
            for field in STEP_REQUIRED_FIELDS:
                if not isinstance(step.get(field), str) or not step[field].strip():
                    errors.append(f"recovery procedure step {index}.{field} is missing")
            step_id = step.get("step_id")
            if isinstance(step_id, str) and step_id.strip():
                if step_id in seen:
                    errors.append(f"recovery procedure duplicate step_id: {step_id}")
                seen.add(step_id)

    if not _structured_list(procedure_payload.get("success_criteria")):
        errors.append("recovery procedure success_criteria must be a non-empty list of strings")
    for field in ("integrity_verification", "failure_handling", "rollback_or_restart"):
        if not _nonempty(procedure_payload.get(field)):
            errors.append(f"recovery procedure {field} is missing")
    for field in REQUIRED_METADATA:
        if not isinstance(procedure_payload.get(field), str) or not procedure_payload[field].strip():
            errors.append(f"recovery procedure {field} is missing")
    return errors


def _write_json(path: Path, payload: object) -> str:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return _sha256(path)


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source_policy)
    if failures:
        return failures

    digest = "sha256:" + ("1" * 64)
    obligation = EXPECTED_OBLIGATIONS["postgres"]
    procedure_path = ROOT / ".mff-recovery-procedure-self-test.json"
    unrelated_path = ROOT / ".mff-recovery-procedure-unrelated-self-test.json"
    profile: dict[str, Any] = {
        "schema_version": PROFILE_SCHEMA,
        "runtime_key": "postgres",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "manifest_path": "deploy/self-test-manifest.json",
        "persistence_profile": "deploy/self-test-persistence.json",
        "profile_mode": obligation["profile_mode"],
        "target_evidence_key": obligation["target_evidence_key"],
        "evidence_status": "design_only_unexecuted",
        "target_execution_evidence_required": True,
        "rpo_target": "self-test",
        "rto_target": "self-test",
        "backup_or_recovery_method": "self-test",
        "encryption_at_rest": "self-test",
        "retention_or_replication_policy": "self-test",
        "restore_or_restart_procedure_ref": procedure_path.relative_to(ROOT).as_posix(),
        "restore_or_restart_procedure_sha256": "",
        "integrity_verification_method": "self-test",
        "failure_scenarios": ["self-test failure"],
    }
    row = {"image_digest": digest}
    source_policy_sha = _sha256(SOURCE_POLICY)

    def make_procedure(source: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": PROCEDURE_SCHEMA,
            "runtime_key": source["runtime_key"],
            "authoritative_runtime_base_commit": source["authoritative_runtime_base_commit"],
            "image_digest": source["image_digest"],
            "recovery_profile_schema_version": source["schema_version"],
            "profile_mode": source["profile_mode"],
            "target_evidence_key": source["target_evidence_key"],
            "manifest_path": source["manifest_path"],
            "persistence_profile": source["persistence_profile"],
            "source_recovery_policy_sha256": source_policy_sha,
            "recovery_design_semantics_sha256": _canonical_sha256(_profile_projection(source)),
            "execution_status": "design_only_unexecuted",
            "preconditions": ["synthetic precondition"],
            "steps": [
                {
                    "step_id": "step-1",
                    "action": "synthetic recovery action",
                    "verification": "synthetic verification",
                }
            ],
            "success_criteria": ["synthetic success"],
            "integrity_verification": {"method": "synthetic-self-test"},
            "failure_handling": {"method": "synthetic-self-test"},
            "rollback_or_restart": {"method": "synthetic-self-test"},
            "validation_method": "validator-self-test",
            "verifier": "validator-self-test",
            "trust_model": "synthetic-self-test-only",
        }

    try:
        procedure = make_procedure(profile)
        profile["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, procedure)
        if _procedure_errors("postgres", row, profile, obligation, policy, source_policy_sha):
            failures.append("valid synthetic recovery procedure was rejected")

        bad = dict(procedure)
        bad["runtime_key"] = "wrong-runtime"
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, bad)
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject procedure runtime drift")

        bad = dict(procedure)
        bad["source_recovery_policy_sha256"] = "0" * 64
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, bad)
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject source-policy drift")

        bad = dict(procedure)
        bad["execution_status"] = "executed"
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, bad)
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject executed-status claim")

        bad = dict(procedure)
        bad["steps"] = []
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, bad)
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject empty procedure steps")

        _write_json(procedure_path, procedure)
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_sha256"] = "0" * 64
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject procedure retained-byte drift")

        changed = json.loads(json.dumps(profile))
        changed["rpo_target"] = "changed-after-procedure"
        changed["restore_or_restart_procedure_sha256"] = _write_json(procedure_path, procedure)
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject recovery-design semantic drift")

        unrelated = dict(procedure)
        unrelated["runtime_key"] = "tigerbeetle"
        unrelated["profile_mode"] = "recovery"
        unrelated["target_evidence_key"] = "tigerbeetle_recovery"
        unrelated_ref = unrelated_path.relative_to(ROOT).as_posix()
        unrelated_sha = _write_json(unrelated_path, unrelated)
        changed = json.loads(json.dumps(profile))
        changed["restore_or_restart_procedure_ref"] = unrelated_ref
        changed["restore_or_restart_procedure_sha256"] = unrelated_sha
        if not _procedure_errors("postgres", row, changed, obligation, policy, source_policy_sha):
            failures.append("self-test failed to reject unrelated structured procedure substitution")
        return failures
    finally:
        procedure_path.unlink(missing_ok=True)
        unrelated_path.unlink(missing_ok=True)


def _contract_errors() -> tuple[list[str], tuple[int, int]]:
    errors: list[str] = []
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    errors.extend(_policy_errors(policy, source_policy))
    source_policy_sha = _sha256(SOURCE_POLICY)
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, (0, 0)

    rows = {
        str(row.get("key")): row
        for row in contract.get("runtimes", [])
        if isinstance(row, dict)
    }
    defaults = contract.get("defaults_for_unresolved_fields", {})
    resolved = 0
    unresolved = 0
    for key, obligation in EXPECTED_OBLIGATIONS.items():
        row = rows.get(key)
        if not isinstance(row, dict):
            errors.append(f"scoped recovery runtime is missing from contract: {key}")
            continue
        profile_ref = row.get("backup_restore_profile", defaults.get("backup_restore_profile"))
        if profile_ref in (None, "", [], {}):
            unresolved += 1
            continue
        profile_path = _repo_file(profile_ref)
        if profile_path is None:
            errors.append(f"{key}: backup_restore_profile is not an existing repository file")
            continue
        try:
            profile = _load(profile_path)
        except Exception as exc:
            errors.append(f"{key}: recovery profile is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        profile_errors = _procedure_errors(
            key, row, profile, obligation, policy, source_policy_sha
        )
        if profile_errors:
            errors.extend(f"{key}: {item}" for item in profile_errors)
        else:
            resolved += 1
    return errors, (resolved, unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed scoped recovery design-evidence association validator."
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
            "PASS: recovery design-evidence validator rejects unrelated structured procedures, "
            "source-policy drift, retained-byte drift, executed-status claims, incomplete procedure "
            "structure, and post-procedure recovery-design drift"
        )
        return 0

    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"RECOVERY DESIGN EVIDENCE BLOCKER: {error}")
        return 2
    resolved, unresolved = counts
    print(
        f"PASS: scoped_recovery_design_evidence: validated {resolved} resolved profiles; "
        f"{unresolved} scoped obligations remain unresolved"
    )
    print(
        "BOUNDARY: recovery procedure evidence is static design evidence only; it does not prove "
        "a restore/restart drill, target execution, recovery success, deployment, production "
        "authorization, or independent validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
