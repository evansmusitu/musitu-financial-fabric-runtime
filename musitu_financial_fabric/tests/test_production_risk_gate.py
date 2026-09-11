from __future__ import annotations

from app.config import Settings
from app.risk import evaluate_reference_risk


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _production_settings():
    return Settings(
        environment="production",
        risk_gate_url="https://risk.invalid/decision",
        risk_gate_token="test-token",
    )


def test_tazama_only_evidence_is_denied(monkeypatch):
    monkeypatch.setattr("app.risk.settings", _production_settings())
    monkeypatch.setattr(
        "app.risk.httpx.post",
        lambda *args, **kwargs: _Response({
            "allow": True,
            "score": 1,
            "reason": "allow",
            "decision_id": "risk-1",
            "engines": ["tazama"],
        }),
    )
    decision = evaluate_reference_risk(amount_minor=100, payer_ref="payer", description=None)
    assert decision.allow is False
    assert decision.reason == "production_risk_evidence_incomplete"


def test_tazama_and_watchman_evidence_is_accepted(monkeypatch):
    monkeypatch.setattr("app.risk.settings", _production_settings())
    monkeypatch.setattr(
        "app.risk.httpx.post",
        lambda *args, **kwargs: _Response({
            "allow": True,
            "score": 7,
            "reason": "allow",
            "decision_id": "risk-2",
            "engines": ["tazama", "watchman"],
        }),
    )
    decision = evaluate_reference_risk(amount_minor=100, payer_ref="payer", description="ok")
    assert decision.allow is True
    assert decision.score == 7
    assert decision.decision_id == "risk-2"
