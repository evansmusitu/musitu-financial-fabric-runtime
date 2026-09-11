# MUSITU Financial Fabric — Activation Runbook

## 1. Deploy dark first

Deploy the production candidate with:

- `MUSITU_ENV=production`
- `MUSITU_LIVE_FUNDS_ENABLED=false`
- `MUSITU_PRODUCTION_MODE=shadow`
- PostgreSQL configured through `MUSITU_METADATA_DB_URL`
- TigerBeetle configured through `MUSITU_LEDGER_BACKEND=tigerbeetle` and replica addresses
- bearer-token introspection configured against the production identity provider
- OpenFGA/OPA authorization decision gate configured
- Tazama/Watchman risk decision gate configured
- production secrets delivered through the approved secret-management path

Startup must fail if a production-critical software dependency is configured unsafely.

## 2. Prove the dark production deployment

Before any real funds are enabled:

1. verify all mandatory runtime health gates;
2. verify authenticated API access and authorization denial paths;
3. verify PostgreSQL backup/restore and recovery procedures;
4. verify TigerBeetle replica recovery and reconciliation procedures;
5. verify Tazama + Watchman fail-closed behavior;
6. verify audit-chain integrity under concurrency;
7. execute load, soak, failure-injection, and disaster-recovery evidence;
8. complete independent penetration/security review and remediate required findings.

## 3. Acquire external authorization evidence

The actual regulator, sponsor/settlement bank, applicable data-protection authority, and independent-security evidence must be retained outside the source repository. Provider/card/custody approvals are also required where those capabilities are in the approved launch perimeter.

Create the deployed authorization manifest from the repository example only after authentic evidence exists. Compute the exact SHA-256 of that deployed file and configure both:

- `MUSITU_AUTHORIZATION_MANIFEST_PATH`
- `MUSITU_AUTHORIZATION_MANIFEST_SHA256`

Never commit the real authorization package, credentials, or confidential regulatory material to this repository.

## 4. Controlled pilot

Only after the authorization gate reports ready may an approved pilot use:

- `MUSITU_PRODUCTION_MODE=pilot`
- `MUSITU_LIVE_FUNDS_ENABLED=true`

The external manifest must explicitly allow `pilot` or `production` funds scope. Enforce regulator/counterparty transaction, user, corridor, currency, and volume limits outside and inside the payment policy layer as applicable.

## 5. Production promotion

Move to `MUSITU_PRODUCTION_MODE=live` only when the external evidence explicitly covers production operation and all pilot exit criteria are satisfied. Perform canary activation, continuous reconciliation, audit verification, alerting, and rollback drills.

## Emergency stop

The primary application-level stop is `MUSITU_LIVE_FUNDS_ENABLED=false`. Network/provider credentials and settlement access must also have independent operational kill controls. A software flag alone is not a substitute for counterparty and infrastructure controls.

## Never bypass

Do not replace missing evidence with test files, mock responses, developer assertions, CI success, or repository metadata. Missing evidence must keep the funds gate closed.
