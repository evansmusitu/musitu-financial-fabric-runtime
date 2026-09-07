from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    score: int
    reason: str


def evaluate_reference_risk(*, amount_minor: int, payer_ref: str | None, description: str | None) -> RiskDecision:
    """Minimal deterministic sandbox guard. Tazama/Watchman remain mandatory production engines."""
    score = 0
    if amount_minor >= 500_000:
        score += 40
    if not payer_ref:
        score += 10
    if description is not None and len(description) > 280:
        score += 10
    return RiskDecision(score < 80, min(score, 100), "allow" if score < 80 else "review_required")
