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
SOURCE_POLICY = TARGET / "operational-profile-policy.json"
POLICY = TARGET / "operational-target-evidence-policy.json"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.operational-target-evidence-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.operational-profile-policy.v1"
DESCRIPTOR_SCHEMA = "mff.operational-target-validation.v1"
PROJECTION = "canonical_profile_without_target_validation"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_PROFILE_KINDS = {
    "probe_profile": {"profile_schema_version": "mff.probe-profile.v1"},
    "network_profile": {"profile_schema_version": "mff.network-profile.v1"},
    "disruption_budget_profile": {"profile_schema_version": "mff.disruption-budget-profile.v1"},
    "anti_affinity_profile": {"profile_schema_version": "mff.anti-affinity-profile.v1"},
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
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profile_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "target_validation"}


def _policy_errors(policy: object, source_policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["operational target-evidence policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("operational target-evidence policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("operational target-evidence policy is not anchored to the sealed runtime release")
    if policy.get("source_profile_policy_schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("operational target-evidence source policy schema is invalid")
    if policy.get("descriptor_schema_version") != DESCRIPTOR_SCHEMA:
        errors.append("operational target-validation descriptor schema is invalid")
    if policy.get("profile_semantics_projection") != PROJECTION:
        errors.append("operational target-evidence profile semantics projection is invalid")
    if policy.get("profile_kinds") != EXPECTED_PROFILE_KINDS:
        errors.append("operational target-evidence profile-kind policy is invalid")
    if policy.get("descriptor_required_metadata") != EXPECTED_DESCRIPTOR_METADATA:
        errors.append("operational target-validation descriptor metadata policy is invalid")
    if not isinstance(source_policy, dict):
        return errors + ["operational source policy root must be an object"]
    if source_policy.get("schema_version") != policy.get("source_profile_policy_schema_version"):
        errors.append("operational target-evidence policy does not match source profile policy schema")
    if source_policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("operational source policy is not anchored to the sealed runtime release")
    profiles = source_policy.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(EXPECTED_PROFILE_KINDS):
        errors.append("operational source profile inventory drifted")
    else:
        for kind, expected in EXPECTED_PROFILE_KINDS.items():
            section = profiles.get(kind)
            if not isinstance(section, dict):
                errors.append(f"{kind} source profile policy section is missing")
            elif section.get("profile_schema_version") != expected["profile_schema_version"]:
                errors.append(f"{kind} source profile schema drifted")
            elif section.get("target_validation_status_required_for_resolution") != "passed":
                errors.append(f"{kind} source profile no longer requires passed target validation")
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


def _profile_errors(kind: str, key: str, row: dict[str, Any], payload: object, policy: dict[str, Any], source_policy_sha256: str) -> list[str]:
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
    evidence_errors, evidence_path = _evidence_errors(payload.get("target_validation"))
    errors.extend(evidence_errors)
    if evidence_path is None:
        return errors
    try:
        descriptor = _load(evidence_path)
    except Exception as exc:
        errors.append(f"target_validation evidence must be a JSON operational descriptor ({type(exc).__name__})")
        return errors
    if not isinstance(descriptor, dict):
        return errors + ["operational target-validation descriptor root must be an object"]
    if descriptor.get("schema_version") != policy.get("descriptor_schema_version"):
        errors.append("operational target-validation descriptor schema_version is invalid")
    if descriptor.get("profile_kind") != kind:
        errors.append("operational target-validation descriptor profile_kind does not match profile")
    direct = {
        "runtime_key": key,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": payload.get("image_digest"),
        "environment_id": environment,
        "profile_schema_version": payload.get("schema_version"),
        "source_policy_sha256": source_policy_sha256,
    }
    for field, expected in direct.items():
        if descriptor.get(field) != expected:
            errors.append(f"operational target-validation descriptor {field} does not match profile authority")
    declared_semantics = str(descriptor.get("profile_semantics_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(declared_semantics):
        errors.append("operational target-validation descriptor profile_semantics_sha256 is missing or malformed")
    else:
        try:
            expected_semantics = _canonical_sha256(_profile_projection(payload))
        except (TypeError, ValueError):
            errors.append(f"{kind} profile semantics are not canonical-JSON hashable")
        else:
            if declared_semantics != expected_semantics:
                errors.append("operational target-validation descriptor semantic hash does not match profile")
    for field in policy.get("descriptor_required_metadata", []):
        value = descriptor.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"operational target-validation descriptor {field} is missing")
    return errors


def _write_json(path: Path, payload: object) -> str:
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    return _sha256(path)


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source_policy)
    if failures:
        return failures
    digest = "sha256:" + ("1" * 64)
    row = {"image_digest": digest}
    source_policy_sha = _sha256(SOURCE_POLICY)
    descriptor_path = ROOT / ".mff-operational-target-validation-self-test.tmp.json"
    common = {"runtime_key": "self-test", "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT, "image_digest": digest, "environment_id": "self-test-target"}
    profiles = {
        "probe_profile": {**common, "schema_version": "mff.probe-profile.v1", "startup": {"status": "not_applicable", "rationale": "synthetic self-test"}, "readiness": {"status": "not_applicable", "rationale": "synthetic self-test"}, "liveness": {"status": "not_applicable", "rationale": "synthetic self-test"}},
        "network_profile": {**common, "schema_version": "mff.network-profile.v1", "default_deny_inherited": True, "ingress_allow_rules": [], "egress_allow_rules": [], "dns_policy": {"mode": "synthetic-self-test"}},
        "disruption_budget_profile": {**common, "schema_version": "mff.disruption-budget-profile.v1", "status": "not_applicable", "rationale": "synthetic self-test"},
        "anti_affinity_profile": {**common, "schema_version": "mff.anti-affinity-profile.v1", "status": "not_applicable", "rationale": "synthetic self-test"},
    }
    def descriptor_for(kind: str, profile: dict[str, Any]) -> dict[str, Any]:
        return {"schema_version": DESCRIPTOR_SCHEMA, "profile_kind": kind, "runtime_key": profile["runtime_key"], "authoritative_runtime_base_commit": profile["authoritative_runtime_base_commit"], "image_digest": profile["image_digest"], "environment_id": profile["environment_id"], "profile_schema_version": profile["schema_version"], "source_policy_sha256": source_policy_sha, "profile_semantics_sha256": _canonical_sha256(_profile_projection(profile)), "validation_method": "validator-self-test", "verifier": "validator-self-test", "trust_model": "synthetic-self-test-only"}
    try:
        for kind, base_profile in profiles.items():
            descriptor = descriptor_for(kind, base_profile)
            evidence_sha = _write_json(descriptor_path, descriptor)
            profile = json.loads(json.dumps(base_profile))
            profile["target_validation"] = {"status": "passed", "evidence_ref": descriptor_path.relative_to(ROOT).as_posix(), "evidence_sha256": evidence_sha}
            if _profile_errors(kind, "self-test", row, profile, policy, source_policy_sha):
                failures.append(f"valid synthetic {kind} target descriptor was rejected")
            mutations = [("profile kind", "profile_kind", "wrong-kind"), ("runtime", "runtime_key", "wrong-runtime"), ("sealed release", "authoritative_runtime_base_commit", "0" * 40), ("image digest", "image_digest", "sha256:" + ("2" * 64)), ("environment", "environment_id", "wrong-target"), ("profile schema", "profile_schema_version", "wrong-schema"), ("source policy", "source_policy_sha256", "0" * 64), ("semantic hash", "profile_semantics_sha256", "0" * 64), ("validation metadata", "validation_method", "")]
            for label, field, value in mutations:
                bad_descriptor = dict(descriptor)
                bad_descriptor[field] = value
                bad = json.loads(json.dumps(profile))
                bad["target_validation"]["evidence_sha256"] = _write_json(descriptor_path, bad_descriptor)
                if not _profile_errors(kind, "self-test", row, bad, policy, source_policy_sha):
                    failures.append(f"{kind} target-evidence self-test failed to reject descriptor {label} drift")
            _write_json(descriptor_path, descriptor)
            bad = json.loads(json.dumps(profile))
            bad["target_validation"]["evidence_sha256"] = "0" * 64
            if not _profile_errors(kind, "self-test", row, bad, policy, source_policy_sha):
                failures.append(f"{kind} target-evidence self-test failed to reject retained-byte hash mismatch")
            mutated_profile = json.loads(json.dumps(profile))
            if kind == "probe_profile": mutated_profile["readiness"]["rationale"] = "changed semantic"
            elif kind == "network_profile": mutated_profile["default_deny_inherited"] = False
            else: mutated_profile["rationale"] = "changed semantic"
            mutated_profile["target_validation"]["evidence_sha256"] = _write_json(descriptor_path, descriptor)
            if not _profile_errors(kind, "self-test", row, mutated_profile, policy, source_policy_sha):
                failures.append(f"{kind} target-evidence self-test failed to reject profile semantic drift")
        return failures
    finally:
        descriptor_path.unlink(missing_ok=True)


def _contract_errors() -> tuple[list[str], dict[str, tuple[int, int]]]:
    errors: list[str] = []
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    errors.extend(_policy_errors(policy, source_policy))
    source_policy_sha = _sha256(SOURCE_POLICY)
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
        for kind in EXPECTED_PROFILE_KINDS:
            ref = row.get(kind, defaults.get(kind))
            if ref in (None, "", [], {}):
                counts[kind][1] += 1
                continue
            path = _repo_file(ref)
            if path is None:
                errors.append(f"{key}: {kind} is not an existing repository file")
                continue
            try:
                payload = _load(path)
            except Exception as exc:
                errors.append(f"{key}: {kind} is unreadable or invalid JSON ({type(exc).__name__})")
                continue
            profile_errors = _profile_errors(kind, key, row, payload, policy, source_policy_sha)
            errors.extend(f"{key}: {kind}_target_evidence: {error}" for error in profile_errors)
            if not profile_errors:
                counts[kind][0] += 1
    return errors, {kind: (value[0], value[1]) for kind, value in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral operational target-evidence descriptors.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        failures = _self_test()
        if failures:
            for failure in failures: print(f"SELF-TEST FAILURE: {failure}")
            return 4
        print("PASS: operational target-evidence validator rejects byte-valid but semantically unbound probe/network/disruption/anti-affinity descriptors and retained-byte drift")
        return 0
    errors, counts = _contract_errors()
    if errors:
        for error in errors: print(f"OPERATIONAL TARGET EVIDENCE BLOCKER: {error}")
        return 2
    for kind in EXPECTED_PROFILE_KINDS:
        resolved, unresolved = counts[kind]
        print(f"PASS: {kind}_target_evidence: validated {resolved} resolved profiles; {unresolved} remain unresolved")
    print("BOUNDARY: unresolved operational evidence does not establish runtime health, availability, network authorization, disruption behavior, scheduler admission behavior, target health, deployment, production authorization, or independent validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
