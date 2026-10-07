# MUSITU Sovereign Payments — External Evidence Integrity Verification

Date: 2026-10-07
Final implementation head: `87f905ecf8b51dcda28ef95850e7211bec611a5f`
Branch: `feature/musitu-sovereign-payments-20261006`
Status: isolated engineering verification; not production authorization

## Integrity model

Country-profile external evidence now has a dedicated ledger:

`country_profile_evidence_records`

Each record binds:

- country profile;
- exact dependency key;
- evidence reference;
- source authority;
- source version;
- source location/provenance;
- SHA-256 of exact source bytes;
- registering actor;
- verification actor and authorization decision;
- lifecycle state.

Evidence lifecycle:

`registered -> externally_verified -> revoked`

A country dependency can become `externally_verified` only when:

1. the evidence record exists;
2. its profile matches;
3. its dependency matches;
4. its evidence status is `externally_verified`;
5. the dependency evidence reference embeds the exact evidence-record ID and SHA-256.

Free-form `externally_verified` references are rejected by the core setter.

The country-profile gate also fails closed for legacy/free-form external flags: if a live matching evidence record cannot be resolved, the gate treats the dependency as `reference` and keeps it blocked.

## Revocation

Revoking a verified evidence record:

- changes the evidence record to `revoked`;
- chained-audits the action;
- downgrades a dependency previously promoted from that exact record back to `reference`;
- immediately restores the country blocker.

## PostgreSQL concurrency

PostgreSQL evidence operations take transaction-scoped advisory locks on:

- evidence reference during registration;
- evidence record ID during verification/revocation/gate validation.

This preserves the SQLite `BEGIN IMMEDIATE` serialization intent for concurrent evidence lifecycle operations.

## Exact file hashing

`register_country_profile_evidence_file(...)` streams the actual source file bytes and calculates SHA-256 internally.

The caller does not supply the digest for this path.

A sandbox-only CLI is provided:

`scripts/register_sovereign_evidence.py`

The CLI:

- refuses `MUSITU_ENV=production`;
- hashes the evidence file itself;
- registers provenance;
- writes a JSON evidence record;
- does **not** verify or promote the evidence.

Registration alone cannot clear a country blocker.

## TDD evidence

Red states were explicitly demonstrated for:

- missing evidence-ledger module;
- free-form external-verification bypass;
- missing PostgreSQL evidence advisory locks;
- missing exact-file hashing helper;
- missing evidence-registration CLI.

## Independent Python verification

Runtime: Python `3.13.15`.

At final head:

- evidence registration CLI tests: **2 passed**;
- evidence integrity tests: **10 passed**;
- complete Sovereign Payments suite: passed;
- full Financial Fabric repository suite: passed;
- compileall over app/scripts/tests: passed.

## Real PostgreSQL verification

The evidence lifecycle was executed against an ephemeral UTF-8 PostgreSQL instance using the production metadata path.

Observed:

```
POSTGRES_EVIDENCE_TABLE=PASS
POSTGRES_EVIDENCE_PROMOTION=PASS
POSTGRES_EVIDENCE_REVOCATION_REBLOCK=PASS
POSTGRES_AUDIT_CHAIN=PASS
POSTGRES_PAYMENT_INTENTS=0
POSTGRES_LEDGER_POSTINGS=0
```

## Hosted CI

At final head:

- Sovereign Payments workflow #113: success.
- Core Gate #165: pending at the time this receipt was written; do not call it successful until GitHub records conclusion=success.

## Claim boundary

This evidence-integrity work does not establish RBZ approval, Zimswitch authorization, EMVCo certification, MAI allocation, participant certification, settlement finality, production authorization, or live-funds authority.
