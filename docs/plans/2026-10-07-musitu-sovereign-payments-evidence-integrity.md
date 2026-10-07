# MUSITU Sovereign Payments Phase 6 — External Evidence Integrity Plan

Date: 2026-10-07
Branch: `feature/musitu-sovereign-payments-20261006`

**Goal:** Make country-adapter evidence promotion cryptographically bound and provenance-auditable so a free-form evidence reference cannot by itself clear a Zimbabwe production blocker.

## Design

Add an immutable evidence-record layer between external documents and `country_profile_dependencies`.

Each evidence record binds:

- country profile;
- exact dependency key;
- evidence reference;
- issuing/source authority;
- source version;
- source location/provenance;
- SHA-256 of the exact source bytes;
- registering actor;
- verification actor + authorization decision;
- lifecycle status.

Allowed evidence lifecycle:

`registered -> externally_verified -> revoked`

A country dependency may be promoted to `externally_verified` only from an evidence record already in `externally_verified` state and matching the same profile/dependency.

## Fail-closed invariants

- SHA-256 must be exactly 64 hexadecimal characters.
- Evidence reference is unique.
- Duplicate identical registration is idempotent; conflicting reuse fails.
- Verification requires actor and authorization decision.
- Promotion from `registered` or `revoked` evidence fails.
- Evidence for one dependency cannot clear another.
- Direct legacy `set_country_profile_dependency(... externally_verified ...)` remains available for existing tests/internal compatibility but new operator ingestion must use the evidence-bound promotion API; documentation must mark direct promotion as legacy/internal and not operator intake.
- Evidence lifecycle and dependency promotion are chained-audited.
- No production rail or live-funds behavior changes.

## Verification

- focused evidence-integrity tests;
- SQLite/PostgreSQL schema parity;
- all sovereign tests;
- full repository tests;
- real PostgreSQL evidence registration/promotion test;
- hosted Core Gate and Sovereign Payments CI.
