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

Create the deployed authorization manifest from the repository example only after authentic evidence exists. Retain the actual regulator/bank/data-protection/security/rail approval artifacts as a dedicated evidence bundle outside the source repository, mount that exact bundle read-only where the production gate can read it, compute its SHA-256, and record both path and digest under `evidence_bundle`. Missing, unreadable, or modified authorization evidence must keep the funds gate closed.

Compute the exact SHA-256 of the deployed authorization manifest and configure both:

- `MUSITU_AUTHORIZATION_MANIFEST_PATH`
- `MUSITU_AUTHORIZATION_MANIFEST_SHA256`

Never commit the real authorization package, credentials, or confidential regulatory material to this repository.

## 4. Bind executed target-deployment evidence

After the real target environment has been deployed dark and the required drills have actually passed, create a deployment-evidence manifest from `control/musitu-financial-fabric/production-deployment-evidence-manifest.example.json`. Do **not** mark a control passed merely because CI, documentation, or an application flag exists.

Retain the actual target-environment drill/control artifacts as a dedicated evidence bundle outside the source repository. Mount that exact bundle read-only where the production gate can read it, compute its SHA-256, and record both its mounted path and digest under `evidence_bundle` in the deployment-evidence manifest. Any missing bundle, unreadable bundle, or byte mismatch must keep the live-funds gate closed.

The retained target manifest must bind all of the following:

- the exact immutable production target identity configured independently as `MUSITU_TARGET_ENVIRONMENT_ID`;
- the exact runtime commit embedded in the image as `MUSITU_BUILD_COMMIT`;
- the immutable digest of the image actually running in the target environment, configured as `MUSITU_RELEASE_IMAGE_DIGEST`;
- a distinct immutable rollback image digest;
- the exact SHA-256 of the external authorization manifest;
- the mounted target-evidence bundle and its exact SHA-256;
- executed dark-deployment, monitoring/alerting, PostgreSQL backup/restore, TigerBeetle recovery, provider reconciliation, and activation/rollback evidence references;
- network, provider, and settlement kill-control evidence that is genuinely independent of the application.

Compute the exact SHA-256 of the retained deployment-evidence file and configure both:

- `MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_PATH`
- `MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256`
- `MUSITU_TARGET_ENVIRONMENT_ID`

The deployment-evidence manifest and evidence-bundle hashes are integrity bindings only. They do not create regulator approval, provider authorization, independent security certification, data-protection authorization, card/network/custody approval, or independent kill controls. Keep authentic evidence outside the source repository under the appropriate operational controls.

## 5. Controlled pilot

Only after **both** the external-authorization and target-deployment gates report ready may an approved pilot use:

- `MUSITU_PRODUCTION_MODE=pilot`
- `MUSITU_LIVE_FUNDS_ENABLED=true`

The external manifest must explicitly allow `pilot` or `production` funds scope. Enforce regulator/counterparty transaction, user, corridor, currency, and volume limits outside and inside the payment policy layer as applicable.

## 6. Production promotion

Move to `MUSITU_PRODUCTION_MODE=live` only when the external evidence explicitly covers production operation, the pinned target-deployment evidence and byte-pinned target-evidence bundle are current for the exact running release, and all pilot exit criteria are satisfied. Perform canary activation, continuous reconciliation, audit verification, alerting, and rollback drills.

## Emergency stop

The primary application-level stop is `MUSITU_LIVE_FUNDS_ENABLED=false`. Network/provider credentials and settlement access must also have independent operational kill controls. A software flag alone is not a substitute for counterparty and infrastructure controls.

## Never bypass

Do not replace missing evidence with test files, mock responses, developer assertions, CI success, or repository metadata. Missing evidence must keep the funds gate closed.
