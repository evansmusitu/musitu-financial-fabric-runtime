from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "recovery-profile-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.recovery-profile-policy.v1"
PROFILE_SCHEMA = "mff.runtime-recovery-profile.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_OBLIGATIONS = {
    "postgres": {"profile_mode": "backup_restore", "target_evidence_key": "postgres_backup_restore"},
    "tigerbeetle": {"profile_mode": "recovery", "target_evidence_key": "tigerbeetle_recovery"},
}
REQUIRED_DESIGN_FIELDS = (
    "rpo_target",
    "rto_target",
    "backup_or_recovery_method",
    "encryption_at_rest",
    "retention_or_replication_policy",
    "restore_or_restart_procedure_ref",
    "integrity_verification_method",
    "failure_scenarios",
)


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


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _policy_errors() -> list[str]:
    try:
        policy = _load(POLICY)
    except Exception as exc:
        return [f"recovery policy unavailable or invalid JSON: {type(exc).__name__}"]
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("recovery policy schema version is invalid")
    if policy.get("profile_schema_version") != PROFILE_SCHEMA:
        errors.append("recovery profile schema version does not match validator policy")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("recovery policy is not bound to the sealed runtime release")
    if policy.get("scoped_obligations") != EXPECTED_OBLIGATIONS:
        errors.append("recovery policy obligations are not exactly PostgreSQL backup/restore and TigerBeetle recovery")
    if policy.get("required_design_fields") != list(REQUIRED_DESIGN_FIELDS):
        errors.append("recovery policy design fields do not exactly match validator policy")
    return errors


def profile_errors(key: str, row: dict[str, Any], payload: object, obligation: dict[str, str]) -> list[str]:
    errors = _policy_errors()
    if not isinstance(payload, dict):
        return errors + ["recovery profile root must be an object"]
    if payload.get("schema_version") != PROFILE_SCHEMA:
        errors.append("recovery profile schema version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks an immutable image digest")
    elif payload.get("image_digest") != digest:
        errors.append("profile image_digest does not match contract row")
    if payload.get("manifest_path") != row.get("manifest_path"):
        errors.append("profile manifest_path does not match contract row")
    if payload.get("persistence_profile") != row.get("persistence_profile"):
        errors.append("profile persistence_profile does not match contract row")
    if _repo_file(row.get("persistence_profile")) is None:
        errors.append("contract persistence_profile is not an existing repository-relative file")
    if payload.get("profile_mode") != obligation["profile_mode"]:
        errors.append("profile_mode does not match authoritative recovery obligation")
    if payload.get("target_evidence_key") != obligation["target_evidence_key"]:
        errors.append("target_evidence_key does not match authoritative deployment-evidence requirement")
    if payload.get("evidence_status") != "design_only_unexecuted":
        errors.append("recovery profile must remain design_only_unexecuted")
    if payload.get("target_execution_evidence_required") is not True:
        errors.append("recovery profile must require separate target execution evidence")
    for field in REQUIRED_DESIGN_FIELDS[:-1]:
        if not _nonempty(payload.get(field)):
            errors.append(f"recovery profile missing {field}")
    procedure = _repo_file(payload.get("restore_or_restart_procedure_ref"))
    if procedure is None:
        errors.append("restore_or_restart_procedure_ref is not an existing repository-relative file")
    scenarios = payload.get("failure_scenarios")
    if not isinstance(scenarios, list) or not scenarios or any(not isinstance(item, str) or not item.strip() for item in scenarios):
        errors.append("failure_scenarios must be a non-empty list of strings")
    return errors


def _self_test() -> list[str]:
    persistence = ROOT / ".mff-recovery-persistence-self-test.tmp"
    procedure = ROOT / ".mff-recovery-procedure-self-test.tmp"
    persistence.write_text("self-test persistence profile\n", encoding="utf-8")
    procedure.write_text("self-test recovery procedure\n", encoding="utf-8")
    try:
        digest = "sha256:" + ("1" * 64)
        row = {
            "image_digest": digest,
            "manifest_path": "deploy/self-test-manifest.json",
            "persistence_profile": persistence.relative_to(ROOT).as_posix(),
        }
        obligation = EXPECTED_OBLIGATIONS["postgres"]
        payload: dict[str, Any] = {
            "schema_version": PROFILE_SCHEMA,
            "runtime_key": "postgres",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "manifest_path": row["manifest_path"],
            "persistence_profile": row["persistence_profile"],
            "profile_mode": obligation["profile_mode"],
            "target_evidence_key": obligation["target_evidence_key"],
            "evidence_status": "design_only_unexecuted",
            "target_execution_evidence_required": True,
            "rpo_target": "self-test",
            "rto_target": "self-test",
            "backup_or_recovery_method": "self-test",
            "encryption_at_rest": "self-test",
            "retention_or_replication_policy": "self-test",
            "restore_or_restart_procedure_ref": procedure.relative_to(ROOT).as_posix(),
            "integrity_verification_method": "self-test",
            "failure_scenarios": ["self-test failure"],
        }
        errors = profile_errors("postgres", row, payload, obligation)
        if errors:
            return [f"valid synthetic recovery profile rejected: {errors}"]
        failures: list[str] = []
        mutations: list[tuple[str, object]] = [
            ("runtime_key", "tigerbeetle"),
            ("authoritative_runtime_base_commit", "0" * 40),
            ("image_digest", "sha256:" + ("2" * 64)),
            ("profile_mode", "recovery"),
            ("target_evidence_key", "tigerbeetle_recovery"),
            ("evidence_status", "passed"),
            ("target_execution_evidence_required", False),
            ("restore_or_restart_procedure_ref", "missing/recovery.md"),
        ]
        for field, value in mutations:
            candidate = json.loads(json.dumps(payload))
            candidate[field] = value
            if not profile_errors("postgres", row, candidate, obligation):
                failures.append(f"self-test failed to reject {field} drift")
        missing = json.loads(json.dumps(payload))
        missing.pop("rpo_target")
        if not profile_errors("postgres", row, missing, obligation):
            failures.append("self-test failed to reject incomplete recovery profile")
        return failures
    finally:
        persistence.unlink(missing_ok=True)
        procedure.unlink(missing_ok=True)


def _contract_errors() -> list[str]:
    errors = _policy_errors()
    contract = _load(CONTRACT)
    rows = {str(row.get("key")): row for row in contract.get("runtimes", []) if isinstance(row, dict)}
    for key in EXPECTED_OBLIGATIONS:
        if key not in rows:
            errors.append(f"authoritative recovery runtime {key} is missing from target contract")
    resolved = 0
    unresolved = 0
    for key, obligation in EXPECTED_OBLIGATIONS.items():
        row = rows.get(key)
        if row is None:
            continue
        profile_ref = row.get("backup_restore_profile")
        if not _nonempty(profile_ref):
            unresolved += 1
            continue
        profile_path = _repo_file(profile_ref)
        if profile_path is None:
            errors.append(f"{key}: backup_restore_profile is not an existing repository-relative file")
            continue
        try:
            payload = _load(profile_path)
        except Exception as exc:
            errors.append(f"{key}: recovery profile is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        profile_issue = profile_errors(key, row, payload, obligation)
        if profile_issue:
            errors.extend(f"{key}: {issue}" for issue in profile_issue)
        else:
            resolved += 1
    if not errors:
        print(f"PASS: recovery-profile integrity gate validated {resolved} resolved authoritative recovery profiles")
        print(f"BOUNDARY: {unresolved} authoritative recovery profiles remain unresolved; no target restore/recovery evidence is claimed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral recovery profiles for authoritative target obligations.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    errors = _self_test() if args.self_test else _contract_errors()
    if errors:
        for error in errors:
            print(f"RECOVERY PROFILE BLOCKER: {error}")
        return 6
    if args.self_test:
        print("PASS: recovery profile self-test rejects scope drift, false execution claims, and missing procedure evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
