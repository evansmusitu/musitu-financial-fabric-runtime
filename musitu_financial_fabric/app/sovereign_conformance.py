from __future__ import annotations

from typing import Any

from .sovereign import country_profile_gate, sovereign_capabilities


GENERIC_ADAPTER_BEHAVIORS = (
    "transfer_submit",
    "transfer_status",
    "idempotency",
    "participant_addressing",
    "exception_mapping",
    "settlement_reference",
)


def _required_text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def evaluate_country_adapter_manifest(profile_key: str, manifest: dict[str, Any]) -> dict:
    profile_key = _required_text(profile_key, "profile key").lower()
    if not isinstance(manifest, dict):
        raise ValueError("adapter manifest must be an object")

    authority = _required_text(manifest.get("authority"), "authority")
    interface_version = _required_text(manifest.get("interface_version"), "interface version")
    source_evidence_ref = _required_text(manifest.get("source_evidence_ref"), "source evidence reference")

    raw_behaviors = manifest.get("behaviors")
    if not isinstance(raw_behaviors, dict):
        raise ValueError("adapter behaviors must be an object")

    normalized_behaviors: dict[str, dict[str, Any]] = {}
    missing_behaviors: list[str] = []
    for behavior in GENERIC_ADAPTER_BEHAVIORS:
        item = raw_behaviors.get(behavior)
        if item is None:
            normalized_behaviors[behavior] = {
                "supported": False,
                "mapping_ref": None,
            }
            missing_behaviors.append(behavior)
            continue
        if not isinstance(item, dict):
            raise ValueError(f"{behavior} behavior must be an object")

        supported = bool(item.get("supported", False))
        mapping_ref = str(item.get("mapping_ref") or "").strip()
        if supported and not mapping_ref:
            raise ValueError(f"{behavior} supported behavior requires mapping evidence")
        if not supported:
            missing_behaviors.append(behavior)
        normalized_behaviors[behavior] = {
            "supported": supported,
            "mapping_ref": mapping_ref or None,
        }

    gate = country_profile_gate(profile_key)
    external_ready = bool(gate["external_dependencies_ready"])
    adapter_ready = not missing_behaviors and external_ready

    return {
        "profile_key": profile_key,
        "authority": authority,
        "interface_version": interface_version,
        "source_evidence_ref": source_evidence_ref,
        "structurally_valid": True,
        "behaviors": normalized_behaviors,
        "missing_behaviors": missing_behaviors,
        "country_external_dependencies_ready": external_ready,
        "country_blockers": list(gate["blockers"]),
        "adapter_ready": adapter_ready,
        "production_enabled": False,
        "regulatory_authorized": False,
    }


def build_regulator_evaluation_pack(
    profile_key: str,
    manifest: dict[str, Any],
    uat_result: dict[str, Any],
) -> dict:
    if not isinstance(uat_result, dict):
        raise ValueError("UAT result must be an object")
    if uat_result.get("live_funds_moved") is not False:
        raise ValueError("evaluation pack requires a no-live-funds UAT result")
    if uat_result.get("production_authorized") is not False:
        raise ValueError("evaluation pack requires a non-production UAT result")

    conformance = evaluate_country_adapter_manifest(profile_key, manifest)
    capabilities = sovereign_capabilities()

    return {
        "profile_key": conformance["profile_key"],
        "adapter_conformance": conformance,
        "uat": {
            "scenario": uat_result.get("scenario"),
            "request_to_pay": uat_result.get("request_to_pay"),
            "switch": uat_result.get("switch"),
            "clearing": uat_result.get("clearing"),
            "exception": uat_result.get("exception"),
            "audit": uat_result.get("audit"),
            "side_effects": uat_result.get("side_effects"),
            "live_funds_moved": False,
            "production_authorized": False,
        },
        "sovereign_capabilities": [item["key"] for item in capabilities],
        "country_blockers": list(conformance["country_blockers"]),
        "claim_boundaries": {
            "rbz_approved": False,
            "zimswitch_authorized": False,
            "emvco_certified": False,
            "nipl_superiority_proven": False,
            "national_switch_integrated": False,
            "settlement_finality_proven": False,
        },
        "live_funds_moved": False,
        "production_authorized": False,
    }
