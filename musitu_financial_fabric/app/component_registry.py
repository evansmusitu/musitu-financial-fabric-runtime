from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import os
from typing import Iterable

import httpx


@dataclass(frozen=True)
class Component:
    key: str
    name: str
    layer: str
    kind: str
    required: bool = True
    health_env: str | None = None
    default_health_path: str = "/health"


COMPONENTS: tuple[Component, ...] = (
    Component("tigerbeetle", "TigerBeetle", "ledger", "runtime", health_env="MUSITU_TIGERBEETLE_HEALTH_URL"),
    Component("hyperswitch", "Hyperswitch", "payment-orchestration", "runtime", health_env="MUSITU_HYPERSWITCH_HEALTH_URL"),
    Component("mojaloop", "Mojaloop", "switch-clearing", "runtime", health_env="MUSITU_MOJALOOP_HEALTH_URL"),
    Component("paymenthub", "Mifos Payment Hub EE", "fsp-edge", "runtime", health_env="MUSITU_PAYMENTHUB_HEALTH_URL"),
    Component("gazelle", "Mifos Gazelle", "network-lab", "runtime", health_env="MUSITU_GAZELLE_HEALTH_URL"),
    Component("fineract", "Apache Fineract", "banking-products", "runtime", health_env="MUSITU_FINERACT_HEALTH_URL"),
    Component("tazama", "Tazama", "fraud-aml", "runtime", health_env="MUSITU_TAZAMA_HEALTH_URL"),
    Component("watchman", "Moov Watchman", "sanctions", "runtime", health_env="MUSITU_WATCHMAN_HEALTH_URL"),
    Component("killbill", "Kill Bill", "billing", "runtime", health_env="MUSITU_KILLBILL_HEALTH_URL"),
    Component("cardvault", "Hyperswitch Card Vault", "card-security", "runtime", health_env="MUSITU_CARDVAULT_HEALTH_URL"),
    Component("keycloak", "Keycloak", "human-iam", "runtime", health_env="MUSITU_KEYCLOAK_HEALTH_URL"),
    Component("openfga", "OpenFGA", "authorization", "runtime", health_env="MUSITU_OPENFGA_HEALTH_URL"),
    Component("opa", "Open Policy Agent", "policy", "runtime", health_env="MUSITU_OPA_HEALTH_URL"),
    Component("spire", "SPIFFE/SPIRE", "workload-identity", "runtime", health_env="MUSITU_SPIRE_HEALTH_URL"),
    Component("openbao", "OpenBao", "secrets-pki", "runtime", health_env="MUSITU_OPENBAO_HEALTH_URL"),
    Component("temporal", "Temporal", "durable-workflows", "runtime", health_env="MUSITU_TEMPORAL_HEALTH_URL"),
    Component("nats", "NATS", "event-transport", "runtime", health_env="MUSITU_NATS_HEALTH_URL"),
    Component("postgres", "PostgreSQL", "domain-store", "runtime", health_env="MUSITU_POSTGRES_HEALTH_URL"),
    Component("clickhouse", "ClickHouse", "analytics", "runtime", health_env="MUSITU_CLICKHOUSE_HEALTH_URL"),
    Component("valkey", "Valkey", "cache", "runtime", health_env="MUSITU_VALKEY_HEALTH_URL"),
    Component("opensearch", "OpenSearch", "investigation-search", "runtime", health_env="MUSITU_OPENSEARCH_HEALTH_URL"),
    Component("envoy", "Envoy", "api-edge", "runtime", health_env="MUSITU_ENVOY_HEALTH_URL"),
    Component("coraza", "Coraza", "waf", "runtime", health_env="MUSITU_CORAZA_HEALTH_URL"),
    Component("otel", "OpenTelemetry", "telemetry", "runtime", health_env="MUSITU_OTEL_HEALTH_URL"),
    Component("sigstore", "Sigstore/Cosign", "supply-chain", "tooling"),
    Component("opentofu", "OpenTofu", "infrastructure-as-code", "tooling"),
    Component("openapi-generator", "OpenAPI Generator", "sdk-generation", "tooling"),
    Component("prism", "Prism", "contract-mocking", "tooling"),
    Component("gsma-mmapi", "GSMA Mobile Money API", "mobile-money-standard", "protocol"),
    Component("iso20022", "ISO 20022", "bank-messaging", "protocol"),
    Component("open-payments", "Open Payments", "wallet-interoperability", "protocol"),
    Component("rafiki", "Rafiki", "open-payments-runtime", "runtime", health_env="MUSITU_RAFIKI_HEALTH_URL"),
    Component("mpp", "Machine Payments Protocol", "agent-payments", "protocol"),
    Component("x402", "x402", "agent-payments", "protocol"),
    Component("stripe-compat", "Stripe OpenAPI Compatibility", "developer-migration", "protocol"),
    Component("stellar-anchor", "Stellar Anchor Platform", "stablecoin-crossborder", "runtime", health_env="MUSITU_STELLAR_ANCHOR_HEALTH_URL"),
    Component("cctp", "Circle CCTP Adapter", "stablecoin-crossborder", "protocol"),
    Component("mosip", "MOSIP Compatibility", "sovereign-identity", "protocol"),
    Component("offline-value", "MUSITU Offline Value", "offline-payments", "native"),
)


def component_manifest() -> list[dict]:
    result = []
    for c in COMPONENTS:
        item = asdict(c)
        item["configured_health_url"] = os.getenv(c.health_env, "") if c.health_env else ""
        result.append(item)
    return result


async def probe_components(components: Iterable[Component] = COMPONENTS) -> dict:
    ordered = tuple(components)

    async with httpx.AsyncClient(timeout=2.5, follow_redirects=False) as client:
        async def probe(c: Component) -> dict:
            if c.kind in {"protocol", "tooling", "native"}:
                return {"key": c.key, "name": c.name, "required": c.required, "state": "declared", "kind": c.kind}
            url = os.getenv(c.health_env, "") if c.health_env else ""
            if not url:
                return {"key": c.key, "name": c.name, "required": c.required, "state": "unconfigured", "kind": c.kind}
            try:
                response = await client.get(url)
                return {
                    "key": c.key,
                    "name": c.name,
                    "required": c.required,
                    "state": "healthy" if 200 <= response.status_code < 300 else "unhealthy",
                    "status_code": response.status_code,
                    "kind": c.kind,
                }
            except Exception as exc:
                return {
                    "key": c.key,
                    "name": c.name,
                    "required": c.required,
                    "state": "unreachable",
                    "error": type(exc).__name__,
                    "kind": c.kind,
                }

        rows = list(await asyncio.gather(*(probe(c) for c in ordered)))

    runtime_required = [r for r in rows if r["required"] and r["kind"] == "runtime"]
    return {
        "all_required_runtime_healthy": bool(runtime_required) and all(r["state"] == "healthy" for r in runtime_required),
        "components": rows,
    }
