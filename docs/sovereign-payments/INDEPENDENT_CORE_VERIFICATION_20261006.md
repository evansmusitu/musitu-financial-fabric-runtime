# MUSITU Sovereign Payments — Independent Core Verification 2026-10-06

Status: independent execution evidence; not a replacement for the full Financial Fabric Core Gate  
Branch: `feature/musitu-sovereign-payments-20261006`

## Scope verified

An independent local execution harness was reconstructed from GitHub source for the sovereign core because GitHub-hosted Actions were failing before runner assignment.

Verified GitHub state before evidence capture:

- draft PR #2 remains open, draft and unmerged;
- PR base remains `musitu-financial-fabric-production-readiness`;
- production rail allow-list remains exactly `{"ecocash"}`;
- `service.RAILS` contains no `sovereign` rail;
- authoritative Financial Fabric component registry remains 39 items;
- sovereign module blob after participant-certification addition: `1991ea4dcb66098f774969fed8d52efabdebe0cd`;
- database module blob after certification schema addition: `b2d46daecbf16cd3254a950f9e91517e38571e5a`.

## Red/green record

Phase 2 Task 1 began with a focused participant-certification test.

Initial result:

- 2 tests failed;
- both failures were `AttributeError` because `create_certification_case` did not yet exist.

After the minimum certification implementation:

- focused certification tests: **2 passed**;
- combined independent sovereign core + certification tests: **10 passed**.

The independent pack covers:

1. participant creation and payment-alias normalization/resolution;
2. duplicate scheme-code and alias fail-closed behavior;
3. production participant activation evidence/actor/authorization requirements;
4. participant suspension and fail-closed alias resolution;
5. generic static/dynamic QR behavior and nonce handling;
6. Zimbabwe 2026 dynamic QR profile constraints and normalized profile metadata;
7. request-to-pay idempotency, conflict detection, actor ownership and terminal states;
8. suspended payer fail-closed behavior;
9. PostgreSQL request-to-pay advisory-lock contract;
10. reference-only capability declarations;
11. participant certification mandatory-check enforcement;
12. certification check idempotency/conflict behavior;
13. certification terminal immutability;
14. certification approval does not activate the participant;
15. QR/request-to-pay/certification paths create no payment intents or fund movement;
16. chained audit verification.

## Provenance

The locally executed `app/sovereign.py` is byte-identical to GitHub blob:

`1991ea4dcb66098f774969fed8d52efabdebe0cd`.

The config and audit modules were also reconstructed from GitHub source. The local database module was reconstructed from the current GitHub schema/wrapper source and exercised the same SQLite tables and PostgreSQL advisory-lock behavior, but its local Git blob hash was not byte-identical because of transport reconstruction differences. Therefore this evidence is intentionally described as **independent sovereign-core execution**, not an exact full-repository checkout.

The new certification HTTP surface was source-read back from GitHub after write and inspected for authorization separation, but the complete FastAPI application has not yet executed in this local harness.

## Hosted CI blocker

GitHub-hosted jobs remain externally blocked before any job step starts. Prior diagnostic runs showed:

- `runner_id: 0`;
- empty runner name;
- `steps: []`;
- failures before checkout;
- same behavior on Ubuntu 24.04 and Ubuntu 22.04 fallback jobs;
- log-download attempts returning `BlobNotFound`.

Until that is resolved, do not call the full Core Gate green.

## Claim boundary

This evidence supports continuing isolated engineering. It does not establish:

- RBZ approval;
- Zimswitch/National Switch registration;
- EMVCo certification;
- actual MAI allocation;
- national clearing/settlement finality;
- participant certification by a real scheme;
- production readiness;
- superiority over NIPL/UPI.
