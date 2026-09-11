from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse

from app import main
from app.auth import _PUBLIC_PRODUCTION_PATHS
from app.config import Settings


def _healthy_metadata():
    return {
        "balanced": True,
        "succeeded_without_journal": 0,
        "provider_attention_required": 0,
        "provider_attention": [],
    }


@pytest.mark.asyncio
async def test_live_funds_readiness_requires_runtime_health_and_audit_integrity(monkeypatch):
    async def healthy_components():
        return {"all_required_runtime_healthy": True, "components": []}

    cfg = Settings(environment="production", live_funds_enabled=True, production_mode="pilot")
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "probe_components", healthy_components)
    monkeypatch.setattr(main, "_audit_readiness", lambda: {"valid": True, "events": 7, "broken_at": None})
    monkeypatch.setattr(main, "reconcile", _healthy_metadata)
    monkeypatch.setattr(main, "production_readiness", lambda: {"ready_for_live_funds": True, "checks": []})

    snapshot = await main._readiness_snapshot()
    assert snapshot["service_ready"] is True
    assert snapshot["production_funds_gate"] is True


@pytest.mark.asyncio
async def test_unhealthy_runtime_closes_traffic_and_funds_readiness(monkeypatch):
    async def unhealthy_components():
        return {"all_required_runtime_healthy": False, "components": [{"key": "tigerbeetle", "state": "unreachable"}]}

    cfg = Settings(environment="production", live_funds_enabled=True, production_mode="pilot")
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "probe_components", unhealthy_components)
    monkeypatch.setattr(main, "_audit_readiness", lambda: {"valid": True, "events": 7, "broken_at": None})
    monkeypatch.setattr(main, "reconcile", _healthy_metadata)
    monkeypatch.setattr(main, "production_readiness", lambda: {"ready_for_live_funds": True, "checks": []})

    snapshot = await main._readiness_snapshot()
    assert snapshot["service_ready"] is False
    assert snapshot["production_funds_gate"] is False


@pytest.mark.asyncio
async def test_broken_audit_chain_closes_readiness(monkeypatch):
    async def healthy_components():
        return {"all_required_runtime_healthy": True, "components": []}

    cfg = Settings(environment="production", live_funds_enabled=False, production_mode="shadow")
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "probe_components", healthy_components)
    monkeypatch.setattr(main, "_audit_readiness", lambda: {"valid": False, "events": 7, "broken_at": "4"})
    monkeypatch.setattr(main, "reconcile", _healthy_metadata)
    monkeypatch.setattr(main, "production_readiness", lambda: {"ready_for_live_funds": False, "checks": []})

    snapshot = await main._readiness_snapshot()
    assert snapshot["service_ready"] is False
    assert snapshot["production_funds_gate"] is False


@pytest.mark.asyncio
async def test_succeeded_payment_without_journal_closes_readiness(monkeypatch):
    async def healthy_components():
        return {"all_required_runtime_healthy": True, "components": []}

    cfg = Settings(environment="production", live_funds_enabled=False, production_mode="shadow")
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "probe_components", healthy_components)
    monkeypatch.setattr(main, "_audit_readiness", lambda: {"valid": True, "events": 7, "broken_at": None})
    monkeypatch.setattr(
        main,
        "reconcile",
        lambda: {"balanced": True, "succeeded_without_journal": 1, "provider_attention_required": 0, "provider_attention": []},
    )
    monkeypatch.setattr(main, "reconcile_monetary_truth", lambda: {"consistent": True})
    monkeypatch.setattr(main, "production_readiness", lambda: {"ready_for_live_funds": False, "checks": []})

    snapshot = await main._readiness_snapshot()
    assert snapshot["metadata_reconciliation"]["consistent"] is False
    assert snapshot["service_ready"] is False
    assert snapshot["production_funds_gate"] is False


def test_reconciliation_marks_succeeded_without_journal_unbalanced(monkeypatch):
    monkeypatch.setattr(
        main,
        "reconcile",
        lambda: {"balanced": True, "succeeded_without_journal": 1, "provider_attention_required": 0, "provider_attention": []},
    )
    monkeypatch.setattr(main, "reconcile_monetary_truth", lambda: {"consistent": True})

    result = main.reconciliation()
    assert result["metadata_balanced"] is False
    assert result["balanced"] is False


@pytest.mark.asyncio
async def test_ready_endpoint_returns_503_when_service_is_not_ready(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(environment="production"))
    monkeypatch.setattr(
        main,
        "_readiness_snapshot",
        lambda: _async_value({"service_ready": False, "production_funds_gate": False, "components": [{"key": "secret-internal"}]}),
    )
    response = await main.ready()
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "not_ready"}


@pytest.mark.asyncio
async def test_ready_endpoint_redacts_internal_details_in_production(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(environment="production"))
    monkeypatch.setattr(
        main,
        "_readiness_snapshot",
        lambda: _async_value({"service_ready": True, "production_funds_gate": False, "components": [{"key": "secret-internal"}]}),
    )
    response = await main.ready()
    assert response == {"status": "ready"}


def test_health_endpoint_redacts_runtime_mode_in_production(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(environment="production", live_funds_enabled=True, production_mode="live"))
    assert main.health() == {"status": "ok"}


async def _async_value(value):
    return value


def test_orchestrator_probe_paths_are_public_but_business_api_is_not():
    assert "/health" in _PUBLIC_PRODUCTION_PATHS
    assert "/ready" in _PUBLIC_PRODUCTION_PATHS
    assert "/v1/payments/intents" not in _PUBLIC_PRODUCTION_PATHS