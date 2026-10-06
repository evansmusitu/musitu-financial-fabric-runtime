Plan: docs/plans/2026-10-06-musitu-sovereign-payments-phase1.md
Task 1: implementation complete; participant/alias lifecycle locally verified in isolated harness.
Task 2: implementation complete; QR repository locally verified in isolated harness.
Task 3: implementation complete; request-to-pay and no-fund-movement boundary locally verified in isolated harness.
Task 4: implementation complete; production rail/component-registry isolation confirmed by GitHub source readback and local tests.
Hardening: PostgreSQL request-to-pay idempotency advisory lock, QR nonce uniqueness, and suspended-actor fail-closed behavior added; fresh isolated harness result 13 passed.
CI blocker: GitHub PR runner remains unusable for verification; existing Core Gate and dedicated Sovereign Payments jobs fail, including dependency-free syntax/isolation jobs, while connector log retrieval returns BlobNotFound. Do not treat CI as green.
Next: Zimbabwe 2026 sovereign QR profile grounded in RBZ March 2026 requirements; no production activation.
