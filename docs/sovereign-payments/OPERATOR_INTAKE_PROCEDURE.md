# MUSITU Sovereign Payments — Operator Intake Procedure

Date: 2026-10-07
Status: isolated reference workflow; not production authorization

## Purpose

This procedure turns an **authoritative operator-supplied interface specification** into a machine-readable MUSITU conformance/evaluation pack without inventing missing National Switch behavior.

The starting template is:

`docs/sovereign-payments/ZIMBABWE_OPERATOR_ADAPTER_MANIFEST_TEMPLATE.json`

## Rules

1. Do not populate `authority`, `interface_version`, or `source_evidence_ref` from memory or inference.
2. Mark a behavior `supported=true` only when an authoritative external specification demonstrates the mapping.
3. Every supported behavior requires a non-empty `mapping_ref` pointing to the relevant source section/evidence.
4. Do not change an external dependency to `externally_verified` unless the existing country-profile evidence gate has a real evidence reference, actor, and authorization decision.
5. A complete manifest does not itself authorize production.
6. This workflow must not be run with `MUSITU_ENV=production`.

## MUSITU generic adapter behaviors

The internal conformance harness expects evidence mappings for:

- `transfer_submit`
- `transfer_status`
- `idempotency`
- `participant_addressing`
- `exception_mapping`
- `settlement_reference`

These are MUSITU requirements for a country adapter. They are not represented as official RBZ or Zimswitch API names.

## Generate a reference evaluation pack

From the `musitu_financial_fabric` directory:

```bash
export MUSITU_ENV=sandbox
python scripts/generate_sovereign_evaluation_pack.py \
  --profile zimbabwe-2026 \
  --manifest /path/to/operator-manifest.json \
  --output /tmp/zimbabwe-evaluation-pack.json \
  --db-path /tmp/zimbabwe-evaluation-pack.db
```

The command:

- initializes an isolated sandbox metadata database;
- runs the reference sovereign UAT;
- evaluates the supplied adapter manifest;
- carries through the existing country-profile blockers;
- emits a deterministic JSON evaluation pack;
- records `live_funds_moved=false`;
- records `production_authorized=false`.

It refuses the production environment.

## Expected initial Zimbabwe state

Until authoritative external evidence is supplied, the Zimbabwe profile remains blocked on:

- `national_switch_message_interface`;
- `authoritative_mai_allocation`;
- `emvco_conformance`;
- `participant_certification_pack`;
- `settlement_finality_rules`.

## External material to request

For a real operator intake, request at minimum:

- authoritative switch/interface specification;
- version and effective date;
- participant/addressing specification;
- transaction submission and status semantics;
- idempotency/replay requirements;
- reversal/refund/dispute mapping;
- clearing/settlement reference model;
- QR/MAI allocation specification;
- certification/UAT pack;
- security/key-management requirements;
- regulatory reporting requirements.

All source documents should be retained with provenance and version information.

## Promotion boundary

An operator manifest can become `adapter_ready=true` only when:

- all MUSITU generic adapter behavior mappings are evidenced; and
- all country-profile external dependencies are marked externally verified through the evidence gate.

Even then this layer still returns:

- `production_enabled=false`;
- `regulatory_authorized=false`.

Production remains governed by the separate Financial Fabric live-funds and production-authorization controls.


## Hash-bound evidence ingestion

When an authoritative operator document is received, do not manually type a digest into the dependency gate.

Register the exact file bytes first:

```bash
export MUSITU_ENV=sandbox
python scripts/register_sovereign_evidence.py \
  --profile zimbabwe-2026 \
  --dependency national_switch_message_interface \
  --file /secure/path/operator-spec.pdf \
  --evidence-ref operator:zimswitch:spec-v1 \
  --authority "Zimswitch Technologies" \
  --version "v1" \
  --source-location "secure-evidence-room/operator-spec-v1.pdf" \
  --actor evidence-intake \
  --db-path /secure/path/evidence-ledger.db \
  --output /secure/path/evidence-record.json
```

This performs **registration only**.

Required promotion sequence is:

1. register exact file bytes;
2. independently review the document;
3. verify the evidence record with an explicit authorization decision;
4. promote only the matching country dependency from that verified record;
5. run the country-adapter conformance suite again.

Free-form `externally_verified` references are rejected by the core country-profile gate.

If a verified evidence record is later revoked or superseded, any dependency promoted from that exact record is re-blocked automatically.
