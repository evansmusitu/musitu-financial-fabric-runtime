from __future__ import annotations

import pytest

from app import router
from app.config import Settings


def test_production_auto_route_uses_only_enabled_rails(monkeypatch):
    cfg = Settings(environment="production", production_enabled_rails=("ecocash",))
    monkeypatch.setattr(router, "settings", cfg)

    selected = router.choose_route(list(router.DEFAULT_ROUTES))

    assert selected.rail == "ecocash"


def test_production_agent_auto_route_intersects_mandate_with_enabled_rails(monkeypatch):
    cfg = Settings(environment="production", production_enabled_rails=("ecocash",))
    monkeypatch.setattr(router, "settings", cfg)

    selected = router.choose_route(["internal", "ecocash"])

    assert selected.rail == "ecocash"


def test_production_auto_route_fails_closed_when_no_enabled_candidate(monkeypatch):
    cfg = Settings(environment="production", production_enabled_rails=("ecocash",))
    monkeypatch.setattr(router, "settings", cfg)

    with pytest.raises(ValueError, match="no eligible rails"):
        router.choose_route(["internal", "bank"])


def test_sandbox_auto_route_keeps_existing_scoring(monkeypatch):
    cfg = Settings(environment="sandbox", production_enabled_rails=())
    monkeypatch.setattr(router, "settings", cfg)

    selected = router.choose_route(["internal", "ecocash"])

    assert selected.rail == "internal"
