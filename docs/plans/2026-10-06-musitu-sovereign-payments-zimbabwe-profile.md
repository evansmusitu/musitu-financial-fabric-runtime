# MUSITU Sovereign Payments Zimbabwe 2026 Profile Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed Zimbabwe 2026 QR reference profile to MUSITU Sovereign Payments while preserving the generic international scheme layer and making no certification or production claims.

**Architecture:** Keep Phase 1 generic QR behavior unchanged. Add a separate scheme-profile registry that records a caller-supplied National-Switch MAI allocation reference, then require Zimbabwe-profile QR records to be dynamic-only with amount, unique nonce, future expiry, Point-of-Initiation Method 12, and Tag 62-05 reference metadata. The profile produces normalized reference data only; EMVCo serialization and National Switch connectivity remain outside this phase.

**Tech Stack:** Python, FastAPI, SQLite/PostgreSQL schemas, existing MUSITU chained audit, pytest.

## Global Constraints

- Work only on `feature/musitu-sovereign-payments-20261006`.
- Do not add a production rail or modify live-funds authorization.
- Preserve generic/international QR behavior for other countries.
- Do not invent or auto-allocate Zimbabwe MAI IDs; they are supplied as externally allocated references and remain unverified until external evidence exists.
- Do not claim EMVCo certification, RBZ approval, Zimswitch/National Switch registration, or production interoperability.
- Zimbabwe static QR issuance remains disabled in this phase.
- Zimbabwe offline/store-and-forward execution remains disabled in this phase.
- A Zimbabwe dynamic QR must include amount, one-time nonce, future expiry, Point-of-Initiation Method `12`, and reference metadata corresponding to Tag `62-05`.

---

### Task 1: Zimbabwe scheme-profile/MAI reference registry

**Files:** modify `app/db.py`, `app/sovereign.py`, `app/main.py`; create `tests/test_sovereign_zimbabwe_profile.py`.

**Interfaces:** `register_qr_scheme_profile(participant_id, profile_key, mai_id, allocation_ref)`; `POST /v1/sovereign/qr-scheme-profiles`.

- [ ] Add red tests for two-digit numeric MAI format, unique MAI per profile, resolvable scheme participant, and chained audit.
- [ ] Add `qr_scheme_profiles` to SQLite/PostgreSQL with unique `(profile_key, mai_id)` and unique `(profile_key, participant_id)`.
- [ ] Store `allocation_ref` as a reference only; response explicitly reports `external_verification=false`.
- [ ] Verify focused tests.

### Task 2: Dynamic-only Zimbabwe QR policy

**Files:** modify `app/db.py`, `app/sovereign.py`, `app/main.py`; extend `tests/test_sovereign_zimbabwe_profile.py`.

**Interfaces:** extend `create_qr_record(..., profile_key="generic", scheme_profile_id=None, channel="pos")`.

- [ ] Add red tests: Zimbabwe profile rejects missing amount, missing expiry, expired/non-future expiry, missing scheme profile, and static issuance.
- [ ] Persist `profile_key`, `scheme_profile_id`, `channel`, `point_of_initiation_method`, and `reference_tag_62_05`.
- [ ] For `zimbabwe-2026`: require dynamic amount, future expiry and registered profile; set `point_of_initiation_method="12"` and `reference_tag_62_05=nonce`.
- [ ] Return `serialization_status="normalized_not_emvco_certified"`.
- [ ] Preserve existing generic QR tests.

### Task 3: Explicit non-claims and isolation regression

**Files:** modify `app/sovereign.py`; extend `tests/test_sovereign_isolation.py`; create `docs/sovereign-payments/ZIMBABWE_2026_PROFILE.md`.

- [ ] Add `zimbabwe-qr-profile` to separate sovereign capability manifest only, with `production_enabled=false` and `moves_funds=false`.
- [ ] Assert 39-item Financial Fabric required-component registry and EcoCash-only production rail set remain unchanged.
- [ ] Document open external dependencies: MAI allocation, scheme rules, participant certification, National Switch adapter, settlement/finality/liquidity, disputes, regulatory approval, EMV conformance.
- [ ] Run focused local suite and record GitHub PR-runner blocker separately.

## Unresolved externally observable decisions

- Exact MAI ID and scheme-specific data-object allocation require National Switch/RBZ coordination.
- Exact National Switch API/message interface is not public in the reviewed RBZ guideline and must not be invented.
- EMVCo payload serialization/conformance testing requires the finalized Zimbabwe scheme data profile and allocated MAI.
- Static QR, offline payment execution, fee rules, settlement windows and national dispute SLAs remain outside this phase.
