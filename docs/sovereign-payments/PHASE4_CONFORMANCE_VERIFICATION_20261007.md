# MUSITU Sovereign Payments — Phase 4 Conformance Verification

Date: 2026-10-07
Verified code head: `9445f07f92ee0b36adaa4e93f5b4ab17ebcf91a9`
Branch: `feature/musitu-sovereign-payments-20261006`
Draft PR: #2
Status: isolated engineering verification; **not production authorization**

## TDD evidence

### Country-adapter conformance harness

Test-only head:

`8ed9e0ce86b6da9f17415a8329f48b3fe640d6e7`

Focused red result:

`ModuleNotFoundError: No module named 'app.sovereign_conformance'`

Recorded red exit: `2`.

After implementation, focused conformance tests passed **4/4**.

### SQLite/PostgreSQL schema parity defect

Test-only head:

`4460526b791f2fc562ad2ea79ae2c5330f1c1cc6`

The parity test failed as designed and exposed:

- duplicate SQLite Phase 2 declarations;
- missing Phase 2 table declarations in `POSTGRES_SCHEMA`.

The schema was repaired without changing sovereign business logic.

## Verified conformance behavior

MUSITU's generic country adapter contract requires evidence-mapped support for:

- `transfer_submit`;
- `transfer_status`;
- `idempotency`;
- `participant_addressing`;
- `exception_mapping`;
- `settlement_reference`.

These are MUSITU integration requirements, not claims about an official Zimswitch, RBZ or NPCI interface.

The conformance evaluator:

- requires authority, interface-version and source-evidence metadata;
- requires a mapping reference for every behavior claimed supported;
- imports the existing country-profile external-evidence blockers;
- sets `adapter_ready=true` only when the internal manifest is complete and the country external-dependency gate is complete;
- always returns `production_enabled=false`;
- always returns `regulatory_authorized=false`.

The regulator evaluation pack preserves explicit false claim boundaries for RBZ approval, Zimswitch authorization, EMVCo certification, NIPL superiority, National Switch integration and settlement finality.

## Python / SQLite independent regression

Exact supported runtime:

`Python 3.13.15`

At exact head `9445f07f92ee0b36adaa4e93f5b4ab17ebcf91a9`:

- compileall: passed;
- focused schema/conformance/isolation tests: **9 passed**;
- complete `tests/test_sovereign_*.py`: **50 passed**;
- full repository pytest: **exit 0**.

## Real PostgreSQL execution

An ephemeral local PostgreSQL **18.6** cluster was installed in the independent Vercel sandbox and initialized with UTF-8 encoding.

The repaired `POSTGRES_SCHEMA` created all required Phase 2 tables:

- `scheme_certification_cases`;
- `scheme_certification_checks`;
- `scheme_settlement_cycles`;
- `scheme_clearing_obligations`;
- `scheme_exceptions`;
- `scheme_exception_evidence`;
- `country_profile_dependencies`.

The reference UAT then executed against real PostgreSQL.

Observed evidence:

```
POSTGRES_SERVER_ENCODING=UTF8
POSTGRES_TABLES_OK 7
POSTGRES_UAT_AUDIT_EVENTS 20
POSTGRES_CONFORMANCE_BLOCKERS 5
POSTGRES_SOVEREIGN_VERIFY=PASS
```

The PostgreSQL UAT retained:

- valid chained audit;
- zero payment intents;
- zero ledger postings;
- `live_funds_moved=false`;
- `production_authorized=false`.

## GitHub-hosted CI recovery

At the same verified head, GitHub-hosted Actions completed successfully:

- Core Gate run **#124**, run id `37566954037`: **success**;
- Sovereign Payments run **#72**, run id `37566954021`: **success**.

The prior runner-provisioning blocker is therefore no longer active for this commit.

## Isolation invariants

Fresh source readback confirms:

- `_PRODUCTION_IMPLEMENTED_RAILS = {"ecocash"}`;
- no `sovereign` entry exists in `service.RAILS`;
- authoritative Financial Fabric component registry remains **39** items;
- country-adapter conformance is reference-only and moves no funds.

## Claim boundary

This evidence establishes engineering behavior of the isolated reference implementation only.

It does **not** establish:

- RBZ approval;
- Zimswitch/National Switch authorization;
- real National Switch interface compatibility;
- actual MAI allocation;
- EMVCo certification;
- participant certification by a real scheme;
- settlement finality;
- live-funds authority;
- superiority over NIPL/UPI.
