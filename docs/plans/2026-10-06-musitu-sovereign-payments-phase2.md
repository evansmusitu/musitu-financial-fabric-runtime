# MUSITU Sovereign Payments Phase 2 Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the next generic national-scheme control layer—participant certification, clearing/liquidity reference contracts, and disputes/reversals—without inventing Zimbabwe National Switch interfaces or enabling live funds.

**Architecture:** Extend the isolated sovereign module with operator-governed state machines that are independent of any country's proprietary switch API. Country-specific adapters remain separate profiles. Financial movement stays behind the existing Financial Fabric production rail and live-funds gates; Phase 2 records scheme instructions, positions and evidence but does not self-authorize external settlement.

**Tech Stack:** Python, FastAPI, SQLite/PostgreSQL schemas, existing chained audit, pytest, Financial Fabric production evidence controls.

## Global Constraints

- Continue only on `feature/musitu-sovereign-payments-20261006` or a successor isolated sovereign branch explicitly based on it.
- Do not mutate `main` or `musitu-financial-fabric-production-readiness`.
- Do not add a sovereign production rail.
- Do not invent Zimswitch/RBZ endpoints, message fields, MAI allocations, settlement windows, cryptographic profiles or participant identifiers.
- Generic scheme contracts must be clearly labelled reference interfaces.
- Country adapters require authoritative external specifications and separate tests.
- No reference settlement record is evidence that external money moved.
- Every scheme-control mutation must be auditable and fail closed on invalid transitions.
- PostgreSQL concurrency behavior must be explicitly tested for balance/limit/idempotency state that depends on serialization.

---

### Task 1: Participant certification lifecycle

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Modify: `musitu_financial_fabric/app/main.py`
- Create: `musitu_financial_fabric/tests/test_sovereign_certification.py`

**Interfaces:**
- `create_certification_case(participant_id, scheme_profile, evidence_ref)`
- `record_certification_check(case_id, check_key, result, evidence_ref, actor)`
- `decide_certification(case_id, decision, actor, authorization_decision_id)`
- HTTP case/check/decision endpoints.

**Behavior:**
- Participant must exist and cannot be rejected.
- Case states: `open -> approved|rejected`; terminal immutable.
- Approval requires a configured set of mandatory check keys to be passed; the generic set is caller/config supplied and must not be represented as RBZ's official test pack.
- Each check is idempotent by case/check key when payload is identical; conflicting overwrite fails.
- Approval does not automatically activate a participant. Participant status activation remains a separate evidence-bound action.
- Every case/check/decision event is chained-audited.

**Focused tests:**
- missing participant fails;
- duplicate identical check is idempotent;
- conflicting check replay fails;
- approval with missing/failed mandatory checks fails;
- terminal case immutable;
- approval has no payment/settlement side effect.

### Task 2: Generic switch-adapter contract

**Files:**
- Create: `musitu_financial_fabric/app/switch_contracts.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Test: `musitu_financial_fabric/tests/test_sovereign_switch_contract.py`

**Interfaces:**
- `SwitchTransferInstruction`: internal normalized instruction only.
- `SwitchTransferResult`: external-reference/status envelope.
- abstract `SovereignSwitchAdapter.submit_transfer(...)`.
- `UnconfiguredSovereignSwitchAdapter` must always fail closed.

**Behavior:**
- Normalize participant IDs, payer/payee aliases, amount, currency, request/reference IDs.
- No default Zimbabwe endpoint or wire format.
- No adapter is added to production rail routing.
- An accepted request-to-pay may be transformed into a `SwitchTransferInstruction` only; submission remains impossible without an explicitly configured adapter.
- Idempotency key is mandatory in the normalized instruction.

**Focused tests:**
- instruction validates positive amount/3-letter currency;
- unconfigured adapter fails;
- request-to-pay transformation preserves amount/aliases/reference;
- transformation creates no ledger postings/payment intents.

### Task 3: Clearing and liquidity reference ledger

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Create: `musitu_financial_fabric/tests/test_sovereign_clearing.py`

**Interfaces:**
- `open_settlement_cycle(profile_key, cycle_ref, currency)`
- `record_clearing_obligation(cycle_id, debtor_participant_id, creditor_participant_id, amount_minor, external_ref)`
- `calculate_net_positions(cycle_id)`
- `close_settlement_cycle(cycle_id, evidence_ref, actor, authorization_decision_id)`

**Behavior:**
- Reference obligations are not TigerBeetle postings and do not assert external settlement.
- Duplicate external_ref is idempotent only for identical obligation.
- Net positions sum to zero for each currency.
- Cross-currency obligations are rejected within one cycle.
- Closing a cycle requires zero calculation inconsistency and external settlement evidence reference; closure records evidence but does not manufacture finality.
- Closed cycle immutable.
- PostgreSQL must serialize duplicate/idempotency-sensitive obligation insertion.

**Focused tests:**
- balanced net positions;
- duplicate conflict;
- currency mismatch;
- closed-cycle immutability;
- no Financial Fabric ledger balance changes;
- PostgreSQL advisory-lock behavior.

### Task 4: Refund, reversal and dispute state machines

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Create: `musitu_financial_fabric/tests/test_sovereign_disputes.py`

**Interfaces:**
- `create_scheme_exception(transaction_ref, kind, claimant_participant_id, reason, idempotency_key)`
- `record_exception_evidence(exception_id, evidence_ref, actor)`
- `decide_scheme_exception(exception_id, decision, actor, authorization_decision_id)`

**Behavior:**
- Kinds: `refund_request`, `reversal_request`, `dispute`.
- Reference-only states: `open -> accepted|rejected|withdrawn`.
- Decision never directly moves money; later provider/switch adapters execute authorized financial outcomes.
- Duplicate idempotency requests conflict if body differs.
- Terminal immutable.
- Evidence and decision audit required.

### Task 5: Country-profile adapter gate

**Files:**
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Create: `musitu_financial_fabric/tests/test_sovereign_country_adapter_gate.py`
- Update: `docs/sovereign-payments/ZIMBABWE_2026_PROFILE.md`

**Behavior:**
- Country profile declares each external dependency as `unconfigured|reference|externally_verified`.
- Zimbabwe profile must remain non-production while National Switch message interface, actual MAI allocation, EMV conformance and certification pack are unverified.
- No configuration string can upgrade an external dependency to `externally_verified` without an evidence reference bound to the existing production evidence model.
- The gate returns explicit blockers rather than a generic boolean only.

## Promotion criterion

Phase 2 may be called **engineering complete** only when focused tests and the full existing Financial Fabric regression suite execute successfully in a functioning environment.

It may not be called **Zimbabwe integration complete** until authoritative National Switch/RBZ specifications are received and implemented in a separate country adapter.

It may not be called **production ready** until existing Financial Fabric regulator, sponsor-bank, rail-provider, independent-security and target-deployment evidence gates pass for the exact release.

## Externally blocked decisions

- Zimswitch/National Switch API and message contract.
- Actual MAI allocation and Zimbabwe scheme-specific EMV data objects.
- Settlement windows/finality/liquidity rules.
- Official participant certification test pack.
- Refund/reversal/dispute SLAs.
- Scheme transaction limits and fees.
- AML/fraud/reporting integration endpoints.
