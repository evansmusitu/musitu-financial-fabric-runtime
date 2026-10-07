# MUSITU Sovereign Payments Phase 4 — Country Adapter Conformance Plan

Date: 2026-10-07
Branch: `feature/musitu-sovereign-payments-20261006`

**Goal:** Add a regulator/operator-facing conformance harness that can ingest authoritative country-adapter evidence without inventing National Switch interfaces, and produce a fail-closed evaluation pack.

## Constraints

- No Zimswitch, RBZ, NPCI, EMVCo or other external interface may be invented or represented as authoritative.
- The harness validates MUSITU's own generic adapter requirements only.
- Country-specific evidence must be supplied by an external authority/operator and referenced explicitly.
- A structurally complete adapter never self-authorizes production.
- `production_enabled` and `regulatory_authorized` remain false in this layer.
- No live funds, payment intents, ledger postings or external network calls are permitted.

## MUSITU generic adapter behaviors

The initial internal conformance contract requires evidence-mapped support for:

1. `transfer_submit`
2. `transfer_status`
3. `idempotency`
4. `participant_addressing`
5. `exception_mapping`
6. `settlement_reference`

These are MUSITU integration requirements, **not claims about Zimbabwe's official switch API**.

## Task 1: Manifest evaluator

Create `app/sovereign_conformance.py`.

Interface:

`evaluate_country_adapter_manifest(profile_key, manifest)`

Required manifest metadata:

- `authority`
- `interface_version`
- `source_evidence_ref`
- `behaviors`

Each supported behavior must include a non-empty `mapping_ref`.

Result must include:

- structural validity;
- missing/invalid behaviors;
- external country-profile blockers from the existing evidence gate;
- `adapter_ready` only when both the internal manifest and external dependency gate are complete;
- `production_enabled=false`;
- `regulatory_authorized=false`.

## Task 2: Evaluation pack builder

Interface:

`build_regulator_evaluation_pack(profile_key, manifest, uat_result)`

The returned JSON-serializable pack must include:

- country/profile identity;
- generic adapter conformance;
- reference UAT evidence summary;
- sovereign capability keys;
- country blockers;
- explicit claim boundaries;
- `live_funds_moved=false`;
- `production_authorized=false`.

## Task 3: Schema hygiene

Remove duplicate Phase 2 SQLite `CREATE TABLE IF NOT EXISTS` statements without changing the resulting schema.

## Verification gate

Before calling Phase 4 engineering-complete:

- prove focused red before implementation;
- focused conformance tests pass;
- all `test_sovereign_*.py` pass;
- full repository pytest passes on Python 3.13.15;
- direct source readback confirms EcoCash-only production rail, no sovereign route, and 39 authoritative Financial Fabric components.
