# Production Readiness Control Matrix

Authoritative sandbox evidence baseline: `fa2f8967c01e76cb2141475a77678431dc93d4db`.

This matrix separates software-controlled readiness from external authorization. A green software gate never upgrades itself into regulatory or counterparty approval.

## Software-controlled gates

| Control | Required production state |
|---|---|
| Metadata database | PostgreSQL; SQLite is rejected at production startup |
| Monetary truth | TigerBeetle; reference ledger is rejected in production |
| API authentication | Bearer token introspection configured; inactive/malformed tokens fail closed |
| API authorization | Decision must allow and evidence both OpenFGA and OPA |
| Fraud/AML screening | Decision must evidence both Tazama and Watchman; unavailable/incomplete response denies |
| Audit chain | PostgreSQL advisory transaction lock serializes chained audit writes |
| Idempotency | Existing payment and mandate reservation controls remain mandatory |
| External rails | Unconfigured bank/card/stablecoin connectors fail closed |
| EcoCash | Production contract must be explicitly confirmed and exact credentials/endpoints supplied |
| Provider settlement | Live-funds authorization gate required before monetary posting |
| Secrets | No production secret belongs in Git; deploy through the secrets control plane |
| Production evidence | Authorization manifest must be external to the repo and SHA-256 pinned |

## External evidence gates

The live-funds gate requires independent evidence for all of these categories:

- regulator authorization appropriate to the approved pilot/production scope;
- sponsor/settlement bank approval;
- applicable data-protection authorization/registration;
- independent security assurance.

The evidence manifest must set each item to `approved`, contain an evidence reference, permit `pilot` or `production` funds scope, and match the configured SHA-256 exactly.

## External dependencies that code must not fabricate

Provider production credentials and signed contracts, bank settlement accounts, card-network/acquirer certification, custody authorization, EcoCash production contract details, regulator decisions, independent penetration-test reports, and any other third-party approval remain external evidence.

## Claim boundary

Passing this production-readiness workflow means the **software-controlled production safeguards have been implemented and validated**. It does not mean MUSITU has been authorized to handle real funds. Real funds remain disabled until the external authorization manifest independently proves every required external gate.
