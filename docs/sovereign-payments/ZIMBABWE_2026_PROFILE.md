# MUSITU Sovereign Payments — Zimbabwe 2026 QR Reference Profile

Date: 2026-10-06  
Status: isolated engineering reference profile; **not production enabled and not certified**  
Branch: `feature/musitu-sovereign-payments-20261006`

## Purpose

This profile maps selected requirements from the Reserve Bank of Zimbabwe's March 2026 QR Code Payments Guideline into an isolated MUSITU Sovereign Payments reference implementation.

It exists to test whether MUSITU Financial Fabric can express a Zimbabwe-specific sovereign QR policy without changing the international Financial Fabric architecture or enabling a new production rail.

## Implemented reference behavior

The `zimbabwe-2026` profile currently enforces:

- a registered scheme-profile record before Zimbabwe-profile QR issuance;
- a caller-supplied two-digit Merchant Account Information (MAI) identifier reference;
- uniqueness of MAI identifiers within the profile;
- one profile registration per participant within the profile;
- explicit external allocation reference storage;
- `external_verification=false` because MUSITU does not allocate or validate National Switch MAI identifiers;
- dynamic QR only;
- positive transaction amount;
- explicit three-letter currency;
- one-time generated nonce;
- future expiry;
- Point of Initiation Method reference value `12`;
- normalized `reference_tag_62_05` mapped to the generated nonce;
- channel metadata;
- `serialization_status=normalized_not_emvco_certified`;
- chained audit records for profile registration and QR creation;
- no payment execution, clearing, settlement, or ledger movement as a consequence of QR creation/resolution.

The generic international QR reference behavior remains separate and backward compatible.

## Explicit non-claims

This implementation does **not** claim:

- RBZ approval;
- Zimswitch or National Switch registration;
- allocation of a real MAI identifier;
- EMVCo QR serialization or conformance certification;
- operation of Zimbabwe's National QR Repository;
- bank, mobile-money or PSP participant certification;
- inter-provider routing authorization;
- settlement finality;
- scheme liquidity management;
- consumer dispute adjudication;
- offline/store-and-forward settlement;
- live funds authority.

No Zimbabwe sovereign capability is added to `_PRODUCTION_IMPLEMENTED_RAILS`. The existing Financial Fabric production rail boundary remains EcoCash-only until separately authorized and implemented.

## Relationship to Zimbabwe's National Switch

The intended institutional architecture is operator-neutral:

1. RBZ remains regulator/scheme authority.
2. The designated National Switch remains the authoritative national routing/clearing and QR-repository operator where required by regulation.
3. MUSITU Sovereign Payments may act as a technology layer or participant-facing platform only under an approved operator/regulatory model.
4. MAI allocations, repository synchronization, routing interfaces and settlement messages must come from authoritative National Switch/RBZ specifications; MUSITU must not invent them.

## Open engineering work

Before this profile can progress beyond reference status, MUSITU requires authoritative external inputs for:

- actual MAI allocation ranges and scheme-specific data-object definitions;
- National Switch participant and QR-repository interfaces;
- approved EMVCo/Zimbabwe payload serialization profile and conformance tests;
- merchant/KYC binding rules for QR issuance;
- participant certification test packs;
- clearing and settlement-finality rules;
- liquidity and exception-management procedures;
- refunds, reversals, disputes and consumer-protection workflows;
- transaction limits and fee rules;
- regulatory reporting schemas and delivery channels;
- offline/store-and-forward standards;
- independent security assessment and real-target operational evidence.

## Safety invariant

A successful unit test, CI run, reference QR creation, or normalized tag value is engineering evidence only. It cannot create regulatory approval, National Switch registration, EMVCo certification, provider contracts, settlement authority, or permission to move live funds.


## External dependency evidence gate

The reference implementation now exposes an explicit country-profile dependency gate for `zimbabwe-2026`.

The gate begins fail-closed with these dependencies unconfigured:

- `national_switch_message_interface`
- `authoritative_mai_allocation`
- `emvco_conformance`
- `participant_certification_pack`
- `settlement_finality_rules`

Each dependency can be recorded as `unconfigured`, `reference`, or `externally_verified`. A status of `externally_verified` requires a non-empty external evidence reference, an actor, and an authorization decision ID, and every change is recorded in the chained audit log.

Reference or draft material does not satisfy the gate. The gate reports a blocker for every dependency that is not `externally_verified`.

Even when all external dependencies have evidence, the gate returns `production_enabled=false`. External evidence readiness cannot self-enable a production rail, bypass Financial Fabric's existing live-funds controls, or create RBZ/Zimswitch/EMVCo authorization.
