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
POLICY = TARGET / "identity-secret-profile-policy.json"
SELF_TEST_EVIDENCE = TARGET / ".validation" / "identity-secret-profile-self-test-evidence.txt"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


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


def _nonempty(value: object) -> bool:
    return value not in (None, "", [], {})


def _target_validation_errors(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["target_validation must be an object"]
    if payload.get("status") != "passed":
        errors.append("target_validation.status must be passed")
    evidence_path = _repo_file(payload.get("evidence_ref"))
    if evidence_path is None:
        errors.append("target_validation.evidence_ref must reference an existing repository file")
    declared = str(payload.get("evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared):
        errors.append("target_validation.evidence_sha256 is missing or malformed")
    elif evidence_path is not None and _sha256(evidence_path) != declared:
        errors.append("target_validation evidence SHA-256 does not match retained bytes")
    return errors


def _common_errors(key: str, row: dict[str, Any], payload: object, schema: str, required_fields: list[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["profile root must be an object"]
    if payload.get("schema_version") != schema:
        errors.append("profile schema_version is invalid")
    for field in required_fields:
        if field not in payload or not _nonempty(payload.get(field)) and field not in {
            "shared_static_credentials",
            "contains_secret_material",
            "plaintext_credentials_committed",
        }:
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
    if not isinstance(payload.get("environment_id"), str) or not payload["environment_id"].strip():
        errors.append("profile environment_id is missing")
    errors.extend(_target_validation_errors(payload.get("target_validation")))
    return errors


def _identity_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["workload_identity"]
    errors = _common_errors(
        key,
        row,
        payload,
        str(section["profile_schema_version"]),
        list(section["required_fields"]),
    )
    if not isinstance(payload, dict):
        return errors
    if payload.get("authority_runtime") != section.get("authority_runtime"):
        errors.append("workload identity authority_runtime must be spire")
    if payload.get("identity_standard") != section.get("identity_standard"):
        errors.append("workload identity standard must be SPIFFE")
    for field in ("trust_domain", "workload_selector", "bootstrap_method", "issuance", "rotation", "revocation"):
        if not _nonempty(payload.get(field)):
            errors.append(f"workload identity profile missing {field}")
    if payload.get("shared_static_credentials") is not False:
        errors.append("workload identity profile must forbid shared static credentials")
    return errors


def _secret_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["secrets"]
    errors = _common_errors(
        key,
        row,
        payload,
        str(section["profile_schema_version"]),
        list(section["required_fields"]),
    )
    if not isinstance(payload, dict):
        return errors
    if payload.get("authority_runtime") != section.get("authority_runtime"):
        errors.append("secret profile authority_runtime must be openbao")
    for field in ("delivery_method", "auth_method", "rotation", "revocation"):
        if not _nonempty(payload.get(field)):
            errors.append(f"secret profile missing {field}")
    classes = payload.get("secret_classes")
    if not isinstance(classes, list) or not classes or any(not isinstance(item, str) or not item.strip() for item in classes):
        errors.append("secret_classes must be a non-empty list of secret class names")
    if payload.get("contains_secret_material") is not False:
        errors.append("secret profile must not contain secret material")
    if payload.get("plaintext_credentials_committed") is not False:
        errors.append("secret profile must attest no plaintext credentials are committed")
    return errors


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["identity/secret policy root must be an object"]
    if policy.get("schema_version") != "mff.identity-secret-profile-policy.v1":
        errors.append("identity/secret policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("identity/secret policy is not anchored to the sealed runtime release")
    identity = policy.get("workload_identity")
    secrets = policy.get("secrets")
    if not isinstance(identity, dict) or identity.get("authority_runtime") != "spire" or identity.get("identity_standard") != "SPIFFE":
        errors.append("workload identity policy must bind SPIFFE/SPIRE")
    if not isinstance(secrets, dict) or secrets.get("authority_runtime") != "openbao":
        errors.append("secret policy must bind OpenBao")
    for section_name, section in (("workload_identity", identity), ("secrets", secrets)):
        if not isinstance(section, dict):
            continue
        if section.get("target_validation_status_required_for_deployability") != "passed":
            errors.append(f"{section_name} policy does not require passed target validation")
        required = section.get("required_fields")
        if not isinstance(required, list) or not required or any(not isinstance(item, str) or not item for item in required):
            errors.append(f"{section_name} required_fields is invalid")
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    failures = _policy_errors(policy)
    if failures:
        return failures
    evidence_ref = str(SELF_TEST_EVIDENCE.relative_to(ROOT)).replace("\\", "/")
    evidence_sha = _sha256(SELF_TEST_EVIDENCE)
    digest = "sha256:" + ("1" * 64)
    row = {"image_digest": digest}
    common = {
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "environment_id": "self-test-target",
        "target_validation": {
            "status": "passed",
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence_sha,
        },
    }
    identity = {
        **common,
        "schema_version": "mff.workload-identity-profile.v1",
        "authority_runtime": "spire",
        "identity_standard": "SPIFFE",
        "trust_domain": "self-test.invalid",
        "workload_selector": {"kind": "self-test"},
        "bootstrap_method": "self-test",
        "issuance": "self-test",
        "rotation": "self-test",
        "revocation": "self-test",
        "shared_static_credentials": False,
    }
    secret = {
        **common,
        "schema_version": "mff.secret-profile.v1",
        "authority_runtime": "openbao",
        "delivery_method": "self-test",
        "auth_method": "self-test",
        "secret_classes": ["self-test-class"],
        "rotation": "self-test",
        "revocation": "self-test",
        "contains_secret_material": False,
        "plaintext_credentials_committed": False,
    }
    if _identity_errors("self-test", row, identity, policy):
        failures.append("valid synthetic workload identity profile was rejected")
    if _secret_errors("self-test", row, secret, policy):
        failures.append("valid synthetic secret profile was rejected")

    identity_mutations = (
        ("wrong runtime", "runtime_key", "wrong"),
        ("wrong authority", "authority_runtime", "not-spire"),
        ("wrong standard", "identity_standard", "not-spiffe"),
        ("shared static credentials", "shared_static_credentials", True),
    )
    for label, field, value in identity_mutations:
        candidate = json.loads(json.dumps(identity))
        candidate[field] = value
        if not _identity_errors("self-test", row, candidate, policy):
            failures.append(f"identity self-test failed to reject {label}")

    secret_mutations = (
        ("wrong authority", "authority_runtime", "not-openbao"),
        ("embedded secret material", "contains_secret_material", True),
        ("plaintext credentials", "plaintext_credentials_committed", True),
        ("empty secret classes", "secret_classes", []),
    )
    for label, field, value in secret_mutations:
        candidate = json.loads(json.dumps(secret))
        candidate[field] = value
        if not _secret_errors("self-test", row, candidate, policy):
            failures.append(f"secret self-test failed to reject {label}")

    for kind, payload, checker in (
        ("identity", identity, _identity_errors),
        ("secret", secret, _secret_errors),
    ):
        candidate = json.loads(json.dumps(payload))
        candidate["target_validation"]["evidence_sha256"] = "0" * 64
        if not checker("self-test", row, candidate, policy):
            failures.append(f"{kind} self-test failed to reject target evidence hash mismatch")
        candidate = json.loads(json.dumps(payload))
        candidate["target_validation"]["status"] = "pending"
        if not checker("self-test", row, candidate, policy):
            failures.append(f"{kind} self-test failed to reject unpassed target validation")
    return failures


def _contract_errors() -> tuple[list[str], int, int, int, int]:
    errors: list[str] = []
    policy = _load(POLICY)
    errors.extend(_policy_errors(policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, 0, 0, 0, 0
    defaults = contract.get("defaults_for_unresolved_fields", {})
    identity_resolved = identity_unresolved = secret_resolved = secret_unresolved = 0
    for row in contract.get("runtimes", []):
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))
        identity_ref = row.get("workload_identity_profile", defaults.get("workload_identity_profile"))
        if identity_ref in (None, "", [], {}):
            identity_unresolved += 1
        else:
            path = _repo_file(identity_ref)
            if path is None:
                errors.append(f"{key}: workload_identity_profile is not an existing repository file")
            else:
                try:
                    payload = _load(path)
                except Exception as exc:
                    errors.append(f"{key}: workload identity profile is unreadable ({type(exc).__name__})")
                else:
                    for error in _identity_errors(key, row, payload, policy):
                        errors.append(f"{key}: {error}")
                    if not _identity_errors(key, row, payload, policy):
                        identity_resolved += 1
        secret_ref = row.get("secret_profile", defaults.get("secret_profile"))
        if secret_ref in (None, "", [], {}):
            secret_unresolved += 1
        else:
            path = _repo_file(secret_ref)
            if path is None:
                errors.append(f"{key}: secret_profile is not an existing repository file")
            else:
                try:
                    payload = _load(path)
                except Exception as exc:
                    errors.append(f"{key}: secret profile is unreadable ({type(exc).__name__})")
                else:
                    for error in _secret_errors(key, row, payload, policy):
                        errors.append(f"{key}: {error}")
                    if not _secret_errors(key, row, payload, policy):
                        secret_resolved += 1
    return errors, identity_resolved, identity_unresolved, secret_resolved, secret_unresolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral workload identity and secret profiles.")
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
        print("PASS: identity/secret profile validator rejects authority drift, static credentials, secret material, and unbound target evidence")
        return 0

    errors, identity_resolved, identity_unresolved, secret_resolved, secret_unresolved = _contract_errors()
    if errors:
        for error in errors:
            print(f"PROFILE BLOCKER: {error}")
        return 2
    print(f"PASS: validated {identity_resolved} resolved workload identity profiles; {identity_unresolved} remain unresolved")
    print(f"PASS: validated {secret_resolved} resolved secret profiles; {secret_unresolved} remain unresolved")
    print("BOUNDARY: unresolved profiles remain fail closed; no SPIRE trust domain, OpenBao production auth, credential, secret delivery, or target execution is claimed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
