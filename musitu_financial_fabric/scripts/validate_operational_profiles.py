from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "operational-profile-policy.json"
SELF_TEST_EVIDENCE = TARGET / ".validation" / "operational-profile-self-test-evidence.txt"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
EXPECTED_PROFILE_FIELDS = (
    "probe_profile",
    "network_profile",
    "disruption_budget_profile",
    "anti_affinity_profile",
)
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
PDB_PERCENT = re.compile(r"^(?:0|[1-9][0-9]?|100)%$")
NAMED_PORT = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
INT32_MAX = (1 << 31) - 1


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


def _common_errors(
    key: str,
    row: dict[str, Any],
    payload: object,
    schema: str,
    required_fields: list[str],
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
    if not isinstance(payload.get("environment_id"), str) or not payload["environment_id"].strip():
        errors.append("profile environment_id is missing")
    errors.extend(_target_validation_errors(payload.get("target_validation")))
    return errors


def _valid_network_port(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 1 <= value <= 65535
    if not isinstance(value, str):
        return False
    name = value.strip()
    return (
        1 <= len(name) <= 15
        and bool(NAMED_PORT.fullmatch(name))
        and any(char.isalpha() for char in name)
    )


def _probe_mechanism_errors(name: str, mechanism: object, section: dict[str, Any]) -> list[str]:
    if not isinstance(mechanism, dict) or not mechanism:
        return [f"{name} configured probe mechanism must be a non-empty object"]
    probe_type = mechanism.get("type")
    allowed = set(section.get("configured_probe_mechanism_types", []))
    if probe_type not in allowed:
        return [f"{name} configured probe mechanism.type must be one of {sorted(allowed)}"]
    errors: list[str] = []
    if probe_type == "exec":
        command = mechanism.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            errors.append(f"{name} exec probe command must be a non-empty string array")
    elif probe_type == "grpc":
        port = mechanism.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append(f"{name} grpc probe port must be a numeric port from 1 through 65535")
        service = mechanism.get("service")
        if service is not None and (not isinstance(service, str) or not service.strip()):
            errors.append(f"{name} grpc probe service must be a non-empty string when provided")
    elif probe_type == "http_get":
        if not _valid_network_port(mechanism.get("port")):
            errors.append(f"{name} http_get probe port must be an explicit numeric or named port")
        path = mechanism.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"{name} http_get probe path must be an absolute HTTP path")
        scheme = mechanism.get("scheme", "HTTP")
        if scheme not in {"HTTP", "HTTPS"}:
            errors.append(f"{name} http_get probe scheme must be HTTP or HTTPS")
    elif probe_type == "tcp_socket":
        if not _valid_network_port(mechanism.get("port")):
            errors.append(f"{name} tcp_socket probe port must be an explicit numeric or named port")
    return errors


def _probe_timing_errors(name: str, timing: object, section: dict[str, Any]) -> list[str]:
    if not isinstance(timing, dict) or not timing:
        return [f"{name} configured probe timing_policy must be a non-empty object"]
    errors: list[str] = []
    required = section.get("configured_probe_timing_required_fields", [])
    for field in required:
        value = timing.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errors.append(f"{name} configured probe {field} must be an integer >= 1")
    initial_delay = timing.get("initial_delay_seconds")
    if initial_delay is not None and (
        isinstance(initial_delay, bool) or not isinstance(initial_delay, int) or initial_delay < 0
    ):
        errors.append(f"{name} configured probe initial_delay_seconds must be an integer >= 0")
    termination = timing.get("termination_grace_period_seconds")
    if termination is not None:
        if name == "readiness":
            errors.append("readiness probe must not set termination_grace_period_seconds")
        elif isinstance(termination, bool) or not isinstance(termination, int) or termination < 1:
            errors.append(f"{name} configured probe termination_grace_period_seconds must be an integer >= 1")
    if name in {"startup", "liveness"} and timing.get("success_threshold") != 1:
        errors.append(f"{name} configured probe success_threshold must equal 1")
    return errors


def _probe_block_errors(name: str, block: object, section: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(block, dict):
        return [f"{name} probe must be an object"]
    status = block.get("status")
    if status not in set(section.get("allowed_probe_statuses", [])):
        return [f"{name} probe status is invalid"]
    if status == "configured":
        for field in section.get("configured_probe_required_fields", []):
            if not _nonempty(block.get(field)):
                errors.append(f"{name} configured probe missing {field}")
        errors.extend(_probe_mechanism_errors(name, block.get("mechanism"), section))
        errors.extend(_probe_timing_errors(name, block.get("timing_policy"), section))
    elif status == "not_applicable":
        for field in section.get("not_applicable_required_fields", []):
            if not _nonempty(block.get(field)):
                errors.append(f"{name} not-applicable probe missing {field}")
    return errors


def _probe_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["profiles"]["probe_profile"]
    errors = _common_errors(
        key, row, payload, str(section["profile_schema_version"]), list(section["required_fields"])
    )
    if not isinstance(payload, dict):
        return errors
    for name in ("startup", "readiness", "liveness"):
        errors.extend(_probe_block_errors(name, payload.get(name), section))
    return errors


def _network_port_errors(direction: str, rule_index: int, ports: object, section: dict[str, Any]) -> list[str]:
    prefix = f"{direction}_allow_rules[{rule_index}].ports"
    if not isinstance(ports, list) or not ports:
        return [f"{prefix} must be a non-empty array so the rule cannot match all ports"]
    errors: list[str] = []
    allowed_protocols = set(section.get("allowed_protocols", []))
    for index, item in enumerate(ports):
        item_prefix = f"{prefix}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_prefix} must be an object")
            continue
        if "port" not in item or not _valid_network_port(item.get("port")):
            errors.append(f"{item_prefix}.port must be an explicit numeric port 1-65535 or valid named port")
        protocol = item.get("protocol", "TCP")
        if protocol not in allowed_protocols:
            errors.append(f"{item_prefix}.protocol must be one of {sorted(allowed_protocols)}")
        if "end_port" in item:
            start = item.get("port")
            end = item.get("end_port")
            if isinstance(start, bool) or not isinstance(start, int):
                errors.append(f"{item_prefix}.end_port is only valid with a numeric port")
            elif isinstance(end, bool) or not isinstance(end, int) or not (start <= end <= 65535):
                errors.append(f"{item_prefix}.end_port must be an integer from port through 65535")
    return errors


def _allow_rule_errors(direction: str, rules: object, section: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(rules, list):
        return [f"{direction}_allow_rules must be an array"]
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"{direction}_allow_rules[{index}] must be an object")
            continue
        for field in section.get("allow_rule_required_fields", []):
            if field not in rule:
                errors.append(f"{direction}_allow_rules[{index}] missing {field}")
        if not _nonempty(rule.get("peer")):
            errors.append(f"{direction}_allow_rules[{index}].peer is empty")
        errors.extend(_network_port_errors(direction, index, rule.get("ports"), section))
        if not isinstance(rule.get("rationale"), str) or not rule["rationale"].strip():
            errors.append(f"{direction}_allow_rules[{index}].rationale is empty")
    return errors


def _network_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["profiles"]["network_profile"]
    errors = _common_errors(
        key, row, payload, str(section["profile_schema_version"]), list(section["required_fields"])
    )
    if not isinstance(payload, dict):
        return errors
    if payload.get("default_deny_inherited") is not True:
        errors.append("network profile must preserve inherited default-deny")
    errors.extend(_allow_rule_errors("ingress", payload.get("ingress_allow_rules"), section))
    errors.extend(_allow_rule_errors("egress", payload.get("egress_allow_rules"), section))
    dns_policy = payload.get("dns_policy")
    if not isinstance(dns_policy, dict) or not dns_policy:
        errors.append("network profile dns_policy must be a non-empty object")
    return errors


def _valid_pdb_budget_value(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= INT32_MAX
    return isinstance(value, str) and bool(PDB_PERCENT.fullmatch(value.strip()))


def _disruption_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["profiles"]["disruption_budget_profile"]
    errors = _common_errors(
        key, row, payload, str(section["profile_schema_version"]), list(section["required_fields"])
    )
    if not isinstance(payload, dict):
        return errors
    status = payload.get("status")
    if status not in set(section.get("allowed_statuses", [])):
        return errors + ["disruption budget profile status is invalid"]
    if status == "configured":
        for field in section.get("configured_required_fields", []):
            if not _nonempty(payload.get(field)):
                errors.append(f"configured disruption budget profile missing {field}")
        selector = payload.get("selector")
        if not isinstance(selector, dict) or not selector:
            errors.append("configured disruption budget selector must be a non-empty object")
        budget = payload.get("budget")
        if not isinstance(budget, dict):
            errors.append("configured disruption budget budget must be an object")
        else:
            populated = [
                name for name in ("min_available", "max_unavailable")
                if _nonempty(budget.get(name))
            ]
            if len(populated) != 1:
                errors.append("configured disruption budget must set exactly one of min_available or max_unavailable")
            elif not _valid_pdb_budget_value(budget.get(populated[0])):
                errors.append(
                    f"configured disruption budget {populated[0]} must be a non-negative int32 or percentage from 0% through 100%"
                )
    elif status == "not_applicable":
        for field in section.get("not_applicable_required_fields", []):
            if not _nonempty(payload.get(field)):
                errors.append(f"not-applicable disruption budget profile missing {field}")
    return errors


def _anti_affinity_errors(key: str, row: dict[str, Any], payload: object, policy: dict[str, Any]) -> list[str]:
    section = policy["profiles"]["anti_affinity_profile"]
    errors = _common_errors(
        key, row, payload, str(section["profile_schema_version"]), list(section["required_fields"])
    )
    if not isinstance(payload, dict):
        return errors
    status = payload.get("status")
    if status not in set(section.get("allowed_statuses", [])):
        return errors + ["anti-affinity profile status is invalid"]
    if status == "configured":
        for field in section.get("configured_required_fields", []):
            if not _nonempty(payload.get(field)):
                errors.append(f"configured anti-affinity profile missing {field}")
        keys = payload.get("topology_keys")
        constraints = payload.get("constraints")
        if not isinstance(keys, list) or not keys or any(not isinstance(item, str) or not item.strip() for item in keys):
            errors.append("configured anti-affinity topology_keys must be a non-empty string array")
        if not isinstance(constraints, list) or not constraints or any(not _nonempty(item) for item in constraints):
            errors.append("configured anti-affinity constraints must be a non-empty array")
    elif status == "not_applicable":
        for field in section.get("not_applicable_required_fields", []):
            if not _nonempty(payload.get(field)):
                errors.append(f"not-applicable anti-affinity profile missing {field}")
    return errors


CHECKERS: dict[str, Callable[[str, dict[str, Any], object, dict[str, Any]], list[str]]] = {
    "probe_profile": _probe_errors,
    "network_profile": _network_errors,
    "disruption_budget_profile": _disruption_errors,
    "anti_affinity_profile": _anti_affinity_errors,
}


def _policy_errors(policy: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["operational profile policy root must be an object"]
    if policy.get("schema_version") != "mff.operational-profile-policy.v1":
        errors.append("operational profile policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("operational profile policy is not anchored to the sealed runtime release")
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(EXPECTED_PROFILE_FIELDS):
        errors.append("operational profile policy field set is invalid")
        return errors
    for field in EXPECTED_PROFILE_FIELDS:
        section = profiles.get(field)
        if not isinstance(section, dict):
            errors.append(f"{field} policy must be an object")
            continue
        if not isinstance(section.get("profile_schema_version"), str) or not section["profile_schema_version"]:
            errors.append(f"{field} profile_schema_version is invalid")
        required = section.get("required_fields")
        if not isinstance(required, list) or not required or any(not isinstance(item, str) or not item for item in required):
            errors.append(f"{field} required_fields is invalid")
        if section.get("target_validation_status_required_for_resolution") != "passed":
            errors.append(f"{field} policy does not require passed target validation")
    probe = profiles["probe_profile"]
    if set(probe.get("configured_probe_mechanism_types") or []) != {"exec", "grpc", "http_get", "tcp_socket"}:
        errors.append("probe profile mechanism type set is invalid")
    if probe.get("configured_probe_timing_required_fields") != [
        "period_seconds", "timeout_seconds", "failure_threshold", "success_threshold"
    ]:
        errors.append("probe profile timing field set is invalid")
    network = profiles["network_profile"]
    if network.get("default_deny_inherited_required") is not True:
        errors.append("network profile policy does not require inherited default-deny")
    if network.get("explicit_nonempty_ports_required_per_allow_rule") is not True:
        errors.append("network profile policy must forbid implicit all-port allow rules")
    if set(network.get("allowed_protocols") or []) != {"TCP", "UDP", "SCTP"}:
        errors.append("network profile policy protocol set is invalid")
    disruption = profiles["disruption_budget_profile"]
    if disruption.get("budget_value_semantics") != "non_negative_int32_or_percentage_0_100":
        errors.append("disruption budget policy value semantics are invalid")
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
    configured_probe = {
        "status": "configured",
        "mechanism": {"type": "http_get", "port": 8080, "path": "/healthz", "scheme": "HTTP"},
        "timing_policy": {
            "period_seconds": 10,
            "timeout_seconds": 2,
            "failure_threshold": 3,
            "success_threshold": 1,
            "initial_delay_seconds": 0,
        },
        "failure_semantics": "self-test",
    }
    payloads: dict[str, dict[str, Any]] = {
        "probe_profile": {
            **common,
            "schema_version": "mff.probe-profile.v1",
            "startup": configured_probe,
            "readiness": configured_probe,
            "liveness": configured_probe,
        },
        "network_profile": {
            **common,
            "schema_version": "mff.network-profile.v1",
            "default_deny_inherited": True,
            "ingress_allow_rules": [],
            "egress_allow_rules": [
                {
                    "peer": {"kind": "self-test"},
                    "ports": [{"port": 443, "protocol": "TCP"}],
                    "rationale": "self-test",
                }
            ],
            "dns_policy": {"mode": "self-test"},
        },
        "disruption_budget_profile": {
            **common,
            "schema_version": "mff.disruption-budget-profile.v1",
            "status": "configured",
            "selector": {"source": "self-test"},
            "budget": {"min_available": "50%"},
            "eviction_semantics": "self-test",
            "rationale": "self-test",
        },
        "anti_affinity_profile": {
            **common,
            "schema_version": "mff.anti-affinity-profile.v1",
            "status": "configured",
            "topology_keys": ["self-test"],
            "constraints": [{"source": "self-test"}],
            "rationale": "self-test",
        },
    }

    for field, payload in payloads.items():
        errors = CHECKERS[field]("self-test", row, payload, policy)
        if errors:
            failures.append(f"valid synthetic {field} was rejected: {errors}")

    for field, payload in payloads.items():
        candidate = json.loads(json.dumps(payload))
        candidate["runtime_key"] = "wrong-runtime"
        if not CHECKERS[field]("self-test", row, candidate, policy):
            failures.append(f"{field} self-test failed to reject runtime drift")

        candidate = json.loads(json.dumps(payload))
        candidate["authoritative_runtime_base_commit"] = "0" * 40
        if not CHECKERS[field]("self-test", row, candidate, policy):
            failures.append(f"{field} self-test failed to reject release drift")

        candidate = json.loads(json.dumps(payload))
        candidate["image_digest"] = "sha256:" + ("2" * 64)
        if not CHECKERS[field]("self-test", row, candidate, policy):
            failures.append(f"{field} self-test failed to reject image drift")

        candidate = json.loads(json.dumps(payload))
        candidate["target_validation"]["status"] = "pending"
        if not CHECKERS[field]("self-test", row, candidate, policy):
            failures.append(f"{field} self-test failed to reject unpassed target validation")

        candidate = json.loads(json.dumps(payload))
        candidate["target_validation"]["evidence_sha256"] = "0" * 64
        if not CHECKERS[field]("self-test", row, candidate, policy):
            failures.append(f"{field} self-test failed to reject target evidence hash mismatch")

    bad_probe = json.loads(json.dumps(payloads["probe_profile"]))
    del bad_probe["readiness"]["mechanism"]
    if not _probe_errors("self-test", row, bad_probe, policy):
        failures.append("probe self-test failed to reject incomplete configured readiness probe")

    bad_probe_type = json.loads(json.dumps(payloads["probe_profile"]))
    bad_probe_type["readiness"]["mechanism"] = {"type": "self-test"}
    if not _probe_errors("self-test", row, bad_probe_type, policy):
        failures.append("probe self-test failed to reject unsupported probe mechanism")

    bad_probe_timing = json.loads(json.dumps(payloads["probe_profile"]))
    bad_probe_timing["readiness"]["timing_policy"]["period_seconds"] = 0
    if not _probe_errors("self-test", row, bad_probe_timing, policy):
        failures.append("probe self-test failed to reject invalid period_seconds")

    bad_probe_success = json.loads(json.dumps(payloads["probe_profile"]))
    bad_probe_success["liveness"]["timing_policy"]["success_threshold"] = 2
    if not _probe_errors("self-test", row, bad_probe_success, policy):
        failures.append("probe self-test failed to enforce liveness success_threshold=1")

    bad_readiness_grace = json.loads(json.dumps(payloads["probe_profile"]))
    bad_readiness_grace["readiness"]["timing_policy"]["termination_grace_period_seconds"] = 5
    if not _probe_errors("self-test", row, bad_readiness_grace, policy):
        failures.append("probe self-test failed to reject readiness termination grace period")

    not_applicable_probe = json.loads(json.dumps(payloads["probe_profile"]))
    not_applicable_probe["liveness"] = {"status": "not_applicable"}
    if not _probe_errors("self-test", row, not_applicable_probe, policy):
        failures.append("probe self-test failed to require rationale for not-applicable probe")

    bad_network = json.loads(json.dumps(payloads["network_profile"]))
    bad_network["default_deny_inherited"] = False
    if not _network_errors("self-test", row, bad_network, policy):
        failures.append("network self-test failed to reject default-deny removal")

    bad_network_rule = json.loads(json.dumps(payloads["network_profile"]))
    bad_network_rule["egress_allow_rules"] = [
        {"peer": {"kind": "self-test"}, "ports": [], "rationale": "self-test"}
    ]
    if not _network_errors("self-test", row, bad_network_rule, policy):
        failures.append("network self-test failed to reject implicit all-port allow rule")

    bad_network_port = json.loads(json.dumps(payloads["network_profile"]))
    bad_network_port["egress_allow_rules"] = [
        {"peer": {"kind": "self-test"}, "ports": [{"protocol": "TCP"}], "rationale": "self-test"}
    ]
    if not _network_errors("self-test", row, bad_network_port, policy):
        failures.append("network self-test failed to require an explicit port in every allow entry")

    bad_network_protocol = json.loads(json.dumps(payloads["network_profile"]))
    bad_network_protocol["egress_allow_rules"] = [
        {"peer": {"kind": "self-test"}, "ports": [{"port": 443, "protocol": "ANY"}], "rationale": "self-test"}
    ]
    if not _network_errors("self-test", row, bad_network_protocol, policy):
        failures.append("network self-test failed to reject unsupported network protocol")

    bad_disruption = json.loads(json.dumps(payloads["disruption_budget_profile"]))
    bad_disruption["budget"] = {"min_available": 1, "max_unavailable": 1}
    if not _disruption_errors("self-test", row, bad_disruption, policy):
        failures.append("disruption self-test failed to reject ambiguous budget")

    bad_disruption_value = json.loads(json.dumps(payloads["disruption_budget_profile"]))
    bad_disruption_value["budget"] = {"min_available": "self-test"}
    if not _disruption_errors("self-test", row, bad_disruption_value, policy):
        failures.append("disruption self-test failed to reject invalid budget value")

    bad_disruption_percentage = json.loads(json.dumps(payloads["disruption_budget_profile"]))
    bad_disruption_percentage["budget"] = {"max_unavailable": "101%"}
    if not _disruption_errors("self-test", row, bad_disruption_percentage, policy):
        failures.append("disruption self-test failed to reject out-of-range percentage")

    bad_anti = json.loads(json.dumps(payloads["anti_affinity_profile"]))
    bad_anti["topology_keys"] = []
    if not _anti_affinity_errors("self-test", row, bad_anti, policy):
        failures.append("anti-affinity self-test failed to reject empty topology keys")

    return failures


def _contract_errors() -> tuple[list[str], dict[str, tuple[int, int]]]:
    errors: list[str] = []
    policy = _load(POLICY)
    errors.extend(_policy_errors(policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, {field: (0, 0) for field in EXPECTED_PROFILE_FIELDS}

    defaults = contract.get("defaults_for_unresolved_fields", {})
    counts = {field: [0, 0] for field in EXPECTED_PROFILE_FIELDS}

    for row in contract.get("runtimes", []):
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))
        for field in EXPECTED_PROFILE_FIELDS:
            value = row.get(field, defaults.get(field))
            if value in (None, "", [], {}):
                counts[field][1] += 1
                continue
            path = _repo_file(value)
            if path is None:
                errors.append(f"{key}: {field} is not an existing repository file")
                continue
            try:
                payload = _load(path)
            except Exception as exc:
                errors.append(f"{key}: {field} is unreadable or invalid JSON ({type(exc).__name__})")
                continue
            profile_errors = CHECKERS[field](key, row, payload, policy)
            for error in profile_errors:
                errors.append(f"{key}: {field}: {error}")
            if not profile_errors:
                counts[field][0] += 1

    return errors, {field: (values[0], values[1]) for field, values in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate provider-neutral probe, network, disruption, and topology profiles.")
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
        print("PASS: operational profile validator rejects drift, invalid probe mechanisms/timing, default-deny removal, implicit all-port rules, invalid disruption budgets, and unbound target evidence")
        return 0

    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"OPERATIONAL PROFILE BLOCKER: {error}")
        return 2
    for field in EXPECTED_PROFILE_FIELDS:
        resolved, unresolved = counts[field]
        print(f"PASS: {field}: validated {resolved} resolved profiles; {unresolved} remain unresolved")
    print("BOUNDARY: no probe mechanisms/timings, network allowlists, disruption budgets, topology constraints, or target execution are inferred from unresolved profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
