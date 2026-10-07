from __future__ import annotations

from app import component_registry, production, service, sovereign


def test_sovereign_phase1_does_not_become_a_production_rail():
    assert production._PRODUCTION_IMPLEMENTED_RAILS == {"ecocash"}
    assert "sovereign" not in service.RAILS


def test_authoritative_required_component_registry_remains_unchanged():
    components = component_registry.component_manifest()
    assert len(components) == 39
    assert all(item["required"] is True for item in components)


def test_sovereign_capability_manifest_is_reference_only():
    capabilities = sovereign.sovereign_capabilities()
    assert {item["key"] for item in capabilities} == {
        "sovereign-directory",
        "sovereign-qr",
        "request-to-pay",
        "zimbabwe-qr-profile",
        "participant-certification",
        "switch-transfer-contract",
        "clearing-reference-ledger",
        "scheme-exceptions",
        "country-profile-gate",
        "country-adapter-conformance",
    }
    assert all(item["phase"] == "reference" for item in capabilities)
    assert all(item["production_enabled"] is False for item in capabilities)
    assert all(item["moves_funds"] is False for item in capabilities)
