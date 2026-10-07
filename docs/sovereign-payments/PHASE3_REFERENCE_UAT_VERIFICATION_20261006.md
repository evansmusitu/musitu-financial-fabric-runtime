# MUSITU Sovereign Payments — Phase 3 Reference UAT Verification

Date: 2026-10-06
Verified commit: `8d0e0b023870111e6ed3d9b8539e9d708cf3df16`
Branch: `feature/musitu-sovereign-payments-20261006`
Status: isolated engineering verification; not production authorization

## TDD record

Red test-only head:

`00fc169674ca23d57ad1310a3be3fe430ccb8bbb`

Focused result:

`ModuleNotFoundError: No module named 'app.sovereign_uat'`

Recorded red exit: `2`.

Implementation head:

`8d0e0b023870111e6ed3d9b8539e9d708cf3df16`

## Verified environment

- independent Vercel universal sandbox;
- region: `cpt1`;
- exact Python runtime: `3.13.15`;
- dependencies installed from `constraints-ci.txt`;
- exact Git checkout matched the verified commit.

## Focused UAT verification

Command:

```bash
python -m pytest -q tests/test_sovereign_reference_uat.py
```

Result:

```
. [100%]
```

Exit code: `0`.

## Sovereign regression

Command:

```bash
python -m pytest -q tests/test_sovereign_*.py
```

Result: **44 sovereign tests passed**, exit `0`.

## Full Financial Fabric regression

Command:

```bash
python -m compileall -q app tests
python -m pytest -q
```

Result: full suite completed at 100%, exit `0`.

## Reference UAT behavior proven

The compositional UAT exercises:

- two scheme participants;
- reference participant certification;
- payment aliases;
- request-to-pay creation and acceptance;
- normalized sovereign switch instruction;
- fail-closed unconfigured switch submission;
- reference clearing obligation and zero-sum net positions;
- reference settlement-cycle closure with `external_settlement_verified=false`;
- synthetic dispute lifecycle;
- Zimbabwe country-profile gate remaining non-production and externally blocked;
- valid chained audit;
- zero `payment_intents`;
- zero `ledger_postings`;
- explicit `live_funds_moved=false`;
- explicit `production_authorized=false`.

## Claim boundary

This verification does not establish RBZ approval, Zimswitch/National Switch integration, EMVCo conformance, participant certification by a real scheme, settlement finality, live-funds authorization, or superiority over NIPL/UPI.

GitHub-hosted Actions remain a separate runner-provisioning issue and are not claimed green.
