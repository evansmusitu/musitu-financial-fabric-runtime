Plan: docs/plans/2026-10-06-musitu-sovereign-payments-phase1.md
Task 1: implementation complete; participant/alias lifecycle locally verified in isolated harness.
Task 2: implementation complete; QR repository locally verified in isolated harness.
Task 3: implementation complete; request-to-pay and no-fund-movement boundary locally verified in isolated harness.
Task 4: implementation complete; production rail/component-registry isolation confirmed by GitHub source readback and local tests.
Hardening: PostgreSQL request-to-pay idempotency advisory lock, QR nonce uniqueness, and suspended-actor fail-closed behavior added; fresh isolated harness result 13 passed.
CI blocker: GitHub PR runner remains unusable for verification; existing Core Gate and dedicated Sovereign Payments jobs fail, including dependency-free syntax/isolation jobs, while connector log retrieval returns BlobNotFound. Do not treat CI as green.
Zimbabwe 2026 profile: implementation added for external MAI-reference registration, dynamic-only QR policy, future expiry, normalized initiation/tag metadata, API exposure, and explicit non-certification documentation. Production rail and 39-item required-component registry remain unchanged. Verification is pending because GitHub-hosted jobs have been failing before recorded steps; do not treat this profile as green until a runner completes the focused sovereign suite.

Phase 2 Task 1: participant certification lifecycle implemented on isolated branch; focused red observed (2 missing-interface failures), then 2/2 focused green and 10/10 combined independent sovereign-core regression green. Certification approval remains separate from participant activation and moves no funds. Hosted GitHub Actions remains pre-run blocked; full Core Gate is not green.

Independent verification: exact commit 945d53df9dc1264e06f2aa0c3285ee1095529a07 cloned into isolated Vercel sandbox; Python 3.13.15 + pinned constraints; sovereign focused suite 26/26 passed; full compile + pytest suite exited 0. Receipt: docs/sovereign-payments/VERIFICATION_20261006.md. GitHub-hosted Actions runner provisioning remains separately blocked.
Phase 2: starting Task 1 participant certification lifecycle by TDD; no production activation.

Phase 3 reference UAT: red proven at 00fc169674ca23d57ad1310a3be3fe430ccb8bbb; implementation verified at 8d0e0b023870111e6ed3d9b8539e9d708cf3df16 under Python 3.13.15. Focused UAT 1/1 passed, sovereign suite 44/44 passed, full repository pytest exited 0. Verification receipt: docs/sovereign-payments/PHASE3_REFERENCE_UAT_VERIFICATION_20261006.md. No production rail activation or live-funds movement.
