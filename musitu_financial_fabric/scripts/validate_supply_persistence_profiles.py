from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "supply-persistence-profile-policy.json"
SELF_TEST_EVIDENCE = TARGET / ".validation" / "supply-persistence-profile-self-test-evidence.txt"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_DESCRIPTOR_SCHEMA = "mff.image-provenance-verification.v1"
DESCRIPTOR_BINDINGS = [
    "runtime_key",
    "authoritative_runtime_base_commit",
    "image_digest",
    "provenance_kind",
    "verified_at",
    "method",
    "verifier",
    "trust_model",
    "artifact_source_sha256",
    "source_identity_sha256",
    "build_recipe_sha256",
    "builder_identity_sha256",
]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


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


def _offset_aware_timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def _byte_bound_evidence_errors(payload: object, *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label} must be an object"]
    if payload.get("status") != "passed":
        errors.append(f"{label}.status must be passed")
    for field in ("method", "verifier", "trust_model"):
        if not _nonempty(payload.get(field)):
            errors.append(f"{label}.{field} is missing")
    evidence = _repo_file(payload.get("evidence_ref"))
    if evidence is None:
        errors.append(f"{label}.evidence_ref must reference an existing repository file")
    declared = str(payload.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append(f"{label}.evidence_sha256 is missing or malformed")
    elif evidence is not None and _sha256(evidence) != declared:
        errors.append(f"{label} evidence SHA-256 does not match retained bytes")
    return errors


def _target_validation_errors(payload: object) -> list[str]:
    return _byte_bound_evidence_errors(payload, label="target_validation")


def _common_binding_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    *,
    schema: str,
    required_fields: list[str],
    require_environment: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["profile root must be an object"]
    if payload.get("schema_version") != schema:
        errors.append("profile schema_version is invalid")
    for field in required_fields:
        if field not in payload:
            errors.append(f"profile missing {field}")
    if payload.get("runtime_key") != key:
        errors.append("profile runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest for profile binding")
    elif payload.get("image_digest") != digest:
        errors.append("profile image_digest does not match contract row")
    if require_environment:
        environment = payload.get("environment_id")
        if not isinstance(environment, str) or not environment.strip():
            errors.append("profile environment_id is missing")
    return errors


def _provenance_descriptor_errors(
    key: str,
    payload: dict[str, Any],
    section: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    verification = payload.get("verification")
    errors.extend(_byte_bound_evidence_errors(verification, label="verification"))
    if not isinstance(verification, dict):
        return errors

    evidence_path = _repo_file(verification.get("evidence_ref"))
    if evidence_path is None:
        return errors
    try:
        descriptor = _load(evidence_path)
    except Exception as exc:
        errors.append(
            f"verification evidence must be a JSON provenance descriptor ({type(exc).__name__})"
        )
        return errors
    if not isinstance(descriptor, dict):
        return errors + ["verification evidence descriptor root must be an object"]
    if descriptor.get("schema_version") != section.get("verification_descriptor_schema_version"):
        errors.append("verification descriptor schema_version is invalid")
    required = section.get("verification_descriptor_required_bindings")
    if not isinstance(required, list) or required != DESCRIPTOR_BINDINGS:
        errors.append("provenance policy verification descriptor bindings are invalid")
        return errors
    for field in required:
        if field not in descriptor:
            errors.append(f"verification descriptor missing {field}")

    expected_direct = {
        "runtime_key": key,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": payload.get("image_digest"),
        "provenance_kind": payload.get("provenance_kind"),
        "verified_at": payload.get("verified_at"),
        "method": verification.get("method"),
        "verifier": verification.get("verifier"),
        "trust_model": verification.get("trust_model"),
    }
    for field, expected in expected_direct.items():
        if descriptor.get(field) != expected:
            errors.append(f"verification descriptor {field} does not match provenance profile")

    hashed_bindings = {
        "artifact_source_sha256": payload.get("artifact_source"),
        "source_identity_sha256": payload.get("source_identity"),
        "build_recipe_sha256": payload.get("build_recipe"),
        "builder_identity_sha256": payload.get("builder_identity"),
    }
    for field, source_value in hashed_bindings.items():
        try:
            expected = _canonical_sha256(source_value)
        except (TypeError, ValueError):
            errors.append(f"provenance profile {field.removesuffix('_sha256')} is not canonical-JSON hashable")
            continue
        declared = str(descriptor.get(field, "")).strip().lower()
        if not SHA256_HEX.fullmatch(declared):
            errors.append(f"verification descriptor {field} is missing or malformed")
        elif declared != expected:
            errors.append(f"verification descriptor {field} does not match provenance profile")
    return errors


def _provenance_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    policy: dict[str, Any],
) -> list[str]:
    section = policy["provenance_profile"]
    errors = _common_binding_errors(
        key,
        row,
        payload,
        schema=str(section["profile_schema_version"]),
        required_fields=list(section["required_fields"]),
        require_environment=False,
    )
    if not isinstance(payload, dict):
        return errors
    if payload.get("provenance_kind") not in set(section.get("allowed_provenance_kinds", [])):
        errors.append("provenance_kind is invalid")
    for field in ("artifact_source", "source_identity", "build_recipe", "builder_identity"):
        if not _nonempty(payload.get(field)):
            errors.append(f"provenance profile missing {field}")
    if payload.get("mutable_tag_only") is not False:
        errors.append("provenance profile must not rely on a mutable tag only")
    if not _offset_aware_timestamp(payload.get("verified_at")):
        errors.append("verified_at must be an offset-aware ISO-8601 timestamp")
    errors.extend(_provenance_descriptor_errors(key, payload, section))
    return errors


def _persistence_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    policy: dict[str, Any],
) -> list[str]:
    section = policy["persistence_profile"]
    errors = _common_binding_errors(
        key,
        row,
        payload,
        schema=str(section["profile_schema_version"]),
        required_fields=list(section["required_fields"]),
        require_environment=True,
    )
    if not isinstance(payload, dict):
        return errors
    classification = payload.get("classification")
    if classification not in set(section.get("allowed_classifications", [])):
        errors.append("persistence classification is invalid")
        errors.extend(_target_validation_errors(payload.get("target_validation")))
        return errors

    if classification == "stateful":
        for field in section.get("stateful_required_fields", []):
            if not _nonempty(payload.get(field)):
                errors.append(f"stateful persistence profile missing {field}")
        storage = payload.get("storage")
        if not isinstance(storage, dict) or not storage:
            errors.append("stateful persistence storage must be a non-empty object")
        recovery = payload.get("backup_restore_profile_ref")
        if recovery != row.get("backup_restore_profile"):
            errors.append("backup_restore_profile_ref does not match contract row")
        if _repo_file(recovery) is None:
            errors.append("backup_restore_profile_ref must reference an existing repository file")
        objectives = payload.get("recovery_objectives")
        if not isinstance(objectives, dict) or not objectives:
            errors.append("stateful persistence recovery_objectives must be a non-empty object")
        integrity = payload.get("data_integrity_validation")
        if not isinstance(integrity, dict) or not integrity:
            errors.append("stateful persistence data_integrity_validation must be a non-empty object")
    elif classification == "stateless":
        for field in section.get("stateless_required_fields", []):
            if field not in payload:
                errors.append(f"stateless persistence profile missing {field}")
        if payload.get("ephemeral_state_only") is not True:
            errors.append("stateless profile must explicitly assert ephemeral_state_only=true")
        if not _nonempty(payload.get("reconstruction_source")):
            errors.append("stateless profile reconstruction_source is missing")
        if not isinstance(payload.get("rationale"), str) or not payload["rationale"].strip():
            errors.append("stateless profile rationale is missing")

    errors.extend(_target_validation_errors(payload.get("target_validation")))
    return errors


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["supply/persistence policy root must be an object"]
    if policy.get("schema_version") != "mff.supply-persistence-profile-policy.v2":
        errors.append("policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("policy is not anchored to the sealed runtime release")
    provenance = policy.get("provenance_profile")
    persistence = policy.get("persistence_profile")
    if not isinstance(provenance, dict):
        errors.append("provenance_profile policy is missing")
    else:
        if provenance.get("verification_status_required_for_resolution") != "passed":
            errors.append("provenance policy does not require passed verification")
        kinds = provenance.get("allowed_provenance_kinds")
        if set(kinds or []) != {"first_party_build", "upstream_verified"}:
            errors.append("provenance allowed kind set is invalid")
        if provenance.get("verification_descriptor_schema_version") != PROVENANCE_DESCRIPTOR_SCHEMA:
            errors.append("provenance verification descriptor schema is invalid")
        if provenance.get("verification_descriptor_required_bindings") != DESCRIPTOR_BINDINGS:
            errors.append("provenance verification descriptor bindings are invalid")
    if not isinstance(persistence, dict):
        errors.append("persistence_profile policy is missing")
    else:
        if persistence.get("target_validation_status_required_for_resolution") != "passed":
            errors.append("persistence policy does not require passed target validation")
        if set(persistence.get("allowed_classifications") or []) != {"stateful", "stateless"}:
            errors.append("persistence classification set is invalid")
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    failures = _policy_errors(policy)
    if failures:
        return failures

    persistence_evidence_ref = str(SELF_TEST_EVIDENCE.relative_to(ROOT)).replace("\\", "/")
    persistence_evidence_sha = _sha256(SELF_TEST_EVIDENCE)
    digest = "sha256:" + ("1" * 64)
    row = {
        "image_digest": digest,
        "backup_restore_profile": persistence_evidence_ref,
    }
    persistence_evidence = {
        "status": "passed",
        "method": "validator-self-test",
        "verifier": "validator-self-test",
        "trust_model": "synthetic-self-test-only",
        "evidence_ref": persistence_evidence_ref,
        "evidence_sha256": persistence_evidence_sha,
    }

    artifact_source = {"kind": "synthetic-self-test", "ref": "artifact"}
    source_identity = {"kind": "synthetic-self-test", "ref": "source"}
    build_recipe = {"kind": "synthetic-self-test", "ref": "recipe"}
    builder_identity = {"kind": "synthetic-self-test", "ref": "builder"}
    verified_at = "2026-09-12T00:00:00+00:00"
    method = "validator-self-test"
    verifier = "validator-self-test"
    trust_model = "synthetic-self-test-only"

    descriptor_path = ROOT / ".mff-provenance-verification-self-test.tmp.json"

    def descriptor_payload() -> dict[str, Any]:
        return {
            "schema_version": PROVENANCE_DESCRIPTOR_SCHEMA,
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "provenance_kind": "first_party_build",
            "verified_at": verified_at,
            "method": method,
            "verifier": verifier,
            "trust_model": trust_model,
            "artifact_source_sha256": _canonical_sha256(artifact_source),
            "source_identity_sha256": _canonical_sha256(source_identity),
            "build_recipe_sha256": _canonical_sha256(build_recipe),
            "builder_identity_sha256": _canonical_sha256(builder_identity),
        }

    def write_descriptor(value: dict[str, Any]) -> str:
        descriptor_path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return _sha256(descriptor_path)

    base_descriptor = descriptor_payload()
    try:
        descriptor_sha = write_descriptor(base_descriptor)
        descriptor_ref = descriptor_path.relative_to(ROOT).as_posix()
        provenance_evidence = {
            "status": "passed",
            "method": method,
            "verifier": verifier,
            "trust_model": trust_model,
            "evidence_ref": descriptor_ref,
            "evidence_sha256": descriptor_sha,
        }
        provenance = {
            "schema_version": "mff.image-provenance-profile.v1",
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "provenance_kind": "first_party_build",
            "artifact_source": artifact_source,
            "source_identity": source_identity,
            "build_recipe": build_recipe,
            "builder_identity": builder_identity,
            "mutable_tag_only": False,
            "verified_at": verified_at,
            "verification": provenance_evidence,
        }
        persistence_stateful = {
            "schema_version": "mff.persistence-profile.v1",
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "environment_id": "self-test-target",
            "classification": "stateful",
            "storage": {"kind": "synthetic-self-test"},
            "durability": "synthetic-self-test",
            "encryption_at_rest": "synthetic-self-test",
            "retention": "synthetic-self-test",
            "backup_restore_profile_ref": persistence_evidence_ref,
            "recovery_objectives": {"source": "synthetic-self-test"},
            "data_integrity_validation": {"source": "synthetic-self-test"},
            "target_validation": persistence_evidence,
        }
        persistence_stateless = {
            "schema_version": "mff.persistence-profile.v1",
            "runtime_key": "self-test",
            "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
            "image_digest": digest,
            "environment_id": "self-test-target",
            "classification": "stateless",
            "ephemeral_state_only": True,
            "reconstruction_source": {"kind": "synthetic-self-test"},
            "rationale": "synthetic self-test only",
            "target_validation": persistence_evidence,
        }

        if _provenance_errors("self-test", row, provenance, policy):
            failures.append("valid synthetic provenance profile was rejected")
        if _persistence_errors("self-test", row, persistence_stateful, policy):
            failures.append("valid synthetic stateful persistence profile was rejected")
        if _persistence_errors("self-test", row, persistence_stateless, policy):
            failures.append("valid synthetic stateless persistence profile was rejected")

        bad = json.loads(json.dumps(provenance))
        bad["mutable_tag_only"] = True
        if not _provenance_errors("self-test", row, bad, policy):
            failures.append("provenance self-test failed to reject mutable-tag-only evidence")

        bad = json.loads(json.dumps(provenance))
        bad["verification"]["status"] = "pending"
        if not _provenance_errors("self-test", row, bad, policy):
            failures.append("provenance self-test failed to reject unverified evidence")

        bad = json.loads(json.dumps(provenance))
        bad["verification"]["evidence_sha256"] = "0" * 64
        if not _provenance_errors("self-test", row, bad, policy):
            failures.append("provenance self-test failed to reject evidence hash mismatch")

        bad = json.loads(json.dumps(provenance))
        bad["verified_at"] = "2026-09-12T00:00:00"
        if not _provenance_errors("self-test", row, bad, policy):
            failures.append("provenance self-test failed to reject timezone-less verification time")

        descriptor_mutations = [
            ("image digest", "image_digest", "sha256:" + ("2" * 64)),
            ("sealed release", "authoritative_runtime_base_commit", "0" * 40),
            ("provenance kind", "provenance_kind", "upstream_verified"),
            ("artifact source hash", "artifact_source_sha256", "0" * 64),
            ("verification method", "method", "different-method"),
        ]
        for label, field, value in descriptor_mutations:
            mutated = dict(base_descriptor)
            mutated[field] = value
            bad = json.loads(json.dumps(provenance))
            bad["verification"]["evidence_sha256"] = write_descriptor(mutated)
            if not _provenance_errors("self-test", row, bad, policy):
                failures.append(f"provenance self-test failed to reject descriptor {label} drift")
        write_descriptor(base_descriptor)

        bad = json.loads(json.dumps(persistence_stateless))
        bad["ephemeral_state_only"] = False
        if not _persistence_errors("self-test", row, bad, policy):
            failures.append("persistence self-test failed to reject false statelessness assertion")

        bad = json.loads(json.dumps(persistence_stateful))
        bad["backup_restore_profile_ref"] = "missing/recovery-profile.json"
        if not _persistence_errors("self-test", row, bad, policy):
            failures.append("persistence self-test failed to reject mismatched recovery reference")

        bad = json.loads(json.dumps(persistence_stateful))
        del bad["storage"]
        if not _persistence_errors("self-test", row, bad, policy):
            failures.append("persistence self-test failed to reject missing stateful storage evidence")

        for payload, checker, label in (
            (provenance, _provenance_errors, "provenance"),
            (persistence_stateful, _persistence_errors, "persistence"),
        ):
            bad = json.loads(json.dumps(payload))
            bad["runtime_key"] = "wrong-runtime"
            if not checker("self-test", row, bad, policy):
                failures.append(f"{label} self-test failed to reject runtime drift")
            bad = json.loads(json.dumps(payload))
            bad["authoritative_runtime_base_commit"] = "0" * 40
            if not checker("self-test", row, bad, policy):
                failures.append(f"{label} self-test failed to reject release drift")
            bad = json.loads(json.dumps(payload))
            bad["image_digest"] = "sha256:" + ("2" * 64)
            if not checker("self-test", row, bad, policy):
                failures.append(f"{label} self-test failed to reject image drift")

        return failures
    finally:
        descriptor_path.unlink(missing_ok=True)


def _contract_errors() -> tuple[list[str], tuple[int, int], tuple[int, int]]:
    errors: list[str] = []
    policy = _load(POLICY)
    errors.extend(_policy_errors(policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, (0, 0), (0, 0)
    defaults = contract.get("defaults_for_unresolved_fields", {})
    provenance_resolved = provenance_unresolved = 0
    persistence_resolved = persistence_unresolved = 0

    for row in contract.get("runtimes", []):
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))

        provenance_ref = row.get("provenance_ref", defaults.get("provenance_ref"))
        if provenance_ref in (None, "", [], {}):
            provenance_unresolved += 1
        else:
            path = _repo_file(provenance_ref)
            if path is None:
                errors.append(f"{key}: provenance_ref is not an existing repository file")
            else:
                try:
                    payload = _load(path)
                except Exception as exc:
                    errors.append(f"{key}: provenance profile is unreadable or invalid JSON ({type(exc).__name__})")
                else:
                    profile_errors = _provenance_errors(key, row, payload, policy)
                    errors.extend(f"{key}: provenance_ref: {error}" for error in profile_errors)
                    if not profile_errors:
                        provenance_resolved += 1

        persistence_ref = row.get("persistence_profile", defaults.get("persistence_profile"))
        if persistence_ref in (None, "", [], {}):
            persistence_unresolved += 1
        else:
            path = _repo_file(persistence_ref)
            if path is None:
                errors.append(f"{key}: persistence_profile is not an existing repository file")
            else:
                try:
                    payload = _load(path)
                except Exception as exc:
                    errors.append(f"{key}: persistence profile is unreadable or invalid JSON ({type(exc).__name__})")
                else:
                    profile_errors = _persistence_errors(key, row, payload, policy)
                    errors.extend(f"{key}: persistence_profile: {error}" for error in profile_errors)
                    if not profile_errors:
                        persistence_resolved += 1

    return (
        errors,
        (provenance_resolved, provenance_unresolved),
        (persistence_resolved, persistence_unresolved),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral image provenance and persistence profiles.")
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
            "PASS: supply/persistence validator rejects mutable-tag-only provenance, "
            "byte-valid but semantically unbound provenance descriptors, unverified evidence, "
            "false statelessness, and mismatched recovery references"
        )
        return 0

    errors, provenance, persistence = _contract_errors()
    if errors:
        for error in errors:
            print(f"SUPPLY/PERSISTENCE BLOCKER: {error}")
        return 2
    print(f"PASS: provenance_ref: validated {provenance[0]} resolved profiles; {provenance[1]} remain unresolved")
    print(f"PASS: persistence_profile: validated {persistence[0]} resolved profiles; {persistence[1]} remain unresolved")
    print(
        "BOUNDARY: no signed provenance, registry publication, Sigstore/Cosign verification, "
        "issuer authenticity, stateful/stateless classification, storage design, or target execution "
        "is inferred from unresolved profiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
