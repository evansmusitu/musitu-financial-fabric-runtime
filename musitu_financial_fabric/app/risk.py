from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import settings


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    score: int
    reason: str
    decision_id: str = ""


def _reference_risk(*, amount_minor: int, payer_ref: str | None, description: str | None) -> RiskDecision:
    score = 0
    if amount_minor >= 500_000:
        score += 40
    if not payer_ref:
        score += 10
    if description is not None and len(description) > 280:
        score += 10
    return RiskDecision(score < 80, min(score, 100), "allow" if score < 80 else "review_required", "sandbox-reference")


def _deny(reason: str) -> RiskDecision:
    return RiskDecision(False, 100, reason, "")


def evaluate_reference_risk(*, amount_minor: int, payer_ref: str | None, description: str | None) -> RiskDecision:
    """Sandbox heuristic; production requires evidenced decisions from Tazama and Watchman."""
    if not settings.is_production:
        return _reference_risk(amount_minor=amount_minor, payer_ref=payer_ref, description=description)
    if not settings.risk_gate_url:
        return _deny("production_risk_gate_unconfigured")

    headers = {"Content-Type": "application/json"}
    if settings.risk_gate_token:
        headers["Authorization"] = f"Bearer {settings.risk_gate_token}"
    payload = {
        "amount_minor": int(amount_minor),
        "payer_ref": payer_ref,
        "description": description,
        "required_engines": ["tazama", "watchman"],
    }
    try:
        response = httpx.post(settings.risk_gate_url, json=payload, headers=headers, timeout=5.0)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return _deny("production_risk_gate_unavailable")
    if not isinstance(data, dict) or not isinstance(data.get("allow"), bool):
        return _deny("production_risk_decision_malformed")
    try:
        score = int(data.get("score"))
    except Exception:
        return _deny("production_risk_score_malformed")
    if score < 0 or score > 100:
        return _deny("production_risk_score_out_of_range")
    engines = {str(value).lower() for value in data.get("engines", []) if isinstance(value, str)}
    if not {"tazama", "watchman"}.issubset(engines):
        return _deny("production_risk_evidence_incomplete")
    decision_id = str(data.get("decision_id") or "").strip()
    if not decision_id:
        return _deny("production_risk_decision_id_missing")
    reason = str(data.get("reason") or ("allow" if data["allow"] else "denied"))
    return RiskDecision(bool(data["allow"]), score, reason, decision_id)
