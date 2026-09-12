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
SOURCE_POLICY = TARGET / "identity-secret-profile-policy.json"
POLICY = TARGET / "identity-secret-target-evidence-policy.json"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.identity-secret-target-evidence-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.identity-secret-profile-policy.v1"
DESCRIPTOR_SCHEMA = "mff.identity-secret-target-validation.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_PROFILE_KINDS = {
    "workload_identity": {
        "contract_field": "workload_identity_profile",
        "profile_schema_version": "mff.workload-identity-profile.v1",
        "authority_runtime": "spire",
        "direct_bindings": [
            "runtime_key",
            "authoritative_runtime_base_commit",
            "image_digest",
            "environment_id",
            "authority_runtime",
            "identity_standard",
        ],
        "semantic_fields": [
            "trust_domain",
            "workload_selector",
            "bootstrap_method",
            "issuance",
            "rotation",
            "revocation",
            "shared_static_credentials",
            "long_lived_static_bootstrap_credentials",
        ],
    },
    "secret": {
        "contract_field": "secret_profile",
        "profile_schema_version": "mff.secret-profile.v1",
        "authority_runtime": "openbao",
        "direct_bindings": [
            "runtime_key",
            "authoritative_runtime_base_commit",
            "image_digest",
            "environment_id",
            "authority_runtime",
        ],
        "semantic_fields": [
            "delivery_method",
            "auth_method",
            "secret_classes",
            "rotation",
            "revocation",
            "contains_secret_material",
            "plaintext_credentials_committed",
            "long_lived_static_auth_credentials",
        ],
    },
}
EXPECTED_DESCRIPTOR_METADATA = ["validation_method", "verifier", "trust_model"]


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


def _source_policy_inventory_errors(
    source_policy: object,
    target_policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(source_policy, dict):
        return ["identity/secret source policy root must be an object"]
    if source_policy.get("schema_version") != target_policy.get("source_profile_policy_schema_version"):
        errors.append("identity/secret target-evidence policy does not match source profile policy schema")

    source_sections = {
        "workload_identity": source_policy.get("workload_identity"),
        "secret": source_policy.get("secrets"),
    }
    exclusions = {
        "runtime_key",
        "authoritative_runtime_base_commit",
        "image_digest",
        "environment_id",
        "authority_runtime",
        "identity_standard",
        "target_validation",
    }
    for kind, expected in EXPECTED_PROFILE_KINDS.items():
        section = source_sections.get(kind)
        if not isinstance(section, dict):
            errors.append(f"{kind} source profile policy section is missing")
            continue
        if section.get("profile_schema_version") != expected["profile_schema_version"]:
            errors.append(f"{kind} source profile schema drifted")
        if section.get("authority_runtime") != expected["authority_runtime"]:
            errors.append(f"{kind} source authority runtime drifted")
        if kind == "workload_identity" and section.get("identity_standard") != "SPIFFE":
            errors.append("workload identity source standard drifted")
        required = section.get("required_fields")
        if not isinstance(required, list):
            errors.append(f"{kind} source required_fields is invalid")
            continue
        semantic = [field for field in required if field not in exclusions]
        if semantic != expected["semantic_fields"]:
            errors.append(f"{kind} target-evidence semantic field inventory drifted from source policy")
    return errors


def _policy_errors(policy: object, source_policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["identity/secret target-evidence policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("identity/secret target-evidence policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("identity/secret target-evidence policy is not anchored to the sealed runtime release")
    if policy.get("source_profile_policy_schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("identity/secret target-evidence source policy schema is invalid")
    if policy.get("descriptor_schema_version") != DESCRIPTOR_SCHEMA:
        errors.append("identity/secret target-validation descriptor schema is invalid")
    if policy.get("profile_kinds") != EXPECTED_PROFILE_KINDS:
        errors.append("identity/secret target-evidence profile-kind policy is invalid")
    if policy.get("descriptor_required_metadata") != EXPECTED_DESCRIPTOR_METADATA:
        errors.append("identity/secret target-validation descriptor metadata policy is invalid")
    errors.extend(_source_policy_inventory_errors(source_policy, policy))
    return errors


def _evidence_errors(target_validation: object) -> tuple[list[str], Path | None]:
    errors: list[str] = []
    if not isinstance(target_validation, dict):
        return ["target_validation must be an object"], None
    if target_validation.get("status") != "passed":
        errors.append("target_validation.status must be passed")
    evidence = _repo_file(target_validation.get("evidence_ref"))
    if evidence is None:
        errors.append("target_validation.evidence_ref must reference an existing repository file")
    declared = str(target_validation.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append("target_validation.evidence_sha256 is missing or malformed")
    elif evidence is not None and _sha256(evidence) != declared:
        errors.append("target_validation evidence SHA-256 does not match retained bytes")
    return errors, evidence


def _profile_errors(
    kind: str,
    key: str,
    row: dict[str, Any],
    payload: object,
    policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    section = policy.get("profile_kinds", {}).get(kind)
    if not isinstance(section, dict):
        return [f"{kind} target-evidence policy section is missing"]
    if not isinstance(payload, dict):
        return [f"{kind} profile root must be an object"]

    if payload.get("schema_version") != section.get("profile_schema_version"):
        errors.append(f"{kind} profile schema_version is invalid")
    if payload.get("runtime_key") != key:
        errors.append(f"{kind} profile runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append(f"{kind} profile is not bound to the sealed runtime release")
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append(f"contract row lacks a valid immutable image digest for {kind} target evidence")
    elif payload.get("image_digest") != digest:
        errors.append(f"{kind} profile image_digest does not match contract row")
    environment = payload.get("environment_id")
    if not isinstance(environment, str) or not environment.strip():
        errors.append(f"{kind} profile environment_id is missing")
    if payload.get("authority_runtime") != section.get("authority_runtime"):
        errors.append(f"{kind} profile authority_runtime does not match target-evidence policy")
    if kind == "workload_identity" and payload.get("identity_standard") != "SPIFFE":
        errors.append("workload identity profile identity_standard must be SPIFFE")

    for field in section.get("semantic_fields", []):
        if field not in payload:
            errors.append(f"{kind} profile missing semantic field {field}")

    evidence_errors, evidence_path = _evidence_errors(payload.get("target_validation"))
    errors.extend(evidence_errors)
    if evidence_path is None:
        return errors
    try:
        descriptor = _load(evidence_path)
    except Exception as exc:
        errors.append(f"target_validation evidence must be a JSON identity/secret descriptor ({type(exc).__name__})")
        return errors
    if not isinstance(descriptor, dict):
        return errors + ["identity/secret target-validation descriptor root must be an object"]
    if descriptor.get("schema_version") != policy.get("descriptor_schema_version"):
        errors.append("identity/secret target-validation descriptor schema_version is invalid")
    if descriptor.get("profile_kind") != kind:
        errors.append("identity/secret target-validation descriptor profile_kind does not match profile")

    for field in section.get("direct_bindings", []):
        if field not in descriptor:
            errors.append(f"identity/secret target-validation descriptor missing {field}")
        elif descriptor.get(field) != payload.get(field):
            errors.append(f"identity/secret target-validation descriptor {field} does not match profile")

    semantic_payload = {field: payload.get(field) for field in section.get("semantic_fields", [])}
    declared_semantic = str(descriptor.get("profile_semantics_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared_semantic):
        errors.append("identity/secret target-validation descriptor profile_semantics_sha256 is missing or malformed")
    else:
        try:
            expected_semantic = _canonical_sha256(semantic_payload)
        except (TypeError, ValueError):
            errors.append(f"{kind} profile semantic fields are not canonical-JSON hashable")
        else:
            if declared_semantic != expected_semantic:
                errors.append("identity/secret target-validation descriptor semantic hash does not match profile")

    for field in policy.get("descriptor_required_metadata", []):
        value = descriptor.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"identity/secret target-validation descriptor {field} is missing")
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
    row = {"image_digest": digest}
    descriptor_path = ROOT / ".mff-identity-secret-target-validation-self-test.tmp.json"

    identity = {
        "schema_version": "mff.workload-identity-profile.v1",
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "authority_runtime": "spire",
        "identity_standard": "SPIFFE",
        "trust_domain": "self-test.invalid",
        "workload_selector": {"kind": "self-test"},
        "bootstrap_method": "self-test",
        "issuance": "self-test",
        "rotation": "self-test",
        "revocation": "self-test",
        "shared_static_credentials": False,
        "long_lived_static_bootstrap_credentials": False,
    }
    secret = {
        "schema_version": "mff.secret-profile.v1",
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "authority_runtime": "openbao",
        "delivery_method": "self-test",
        "auth_method": "self-test",
        "secret_classes": ["self-test-class"],
        "rotation": "self-test",
        "revocation": "self-test",
        "contains_secret_material": False,
        "plaintext_credentials_committed": False,
        "long_lived_static_auth_credentials": False,
    }

    def descriptor_for(kind: str, profile: dict[str, Any]) -> dict[str, Any]:
        section = policy["profile_kinds"][kind]
        descriptor = {
            "schema_version": DESCRIPTOR_SCHEMA,
            "profile_kind": kind,
            "validation_method": "validator-self-test",
            "verifier": "validator-self-test",
            "trust_model": "synthetic-self-test-only",
        }
        for field in section["direct_bindings"]:
            descriptor[field] = profile[field]
        semantics = {field: profile[field] for field in section["semantic_fields"]}
        descriptor["profile_semantics_sha256"] = _canonical_sha256(semantics)
        return descriptor

    try:
        for kind, base_profile in (("workload_identity", identity), ("secret", secret)):
            descriptor = descriptor_for(kind, base_profile)
            evidence_sha = _write_json(descriptor_path, descriptor)
            profile = json.loads(json.dumps(base_profile))
            profile["target_validation"] = {
                "status": "passed",
                "evidence_ref": descriptor_path.relative_to(ROOT).as_posix(),
                "evidence_sha256": evidence_sha,
            }
            if _profile_errors(kind, "self-test", row, profile, policy):
                failures.append(f"valid synthetic {kind} target descriptor was rejected")

            descriptor_mutations = [
                ("profile kind", "profile_kind", "secret" if kind == "workload_identity" else "workload_identity"),
                ("runtime", "runtime_key", "wrong-runtime"),
                ("sealed release", "authoritative_runtime_base_commit", "0" * 40),
                ("image digest", "image_digest", "sha256:" + ("2" * 64)),
                ("environment", "environment_id", "wrong-target"),
                ("authority", "authority_runtime", "wrong-authority"),
                ("semantic hash", "profile_semantics_sha256", "0" * 64),
                ("validation metadata", "validation_method", ""),
            ]
            if kind == "workload_identity":
                descriptor_mutations.append(("identity standard", "identity_standard", "not-SPIFFE"))
            for label, field, value in descriptor_mutations:
                bad_descriptor = dict(descriptor)
                bad_descriptor[field] = value
                bad = json.loads(json.dumps(profile))
                bad["target_validation"]["evidence_sha256"] = _write_json(descriptor_path, bad_descriptor)
                if not _profile_errors(kind, "self-test", row, bad, policy):
                    failures.append(f"{kind} target-evidence self-test failed to reject descriptor {label} drift")

            _write_json(descriptor_path, descriptor)
            bad = json.loads(json.dumps(profile))
            bad["target_validation"]["evidence_sha256"] = "0" * 64
            if not _profile_errors(kind, "self-test", row, bad, policy):
                failures.append(f"{kind} target-evidence self-test failed to reject retained-byte hash mismatch")
        return failures
    finally:
        descriptor_path.unlink(missing_ok=True)


def _contract_errors() -> tuple[list[str], dict[str, tuple[int, int]]]:
    errors: list[str] = []
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    errors.extend(_policy_errors(policy, source_policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, {kind: (0, 0) for kind in EXPECTED_PROFILE_KINDS}
    defaults = contract.get("defaults_for_unresolved_fields", {})
    counts: dict[str, list[int]] = {kind: [0, 0] for kind in EXPECTED_PROFILE_KINDS}

    for row in contract.get("runtimes", []):
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))
        for kind, section in EXPECTED_PROFILE_KINDS.items():
            contract_field = section["contract_field"]
            ref = row.get(contract_field, defaults.get(contract_field))
            if ref in (None, "", [], {}):
                counts[kind][1] += 1
                continue
            path = _repo_file(ref)
            if path is None:
                errors.append(f"{key}: {contract_field} is not an existing repository file")
                continue
            try:
                payload = _load(path)
            except Exception as exc:
                errors.append(f"{key}: {contract_field} is unreadable or invalid JSON ({type(exc).__name__})")
                continue
            profile_errors = _profile_errors(kind, key, row, payload, policy)
            errors.extend(f"{key}: {kind}_target_evidence: {error}" for error in profile_errors)
            if not profile_errors:
                counts[kind][0] += 1
    return errors, {kind: (value[0], value[1]) for kind, value in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate provider-neutral workload identity and secret target-evidence descriptors."
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
            "PASS: identity/secret target-evidence validator rejects byte-valid but semantically "
            "unbound SPIFFE/SPIRE/OpenBao descriptors and retained-byte drift"
        )
        return 0

    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"IDENTITY/SECRET TARGET EVIDENCE BLOCKER: {error}")
        return 2
    identity = counts["workload_identity"]
    secret = counts["secret"]
    print(
        f"PASS: workload_identity_target_evidence: validated {identity[0]} resolved profiles; "
        f"{identity[1]} remain unresolved"
    )
    print(
        f"PASS: secret_target_evidence: validated {secret[0]} resolved profiles; "
        f"{secret[1]} remain unresolved"
    )
    print(
        "BOUNDARY: unresolved identity/secret evidence does not establish a SPIRE trust domain, "
        "SPIFFE issuance, OpenBao deployment or auth, credential or secret delivery, target health, "
        "deployment, production authorization, or independent validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
