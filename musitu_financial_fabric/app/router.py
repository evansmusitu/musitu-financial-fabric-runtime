from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class RouteScore:
    rail: str
    score: float
    cost_bps: int
    latency_ms: int
    success_probability: float


DEFAULT_ROUTES = {
    "internal": dict(cost_bps=0, latency_ms=25, success_probability=0.9999),
    "ecocash": dict(cost_bps=250, latency_ms=1200, success_probability=0.97),
    "bank": dict(cost_bps=100, latency_ms=2500, success_probability=0.96),
    "card": dict(cost_bps=300, latency_ms=900, success_probability=0.94),
    "stablecoin": dict(cost_bps=40, latency_ms=1800, success_probability=0.985),
}


def score_route(rail: str) -> RouteScore:
    m = DEFAULT_ROUTES[rail]
    score = (m["success_probability"] * 1000.0) - (m["cost_bps"] * 0.35) - (m["latency_ms"] * 0.01)
    return RouteScore(rail=rail, score=round(score, 3), **m)


def choose_route(allowed_rails: list[str]) -> RouteScore:
    eligible = [r for r in allowed_rails if r in DEFAULT_ROUTES]
    if settings.is_production:
        enabled = set(settings.production_enabled_rails)
        eligible = [r for r in eligible if r in enabled]
    candidates = [score_route(r) for r in eligible]
    if not candidates:
        raise ValueError("no eligible rails")
    return max(candidates, key=lambda x: x.score)
