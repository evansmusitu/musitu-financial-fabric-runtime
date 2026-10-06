# MUSITU Sovereign Payments Phase 3 — Reference UAT Plan

Date: 2026-10-06
Branch: `feature/musitu-sovereign-payments-20261006`

**Goal:** Prove that the independently verified sovereign primitives compose into one deterministic, auditable, no-live-funds reference scenario suitable for regulator/operator technical evaluation.

## Constraints

- No production rail activation.
- No real Zimswitch/RBZ/NPCI endpoint or message format may be invented.
- No external settlement is claimed.
- No EMVCo certification is claimed.
- No payment intent or ledger posting may be created by the UAT scenario.
- The existing international Financial Fabric routing architecture remains unchanged.
- The Zimbabwe country gate must remain blocked unless all external dependencies are independently evidenced.

## Task 1: End-to-end reference UAT

Create `app/sovereign_uat.py` and `tests/test_sovereign_reference_uat.py`.

Scenario:

1. Create payer bank and merchant PSP scheme participants.
2. Open and approve generic certification cases using reference checks.
3. Confirm certification approval does not activate participants or move funds.
4. Register payer and merchant aliases.
5. Create and accept a request-to-pay.
6. Transform the accepted request into a normalized `SwitchTransferInstruction`.
7. Confirm the unconfigured sovereign switch adapter fails closed.
8. Open a reference settlement cycle and record a clearing obligation.
9. Calculate zero-sum net positions.
10. Close the reference cycle using an explicit reference evidence string while preserving `external_settlement_verified=false`.
11. Create and decide a synthetic dispute reference.
12. Read the Zimbabwe country gate and confirm it remains non-production.
13. Verify chained audit integrity.
14. Verify `payment_intents == 0` and `ledger_postings == 0`.

The UAT result must return a structured evidence summary, not a production success claim.

## Task 2: Evaluation evidence export

Create a deterministic JSON-serializable result schema from the UAT, including:

- participant IDs and certification state;
- accepted request-to-pay ID;
- normalized switch instruction;
- fail-closed switch submission result;
- clearing cycle ID and net positions;
- dispute case and disposition;
- country-profile blockers;
- audit-chain validity;
- payment/ledger side-effect counts;
- explicit `live_funds_moved=false`;
- explicit `production_authorized=false`.

## Promotion gate

Phase 3 Task 1 is complete only after:

- focused UAT test passes at exact branch head;
- all `test_sovereign_*.py` pass;
- full repository `pytest -q` passes;
- direct source readback confirms EcoCash-only production rail and no sovereign production route.
