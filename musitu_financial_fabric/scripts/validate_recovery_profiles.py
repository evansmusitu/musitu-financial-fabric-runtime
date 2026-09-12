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
POLICY = TARGET / "recovery-profile-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.recovery-profile-policy.v2"
PROFILE_SCHEMA = "mff.runtime-recovery-profile.v1"
PERSISTENCE_SCHEMA = "mff.persistence-profile.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_OBLIGATIONS = {
    "postgres": {"profile_mode": "backup_restore", "target_evidence_key": "postgres_backup_restore"},
    "tigerbeetle": {"profile_mode": "recovery", "target_evidence_key": "tigerbeetle_recovery"},
}
EXPECTED_RESOLUTION_MODES = {
    "scoped_stateful": {
        "requires_persistence_classification": "stateful",
        "requires_recovery_design_profile": True,
    },
    "unscoped_stateless": {
        "requires_persistence_classification": "stateless",
        "backup_restore_profile_must_equal_persistence_profile": True,
    },
    "unscoped_stateful": {
        "resolution": "blocked_until_explicit_scoped_obligation",
    },
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_validation_errors(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["persistence target_validation must be an object"]
    if payload.get("status") != "passed":
        errors.append("persistence target_validation.status must be passed")
    for field in ("method", "verifier", "trust_model"):
        if not _nonempty(payload.get(field)):
            errors.append(f"persistence target_validation.{field} is missing")
    evidence = _repo_file(payload.get("evidence_ref"))
    if evidence is None:
        errors.append("persistence target_validation.evidence_ref must reference an existing repository file")
    declared = str(payload.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append("persistence target_validation.evidence_sha256 is missing or malformed")
    elif evidence is not None and _sha256(evidence) != declared:
        errors.append("persistence target_validation evidence SHA-256 does not match retained bytes")
    return errors


def _persistence_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    *,
    expected_classification: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["persistence profile root must be an object"]
    if payload.get("schema_version") != PERSISTENCE_SCHEMA:
        errors.append("persistence profile schema_version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("persistence profile runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("persistence profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks an immutable image digest")
    elif payload.get("image_digest") != digest:
        errors.append("persistence profile image_digest does not match contract row")
    if not isinstance(payload.get("environment_id"), str) or not payload["environment_id"].strip():
        errors.append("persistence profile environment_id is missing")
    if payload.get("classification") != expected_classification:
        errors.append(
            f"persistence classification must be {expected_classification} before backup_restore_profile can resolve"
        )

    if expected_classification == "stateful":
        for field in (
            "storage",
            "durability",
            "encryption_at_rest",
            "retention",
            "recovery_objectives",
            "data_integrity_validation",
        ):
            if not _nonempty(payload.get(field)):
                errors.append(f"stateful persistence profile missing {field}")
        if payload.get("backup_restore_profile_ref") != row.get("backup_restore_profile"):
            errors.append("stateful persistence backup_restore_profile_ref does not match contract row")
    elif expected_classification == "stateless":
        if payload.get("ephemeral_state_only") is not True:
            errors.append("stateless persistence profile must assert ephemeral_state_only=true")
        if not _nonempty(payload.get("reconstruction_source")):
            errors.append("stateless persistence reconstruction_source is missing")
        if not isinstance(payload.get("rationale"), str) or not payload["rationale"].strip():
            errors.append("stateless persistence rationale is missing")

    errors.extend(_target_validation_errors(payload.get("target_validation")))
    return errors


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
    if policy.get("persistence_profile_schema_version") != PERSISTENCE_SCHEMA:
        errors.append("persistence profile schema version does not match validator policy")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("recovery policy is not bound to the sealed runtime release")
    if policy.get("scoped_obligations") != EXPECTED_OBLIGATIONS:
        errors.append("recovery policy obligations are not exactly PostgreSQL backup/restore and TigerBeetle recovery")
    if policy.get("resolution_modes") != EXPECTED_RESOLUTION_MODES:
        errors.append("recovery policy resolution modes do not exactly match validator policy")
    if policy.get("required_design_fields") != list(REQUIRED_DESIGN_FIELDS):
        errors.append("recovery policy design fields do not exactly match validator policy")
    return errors


def _persistence_profile(
    key: str,
    row: dict[str, Any],
    *,
    expected_classification: str,
) -> tuple[object | None, list[str]]:
    profile_path = _repo_file(row.get("persistence_profile"))
    if profile_path is None:
        return None, ["contract persistence_profile is not an existing repository-relative file"]
    try:
        payload = _load(profile_path)
    except Exception as exc:
        return None, [f"persistence profile is unreadable or invalid JSON ({type(exc).__name__})"]
    return payload, _persistence_errors(
        key,
        row,
        payload,
        expected_classification=expected_classification,
    )


def profile_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    obligation: dict[str, str],
) -> list[str]:
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

    _, persistence_errors = _persistence_profile(
        key,
        row,
        expected_classification="stateful",
    )
    errors.extend(f"persistence: {error}" for error in persistence_errors)

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
    if not isinstance(scenarios, list) or not scenarios or any(
        not isinstance(item, str) or not item.strip() for item in scenarios
    ):
        errors.append("failure_scenarios must be a non-empty list of strings")
    return errors


def _unscoped_stateless_errors(
    key: str,
    row: dict[str, Any],
    profile_ref: object,
) -> list[str]:
    errors = _policy_errors()
    persistence_ref = row.get("persistence_profile")
    if profile_ref != persistence_ref:
        errors.append(
            "unscoped backup_restore_profile may resolve only by referencing the exact stateless persistence_profile"
        )
        return errors
    _, persistence_errors = _persistence_profile(
        key,
        row,
        expected_classification="stateless",
    )
    errors.extend(f"persistence: {error}" for error in persistence_errors)
    return errors


def _self_test() -> list[str]:
    persistence = ROOT / ".mff-recovery-persistence-self-test.json"
    stateless = ROOT / ".mff-recovery-stateless-self-test.json"
    procedure = ROOT / ".mff-recovery-procedure-self-test.tmp"
    evidence = ROOT / ".mff-recovery-evidence-self-test.tmp"
    procedure.write_text("self-test recovery procedure\n", encoding="utf-8")
    evidence.write_text("self-test target validation evidence\n", encoding="utf-8")
    evidence_ref = evidence.relative_to(ROOT).as_posix()
    evidence_sha = _sha256(evidence)
    target_validation = {
        "status": "passed",
        "method": "validator-self-test",
        "verifier": "validator-self-test",
        "trust_model": "synthetic-self-test-only",
        "evidence_ref": evidence_ref,
        "evidence_sha256": evidence_sha,
    }
    try:
        digest = "sha256:" + ("1" * 64)
        recovery_ref = "deploy/self-test-recovery-profile.json"
        persistence_ref = persistence.relative_to(ROOT).as_posix()
        row = {
            "image_digest": digest,
            "manifest_path": "deploy/self-test-manifest.json",
            "persistence_profile": persistence_ref,
            "backup_restore_profile": recovery_ref,
        }
        stateful_payload = {
            "schema_version": PERSISTENCE_SCHEMA,
            "runtime_key": "postgres",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "environment_id": "self-test-target",
            "classification": "stateful",
            "storage": {"kind": "synthetic-self-test"},
            "durability": "synthetic-self-test",
            "encryption_at_rest": "synthetic-self-test",
            "retention": "synthetic-self-test",
            "backup_restore_profile_ref": recovery_ref,
            "recovery_objectives": {"kind": "synthetic-self-test"},
            "data_integrity_validation": {"kind": "synthetic-self-test"},
            "target_validation": target_validation,
        }
        persistence.write_text(json.dumps(stateful_payload), encoding="utf-8")

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
            return [f"valid synthetic scoped recovery profile rejected: {errors}"]

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

        bad_stateful = json.loads(json.dumps(stateful_payload))
        bad_stateful["classification"] = "stateless"
        persistence.write_text(json.dumps(bad_stateful), encoding="utf-8")
        if not profile_errors("postgres", row, payload, obligation):
            failures.append("self-test failed to reject a scoped recovery profile backed by stateless persistence")
        persistence.write_text(json.dumps(stateful_payload), encoding="utf-8")

        stateless_ref = stateless.relative_to(ROOT).as_posix()
        stateless_row = {
            "image_digest": digest,
            "manifest_path": "deploy/self-test-stateless-manifest.json",
            "persistence_profile": stateless_ref,
            "backup_restore_profile": stateless_ref,
        }
        stateless_payload = {
            "schema_version": PERSISTENCE_SCHEMA,
            "runtime_key": "self-test-stateless",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "environment_id": "self-test-target",
            "classification": "stateless",
            "ephemeral_state_only": True,
            "reconstruction_source": {"kind": "synthetic-self-test"},
            "rationale": "synthetic self-test only",
            "target_validation": target_validation,
        }
        stateless.write_text(json.dumps(stateless_payload), encoding="utf-8")
        stateless_errors = _unscoped_stateless_errors(
            "self-test-stateless",
            stateless_row,
            stateless_ref,
        )
        if stateless_errors:
            failures.append(f"valid synthetic unscoped stateless resolution rejected: {stateless_errors}")

        wrong_ref = dict(stateless_row)
        wrong_ref["backup_restore_profile"] = persistence_ref
        if not _unscoped_stateless_errors("self-test-stateless", wrong_ref, persistence_ref):
            failures.append("self-test failed to reject unscoped backup_restore_profile substitution")

        bad_stateless = json.loads(json.dumps(stateless_payload))
        bad_stateless["classification"] = "stateful"
        stateless.write_text(json.dumps(bad_stateless), encoding="utf-8")
        if not _unscoped_stateless_errors("self-test-stateless", stateless_row, stateless_ref):
            failures.append("self-test failed to reject unscoped stateful persistence without an explicit obligation")

        bad_stateless = json.loads(json.dumps(stateless_payload))
        bad_stateless["runtime_key"] = "wrong-runtime"
        stateless.write_text(json.dumps(bad_stateless), encoding="utf-8")
        if not _unscoped_stateless_errors("self-test-stateless", stateless_row, stateless_ref):
            failures.append("self-test failed to reject unscoped persistence runtime drift")

        bad_stateless = json.loads(json.dumps(stateless_payload))
        bad_stateless["target_validation"]["evidence_sha256"] = "0" * 64
        stateless.write_text(json.dumps(bad_stateless), encoding="utf-8")
        if not _unscoped_stateless_errors("self-test-stateless", stateless_row, stateless_ref):
            failures.append("self-test failed to reject unscoped persistence evidence hash drift")

        return failures
    finally:
        persistence.unlink(missing_ok=True)
        stateless.unlink(missing_ok=True)
        procedure.unlink(missing_ok=True)
        evidence.unlink(missing_ok=True)


def _contract_errors() -> list[str]:
    errors = _policy_errors()
    contract = _load(CONTRACT)
    rows = [row for row in contract.get("runtimes", []) if isinstance(row, dict)]
    keys = {str(row.get("key")) for row in rows}
    for key in EXPECTED_OBLIGATIONS:
        if key not in keys:
            errors.append(f"authoritative recovery runtime {key} is missing from target contract")

    defaults = contract.get("defaults_for_unresolved_fields", {})
    resolved = 0
    unresolved = 0
    for row in rows:
        key = str(row.get("key", "unknown"))
        profile_ref = row.get("backup_restore_profile", defaults.get("backup_restore_profile"))
        if not _nonempty(profile_ref):
            unresolved += 1
            continue

        if key in EXPECTED_OBLIGATIONS:
            profile_path = _repo_file(profile_ref)
            if profile_path is None:
                errors.append(f"{key}: backup_restore_profile is not an existing repository-relative file")
                continue
            try:
                payload = _load(profile_path)
            except Exception as exc:
                errors.append(f"{key}: recovery profile is unreadable or invalid JSON ({type(exc).__name__})")
                continue
            profile_issue = profile_errors(key, row, payload, EXPECTED_OBLIGATIONS[key])
        else:
            profile_issue = _unscoped_stateless_errors(key, row, profile_ref)

        if profile_issue:
            errors.extend(f"{key}: {issue}" for issue in profile_issue)
        else:
            resolved += 1

    if not errors:
        print(
            f"PASS: recovery-profile integrity gate validated {resolved} resolved "
            f"backup_restore_profile fields across all {len(rows)} runtimes"
        )
        print(
            f"BOUNDARY: {unresolved} backup_restore_profile fields remain unresolved; "
            "no additional stateful/stateless classification or target restore/recovery evidence is inferred"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate provider-neutral backup/recovery resolution across the exact runtime contract."
    )
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
        print(
            "PASS: recovery profile self-test rejects scoped persistence mismatch, "
            "unscoped substitution, stateful-without-obligation, and evidence drift"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
