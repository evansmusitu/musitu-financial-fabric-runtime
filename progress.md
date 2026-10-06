Plan: docs/plans/2026-10-06-musitu-sovereign-payments-phase1.md
Task 1: implementation complete; participant/alias lifecycle locally verified in isolated harness.
Task 2: implementation complete; QR repository locally verified in isolated harness.
Task 3: implementation complete; request-to-pay and no-fund-movement boundary locally verified in isolated harness.
Task 4: implementation complete; production rail/component-registry isolation confirmed by GitHub source readback and local tests.
Hardening: PostgreSQL request-to-pay idempotency advisory lock, QR nonce uniqueness, and suspended-actor fail-closed behavior added; fresh isolated harness result 13 passed.
CI blocker: GitHub PR runner remains unusable for verification; existing Core Gate and dedicated Sovereign Payments jobs fail, including dependency-free syntax/isolation jobs, while connector log retrieval returns BlobNotFound. Do not treat CI as green.
Zimbabwe 2026 profile: implementation added for external MAI-reference registration, dynamic-only QR policy, future expiry, normalized initiation/tag metadata, API exposure, and explicit non-certification documentation. Production rail and 39-item required-component registry remain unchanged. Verification is pending because GitHub-hosted jobs have been failing before recorded steps; do not treat this profile as green until a runner completes the focused sovereign suite.

Phase 2 Task 1: participant certification lifecycle implemented on isolated branch; focused red observed (2 missing-interface failures), then 2/2 focused green and 10/10 combined independent sovereign-core regression green. Certification approval remains separate from participant activation and moves no funds. Hosted GitHub Actions remains pre-run blocked; full Core Gate is not green.
