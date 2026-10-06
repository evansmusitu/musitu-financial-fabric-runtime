# MUSITU Sovereign Payments Phase 1 Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first sovereign-payment scheme primitives to MUSITU Financial Fabric without changing existing production rail authorization or the international multi-rail product boundary.

**Architecture:** Introduce a provider-neutral scheme layer beside the existing merchant/payment-orchestration layer. Phase 1 adds regulated participant identities, payment aliases, a QR repository, and request-to-pay state transitions using the existing database/audit conventions. All new capabilities remain sandbox/reference functionality until separate production authorization and scheme/operator approval exist.

**Tech Stack:** Python 3.12/3.13, FastAPI, SQLite/PostgreSQL dual schema, pytest, existing MUSITU audit and authorization patterns.

## Global Constraints

- Work only on `feature/musitu-sovereign-payments-20261006`, based on exact Financial Fabric head `a80ce52c3b8fcef3e6cece76103417236bcb0c4c`.
- Do not change `main`, `musitu-financial-fabric-production-readiness`, live credentials, live funds, DNS, or provider configuration.
- Do not add a production-enabled sovereign rail in `_PRODUCTION_IMPLEMENTED_RAILS`.
- Preserve Financial Fabric's international multi-rail design; Sovereign Payments is a module/product line, not a Zimbabwe-only fork.
- Reuse the existing chained audit log for every mutable scheme lifecycle event.
- SQLite and PostgreSQL schemas must stay behaviorally aligned.
- All identifiers must be opaque generated identifiers; payment aliases are unique within a scheme and normalized only by trim + lowercase.
- No code may claim EMVCo, RBZ, Zimswitch, UPI/NPCI certification, interoperability approval, or live-settlement finality.
- Every new state-changing public interface must be idempotent where repeated identical requests are plausible and must fail closed on conflicting state.

---

### Task 1: Scheme participant registry and payment aliases

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Create: `musitu_financial_fabric/app/sovereign.py`
- Modify: `musitu_financial_fabric/app/main.py`
- Test: `musitu_financial_fabric/tests/test_sovereign_directory.py`

**Interfaces:**
- Produces `create_scheme_participant(name, participant_type, scheme_code)`
- Produces `set_participant_status(participant_id, target_status, evidence_ref, actor, authorization_decision_id)`
- Produces `register_payment_alias(participant_id, alias, account_ref, alias_type)`
- Produces `resolve_payment_alias(alias)`
- HTTP: `POST /v1/sovereign/participants`, `POST /v1/sovereign/participants/{id}/status`, `POST /v1/sovereign/aliases`, `GET /v1/sovereign/aliases/{alias}`

- [ ] **Step 1: Add the focused failing tests**
  - Creating a participant returns `pending_review` in production and `sandbox` outside production.
  - Duplicate scheme code fails.
  - Alias resolution returns participant/account identity only for an active/sandbox participant; suspended/rejected participants do not resolve.
  - Duplicate normalized alias fails.
  - Production participant activation requires non-empty evidence reference, actor, and authorization decision id.
  - Every create/status/alias event appears in the chained audit log and the chain verifies.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_directory.py`
Expected: non-zero because `app.sovereign` and the scheme tables/interfaces do not exist.

- [ ] **Step 3: Implement the minimum behavior**
  - Add `scheme_participants` and `payment_aliases` to both schemas.
  - Allowed participant types: `bank`, `mobile_money`, `fintech`, `government`, `switch`, `psp`.
  - Allowed status transitions: `pending_review -> active|rejected`, `sandbox -> active|rejected`, `active -> suspended`, `suspended -> active|rejected`.
  - Alias types: `phone`, `email`, `vpa`, `merchant`, `account`.
  - Alias registration requires a participant that exists and is not rejected.
  - Alias resolution must fail closed for inactive participants.

- [ ] **Step 4: Verify the focused pass**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_directory.py`
Expected: all directory tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `cd musitu_financial_fabric && pytest -q tests/test_smoke.py tests/test_merchant_lifecycle.py tests/test_sovereign_directory.py`
Expected: all pass with existing component count unchanged.

- [ ] **Step 6: Commit the passing deliverable**

Commit message: `feat: add sovereign participant and alias directory`

### Task 2: Sovereign QR repository

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Modify: `musitu_financial_fabric/app/main.py`
- Test: `musitu_financial_fabric/tests/test_sovereign_qr.py`

**Interfaces:**
- Produces `create_qr_record(participant_id, merchant_ref, alias, currency, amount_minor=None, expires_at=None)`
- Produces `resolve_qr_record(qr_id, nonce)`
- HTTP: `POST /v1/sovereign/qr`, `GET /v1/sovereign/qr/{qr_id}`

- [ ] **Step 1: Add the focused failing tests**
  - Static QR record can omit amount; dynamic QR requires positive amount and explicit three-letter currency.
  - QR references an existing resolvable alias owned by the same participant.
  - Each QR has a generated nonce; wrong nonce fails.
  - Expired dynamic QR fails resolution.
  - Repeated resolution is read-only; QR repository does not itself execute payment.
  - QR creation is audited.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_qr.py`
Expected: non-zero because QR repository does not exist.

- [ ] **Step 3: Implement the minimum behavior**
  - Add `scheme_qr_records` to SQLite/PostgreSQL schemas.
  - Store an internal normalized MUSITU QR record; do not label it EMVCo-certified.
  - Dynamic records support `amount_minor`, currency, nonce, and expiry; static records contain alias/merchant identity and currency only.
  - Resolution returns normalized payment-initiation data only.

- [ ] **Step 4: Verify the focused pass**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_qr.py`
Expected: all QR tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_directory.py tests/test_sovereign_qr.py tests/test_smoke.py`
Expected: all pass.

- [ ] **Step 6: Commit the passing deliverable**

Commit message: `feat: add sovereign QR repository`

### Task 3: Request-to-pay state machine

**Files:**
- Modify: `musitu_financial_fabric/app/db.py`
- Modify: `musitu_financial_fabric/app/sovereign.py`
- Modify: `musitu_financial_fabric/app/main.py`
- Test: `musitu_financial_fabric/tests/test_sovereign_request_to_pay.py`

**Interfaces:**
- Produces `create_request_to_pay(payee_alias, payer_alias, amount_minor, currency, reference, idempotency_key)`
- Produces `respond_request_to_pay(request_id, decision, actor_alias)`
- HTTP: `POST /v1/sovereign/requests-to-pay`, `POST /v1/sovereign/requests-to-pay/{id}/response`

- [ ] **Step 1: Add the focused failing tests**
  - Both payer and payee aliases must resolve.
  - Amount must be positive and currency explicit.
  - Same idempotency key + identical request returns same request; conflicting body fails.
  - State transitions: `pending -> accepted|declined|cancelled`; terminal states cannot transition.
  - Only payer alias may accept/decline; payee alias may cancel.
  - Acceptance does not move funds or create a provider settlement; it produces an accepted payment instruction for a later orchestration step.
  - Every transition is audited.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_request_to_pay.py`
Expected: non-zero because request-to-pay does not exist.

- [ ] **Step 3: Implement the minimum behavior**
  - Add `request_to_pay` table with request hash/idempotency, aliases, amount/currency, reference and state.
  - Enforce transition ownership and terminal-state immutability.
  - Keep payment execution outside this task.

- [ ] **Step 4: Verify the focused pass**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_request_to_pay.py`
Expected: all request-to-pay tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_directory.py tests/test_sovereign_qr.py tests/test_sovereign_request_to_pay.py tests/test_smoke.py`
Expected: all pass.

- [ ] **Step 6: Commit the passing deliverable**

Commit message: `feat: add sovereign request to pay`

### Task 4: Isolation, capability declaration, and full regression gate

**Files:**
- Modify: `musitu_financial_fabric/app/component_registry.py`
- Test: `musitu_financial_fabric/tests/test_sovereign_isolation.py`
- Create: `docs/sovereign-payments/PHASE1_SCOPE.md`

**Interfaces:**
- Declares `sovereign-directory`, `sovereign-qr`, and `request-to-pay` as native/reference capabilities.
- Does not add `sovereign` to `_PRODUCTION_IMPLEMENTED_RAILS`.
- Does not change existing rail selection defaults.

- [ ] **Step 1: Add the focused failing tests**
  - Existing `RAILS` production behavior remains unchanged.
  - `_PRODUCTION_IMPLEMENTED_RAILS == {"ecocash"}`.
  - Sovereign APIs never invoke `PaymentRail.create_payment` in Phase 1.
  - New capabilities are visible in the component manifest with `kind="native"`.

- [ ] **Step 2: Verify the relevant failure**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_isolation.py`
Expected: non-zero until capability declarations exist.

- [ ] **Step 3: Implement the minimum behavior**
  - Add native capability declarations only.
  - Document that Phase 1 is a scheme/reference layer, not a licensed rail or production switch.
  - Document explicit non-goals: clearing/liquidity finality, participant certification, EMVCo certification, disputes, offline value and production national switch deployment.

- [ ] **Step 4: Verify the focused pass**

Run: `cd musitu_financial_fabric && pytest -q tests/test_sovereign_isolation.py`
Expected: all isolation tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `cd musitu_financial_fabric && pytest -q`
Expected: complete existing and new test suite passes with no regression.

- [ ] **Step 6: Commit the passing deliverable**

Commit message: `feat: declare isolated sovereign payment primitives`

## Unresolved externally observable decisions

- Public naming/branding of the sovereign product is not finalized; code should use neutral `sovereign` identifiers.
- Exact RBZ/Zimswitch participant certification and settlement interfaces require regulator/operator engagement and are outside Phase 1.
- Exact EMVCo QR serialization is not asserted in Phase 1; Phase 1 stores a normalized internal QR record that can later be adapted to an approved national QR profile.
- No fee model, participant pricing, or national scheme transaction limits are encoded in Phase 1.
