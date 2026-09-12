# Target required-runtime health evidence

`musitu_financial_fabric/scripts/collect_runtime_health_evidence.py` is the target-side collector for the `required_runtime_health` row in the production deployment evidence manifest.

It is deliberately narrow. It does **not** create a production authorization, mark the other deployment drills as passed, verify independent kill controls, or enable live funds.

## Preconditions

Run it from the exact deployed MUSITU Financial Fabric release with:

- `MUSITU_TARGET_ENVIRONMENT_ID` set to the independently assigned immutable target identity;
- `MUSITU_BUILD_COMMIT` set to the exact 40-hex running Git commit;
- `MUSITU_RELEASE_IMAGE_DIGEST` set to the exact immutable OCI digest; and
- every required runtime component health environment variable from `app.component_registry.COMPONENTS` configured to a target-local/approved health endpoint.

The collector uses the same `probe_components()` implementation as the runtime component endpoint. It independently verifies that the observed required-runtime inventory exactly matches the registry, contains no duplicates, and that every required runtime row is healthy. A missing, unconfigured, unreachable or unhealthy required runtime makes the collector exit non-zero.

## Run

```bash
cd musitu_financial_fabric
python scripts/collect_runtime_health_evidence.py \
  --output /evidence/runtime-health-evidence.json
```

Identity flags may be passed explicitly, but environment-backed defaults are preferred so the target orchestration layer owns the values.

## Outputs

The collector writes atomically:

- `runtime-health-evidence.json` — target/build-bound observations and the sanitized component results;
- `runtime-health-evidence.json.sha256` — SHA-256 of the exact JSON bytes; and
- `runtime-health-evidence.json.manifest-fragment.json` — the `required_runtime_health` row containing `passed` only when the complete required runtime inventory is healthy and an `evidence_ref` pinned to the JSON SHA-256.

The collector does not include configured health URLs in the evidence artifact, avoiding accidental disclosure of internal endpoint locations or URL credentials.

The generated fragment must be incorporated into the broader deployment evidence process only after the artifact is retained in the target evidence bundle. The broader production manifest still requires dark deployment, monitoring/alerting, PostgreSQL restore, TigerBeetle recovery, provider reconciliation, activation/rollback and independently verified network/provider/settlement kill controls.

## Fail-closed interpretation

Exit code `0` means only that the exact registered required runtime inventory was observed healthy for the bound target/build at the recorded timestamp. Exit code `1` means health evidence failed. Exit code `2` means target/build identity input was missing or malformed.

None of these results create or imply regulator, sponsor-bank, EcoCash/rail-provider, data-protection, independent-security or live-funds authorization.
