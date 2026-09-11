# Production Readiness Control Matrix

Authoritative sandbox evidence baseline: `fa2f8967c01e76cb2141475a77678431dc93d4db`.

This matrix separates software-controlled readiness from external authorization. A green software gate never upgrades itself into regulatory or counterparty approval.

## Software-controlled gates

| Control | Required production state |
|---|---|
| Metadata database | PostgreSQL; SQLite is rejected at production startup |
| Monetary truth | TigerBeetle; reference ledger is rejected in production |
| Bounded ledger failure | Production TigerBeetle operations run through a bounded worker; unavailable ledger calls must fail closed within the configured 1–30 second deadline |
| Cross-ledger reconciliation | PostgreSQL monetary metadata must reconcile with TigerBeetle; mismatch, missing accounts, empty-ledger unavailability, and lookup failure close readiness |
| API authentication | Bearer token introspection configured; inactive/malformed tokens, blank required scope, and audience mismatch fail closed |
| API authorization | Decision must allow and evidence both OpenFGA and OPA |
| Fraud/AML screening | Decision must evidence both Tazama and Watchman; unavailable/incomplete response denies |
| Audit chain | PostgreSQL advisory transaction lock serializes chained audit writes |
| Idempotency | Existing payment and mandate reservation controls remain mandatory |
| Request boundary | Production request-body limits must be positive and oversized requests are rejected |
| External rails | Only explicitly enabled, implemented production rails may initiate funds movement; unconfigured bank/card/stablecoin connectors fail closed |
| EcoCash | Production contract must be explicitly confirmed; credentials/endpoints must be supplied; credential-bearing paths remain relative to the pinned provider host |
| Provider settlement | Live-funds authorization gate required before monetary posting |
| Runtime reproducibility | Real PostgreSQL + TigerBeetle production topology accepts only the evidence-qualified CPython/runtime dependency versions; CI locks CPython 3.12.14/3.13.15 and exact package constraints |
| Build chain | OCI/CI build evidence pins `pip==26.2.1`, `setuptools==84.0.0`, and `wheel==0.48.0` |
| OCI candidate | Provider-neutral image uses the pinned Python 3.12.14 base digest, numeric non-root user `65532:65532`, exact dependency constraints, and commit revision labeling |
| Container runtime boundary | CI proves read-only root filesystem, dropped Linux capabilities, `no-new-privileges`, and a deny-by-default Moby seccomp profile extended only for TigerBeetle's three required `io_uring_*` syscalls |
| Resilience evidence | Repository CI proves bounded concurrent load, timed soak, TigerBeetle/PostgreSQL outage fail-closed behavior, PostgreSQL backup/restore, TigerBeetle process recreation, audit-chain validity, and reconciliation |
| Secrets | No production secret belongs in Git; deploy through the secrets control plane |
| Production evidence | Authorization manifest must be external to the repo and SHA-256 pinned |

## Earned repository evidence

The following evidence is software/CI evidence only. It is useful as a prerequisite for deployment review, but it is not a regulator, bank, provider, data-protection, or independent-security approval.

- production resilience evidence: concurrent monetary load, full-duration soak, bounded TigerBeetle failure, PostgreSQL failure/recovery, backup/restore, TigerBeetle recreation, audit integrity, and reconciliation passed on the production-readiness line;
- dependency/build reproducibility: evidence-locked runtime packages and CPython versions passed core, software-control, production-data-plane, and resilience gates; PEP 517 build dependencies are exact-version pinned;
- OCI candidate proof at `3dfc0b759e501ff8deb5c63f3a6d17b5d9024703`: image ID `sha256:56ca1a1e9af75133773857447d2f02f7c19dc4381b9ee39491744c55b1e416d6` ran non-root and read-only, used a deny-by-default custom seccomp profile derived from Moby profiles commit `61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31`, reconciled PostgreSQL with TigerBeetle, and kept live funds closed;
- OCI evidence artifact ID `10272657953` was uploaded by the proof run with archive SHA-256 `aa790196938c9f7b539c06ce7b960791487f8fe917925e05d0f0fc1b07feb636`.

These proofs do **not** establish that the same behavior has been demonstrated on the eventual production infrastructure. The dark deployment must repeat the relevant health, recovery, security, and reconciliation evidence on the actual target environment.

## External evidence gates

The live-funds gate requires independent evidence for all of these categories:

- regulator authorization appropriate to the approved pilot/production scope;
- sponsor/settlement bank approval;
- applicable data-protection authorization/registration;
- independent security assurance;
- approval from each rail/provider included in the launch perimeter.

The evidence manifest must set each required item to `approved`, contain an evidence reference, permit the applicable `pilot` or `production` funds scope, remain unexpired, and match the configured SHA-256 exactly. Runtime rails, currencies, and the single-payment ceiling must remain within the manifest's approved launch scope.

## External dependencies that code must not fabricate

Provider production credentials and signed contracts, bank settlement accounts, card-network/acquirer certification, custody authorization, EcoCash production contract details, regulator decisions, independent penetration-test reports, data-protection decisions, and any other third-party approval remain external evidence.

## Claim boundary

Passing repository production-readiness, resilience, provenance, and OCI-candidate workflows means the **software-controlled safeguards represented by those workflows have been implemented and validated in their tested environments**. It does not mean MUSITU has been authorized to handle real funds, and it does not substitute for a successful dark deployment on the actual production infrastructure. Real funds remain disabled until the external authorization manifest independently proves every required external gate and the target deployment has passed its activation runbook.
