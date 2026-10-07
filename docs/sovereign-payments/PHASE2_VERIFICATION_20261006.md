# MUSITU Sovereign Payments — Phase 2 Verification Evidence

Date: 2026-10-06  
Status: isolated engineering verification; **not production authorization**  
Verified code head: `a4f321c9487396578237e99dc503c223f38dd9ca`  
Branch: `feature/musitu-sovereign-payments-20261006`  
Draft PR: #2  
Base: `musitu-financial-fabric-production-readiness`

## Verified implementation scope

Phase 2 now contains the generic sovereign-scheme controls planned for the isolated branch:

- participant certification lifecycle;
- generic fail-closed switch transfer contract;
- clearing / net-position reference ledger;
- refund, reversal and dispute reference lifecycle;
- country-profile external-dependency evidence gate.

These capabilities remain reference-only and are not production rails.

## Exact execution environment

An ephemeral Vercel sandbox was created under the existing independent-audit-readback project solely for verification.

The sandbox cloned the public repository at exact commit:

`a4f321c9487396578237e99dc503c223f38dd9ca`

The checkout was clean before test setup.

Python `3.13.15` was installed with `uv`, matching one of the repository's evidence-locked production Python versions.

Dependencies were installed from the repository using:

`uv pip install --python .venv/bin/python -c constraints-ci.txt -e '.[dev]'`

The package compatibility check reported:

`All installed packages are compatible`

## TDD evidence

### Clearing reference ledger

The clearing tests were written before implementation.

After implementation and hardening, the exact branch executed:

`python -m py_compile app/db.py app/sovereign.py app/main.py tests/test_sovereign_clearing.py`

and:

`python -m pytest -q tests/test_sovereign_clearing.py`

Result: **4/4 passed, exit 0**.

Verified behavior includes:

- cycle creation and currency validation;
- scheme-profile-scoped cycle references;
- cycle-scoped obligation idempotency;
- PostgreSQL composite advisory-lock contract;
- conflicting replay rejection;
- distinct debtor/creditor requirement;
- zero-sum net positions;
- evidence-bound cycle closure;
- closed-cycle immutability;
- `external_settlement_verified=false`;
- no `payment_intents` or `ledger_postings` created by the reference clearing layer.

### Refund / reversal / dispute lifecycle

The test-only commit `17668d434ab63faf954fb74c14b8c0c91d534e95` was executed before implementation.

Result: **4/4 tests failed as expected**. Three failures were missing scheme-exception APIs; the fourth was the missing PostgreSQL idempotency lock.

After implementation, exact head `33b140ba92aaa1ab3a8b386547b75bd979af03a6` executed the same file.

Result: **4/4 passed, exit 0**.

Verified behavior includes:

- supported kinds: `refund_request`, `reversal_request`, `dispute`;
- create-request idempotency and conflict rejection;
- evidence replay idempotency and conflict rejection;
- terminal-state immutability;
- actor and authorization-decision requirements;
- chained audit records;
- PostgreSQL per-idempotency-key advisory lock;
- no direct payment or ledger movement.

### Country-profile evidence gate

The test-only commit `3fc3c36c85b49b7d8c16cae2247c0811c3c1a728` was executed before implementation.

Result: **4/4 tests failed as expected** because the country-profile gate and PostgreSQL dependency lock did not exist.

After implementation, exact head `a4f321c9487396578237e99dc503c223f38dd9ca` executed the same file.

Result: **4/4 passed, exit 0**.

The `zimbabwe-2026` profile now fails closed on these external dependencies:

- `national_switch_message_interface`;
- `authoritative_mai_allocation`;
- `emvco_conformance`;
- `participant_certification_pack`;
- `settlement_finality_rules`.

Dependency states are limited to:

- `unconfigured`;
- `reference`;
- `externally_verified`.

`externally_verified` requires a non-empty evidence reference, an actor, and an authorization decision ID. Every change is chained-audited.

Even when every external dependency is verified, the country gate returns:

`production_enabled=false`

The country gate cannot self-enable live funds or a sovereign production rail.

## Full regression verification

At exact code head `a4f321c9487396578237e99dc503c223f38dd9ca`:

- total pytest collection: **217 tests**;
- full repository `pytest -q --disable-warnings`: **exit 0**;
- complete `tests/test_sovereign_*.py`: **exit 0**.

This establishes that the isolated Sovereign Payments changes did not break the existing repository test suite under the verified sandbox environment.

## Reproduced software Core Gate

The independent sandbox also executed the software portions of the repository Core Gate:

- `python -m compileall -q app scripts tests`: passed;
- required-component manifest: **39 components**, all required;
- API boot under sandbox mode: passed;
- `GET /health`: returned healthy sandbox response;
- `GET /v1/fabric/components`: returned 39 required components;
- MPP challenge: HTTP **402**;
- x402 challenge: HTTP **402**.

The software-core command completed with:

`SOFTWARE_CORE_GATE_EXIT=0`

## Isolation invariants re-read from GitHub

After implementation:

- PR #2 is still **open, draft, unmerged**;
- base remains `musitu-financial-fabric-production-readiness`;
- `_PRODUCTION_IMPLEMENTED_RAILS = {"ecocash"}`;
- `service.RAILS` contains no `sovereign` rail;
- authoritative Financial Fabric component registry remains **39**;
- Sovereign Payments capabilities remain in a separate reference-only manifest.

Current reference capability keys:

- `sovereign-directory`;
- `sovereign-qr`;
- `request-to-pay`;
- `zimbabwe-qr-profile`;
- `participant-certification`;
- `switch-transfer-contract`;
- `clearing-reference-ledger`;
- `scheme-exceptions`;
- `country-profile-gate`.

All declare `production_enabled=false` and `moves_funds=false`.

## Verification limitations

This evidence does **not** mean the GitHub-hosted Core Gate is green.

GitHub-hosted Actions have separately been failing before runner assignment with zero recorded steps. That external runner issue remains unresolved.

The independent software verification also does not substitute for:

- the Core Gate's Docker-capable-runner check;
- live PostgreSQL/TigerBeetle deployment evidence beyond the repository's tests;
- national-switch UAT;
- participant certification by a real scheme;
- settlement-bank/finality evidence;
- independent security assessment for a target national deployment;
- RBZ approval;
- Zimswitch/National Switch authorization;
- actual MAI allocation;
- EMVCo conformance;
- live-funds authorization.

## Engineering decision

Phase 2's planned **generic reference controls are implemented and independently regression-tested** at the verified code head.

The Zimbabwe integration remains deliberately fail-closed pending authoritative external specifications and evidence.
