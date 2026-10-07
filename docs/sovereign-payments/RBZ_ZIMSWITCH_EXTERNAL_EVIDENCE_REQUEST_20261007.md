# MUSITU Sovereign Payments — Zimbabwe External Evidence Request Package

Date: 2026-10-07  
Status: internal draft; **not sent**  
Purpose: obtain the authoritative operator/regulator material required to turn the Zimbabwe profile from public-reference status into a genuine country adapter.

## Official public contacts

### Reserve Bank of Zimbabwe — National Payment Systems Department

- National Payment Systems Department: `npsd@rbz.co.zw`
- RBZ general communications: `communications@rbz.co.zw`
- Telephone: `+263 242 703000`
- Address: 80 Samora Machel Avenue, Harare, Zimbabwe

The March 2026 NPS circular identifies the Director, Financial Markets Division — National Payment Systems and the same RBZ headquarters contact details.

### Zimswitch Technologies

- General: `info@zimswitch.co.zw`
- Telephone: `+263 867 7010309`
- Address: 3 Mulberry Close, Newlands, Harare, Zimbabwe

Zimswitch's public “Build with us” page explicitly invites developer/fintech collaboration and states that it provides documented APIs for integration with national payment infrastructure.

## Current MUSITU position

MUSITU Financial Fabric has an isolated Sovereign Payments reference implementation covering:

- participant registry and certification lifecycle;
- alias directory;
- request-to-pay;
- QR reference repository;
- Zimbabwe 2026 QR profile;
- generic switch-transfer contract;
- reference clearing/net positions;
- disputes/reversals/refund lifecycle;
- country-profile external evidence gate;
- operator adapter conformance harness;
- regulator evaluation-pack generator;
- PostgreSQL and SQLite reference execution;
- fail-closed production/live-funds controls.

This implementation is **not** represented as RBZ-approved, Zimswitch-authorized, EMVCo-certified, or production connected.

## Authoritative artifacts requested

### 1. National Switch / ZIPIT message interface

Request:

- current participant-facing interface/API/protocol specification;
- supported payment initiation and status/query operations;
- participant/addressing model;
- authentication and authorization profile;
- key-management / certificate requirements;
- idempotency/replay requirements;
- error/status codes and retry semantics;
- reversal/refund/exception mappings;
- test/UAT endpoints and credentials process;
- message versioning and change-management process;
- rate/throughput constraints relevant to certification.

This material is required to clear:

`national_switch_message_interface`

### 2. Merchant Account Information (MAI) allocation

Request:

- current MAI allocation procedure;
- application/registration form;
- responsible Zimswitch/RBZ approval point;
- scheme-specific allocation requirements;
- evidence format proving an assigned MAI ID;
- any namespace/reservation rules.

This material is required to clear:

`authoritative_mai_allocation`

### 3. Zimbabwe QR / EMV conformance

Request:

- authoritative Zimbabwe QR scheme profile implementing the RBZ Annexure;
- permitted/required EMVCo data objects and local extensions;
- validation rules and canonical examples/test vectors;
- static/dynamic QR conformance requirements;
- certification laboratory or operator testing process;
- evidence format produced on successful conformance.

This material is required to clear:

`emvco_conformance`

### 4. Participant certification / UAT pack

Request:

- participant onboarding requirements;
- mandatory certification/UAT test cases;
- security and operational-readiness checks;
- interoperability tests;
- performance/resilience thresholds;
- incident/DR tests;
- evidence required for participant approval;
- certification validity/renewal/change-control rules.

This material is required to clear:

`participant_certification_pack`

### 5. Clearing, settlement and finality rulebook

Request:

- clearing cycle and/or real-time settlement model;
- settlement accounts and sponsor/settlement-bank requirements;
- settlement cutoffs/windows;
- liquidity/limit management;
- finality point and evidence;
- failed/ambiguous transaction treatment;
- reconciliation/reporting artifacts;
- exception/default procedures;
- participant settlement responsibilities.

This material is required to clear:

`settlement_finality_rules`

## Proposed first engagement with Zimswitch

### Subject

Technical evaluation request — MUSITU Sovereign Payments / Financial Fabric integration with Zimbabwe national payments infrastructure

### Draft

Dear Zimswitch Team,

MUSITU is developing an isolated sovereign-payments capability within MUSITU Financial Fabric and would like to evaluate integration with Zimbabwe's existing national payments infrastructure under the appropriate Zimswitch and Reserve Bank framework.

We are not representing our current reference implementation as a live National Switch connection, approved payment scheme, or production payment service. Our immediate objective is a sandbox/UAT technical evaluation.

We have already implemented and independently tested reference capabilities for participant management, payment aliases, request-to-pay, QR payment controls, clearing/net-position logic, disputes, auditability, and a fail-closed country-adapter conformance layer.

To map the implementation to the real Zimswitch environment without inventing proprietary interfaces, we would appreciate guidance on the appropriate developer/fintech onboarding path and access, under any required NDA or participation process, to the applicable:

1. National Switch / ZIPIT participant interface specification;
2. sandbox or UAT integration environment and certification process;
3. MAI allocation process for QR schemes;
4. Zimbabwe QR/EMV conformance material;
5. participant certification/UAT pack; and
6. clearing and settlement operating rules relevant to an integration.

We are open to structuring MUSITU as a technology/integration layer working with the designated National Switch rather than assuming the role of the regulated national operator.

Please advise the correct technical and commercial contact, onboarding process, and any prerequisite documentation or agreements.

Kind regards,

MUSITU

## Proposed parallel engagement with RBZ NPSD

### Subject

Request for regulatory pathway guidance — sovereign instant-payment technology evaluation

### Draft

Dear Director / National Payment Systems Department,

MUSITU is evaluating a sovereign instant-payments technology capability within MUSITU Financial Fabric and seeks guidance on the correct regulatory and operator engagement pathway in Zimbabwe.

Our current implementation is an isolated reference environment only. It is not connected to live customer funds and we do not represent it as an approved payment system, National Switch, QR scheme, or licensed PSP.

We have reviewed the Reserve Bank's March 2026 Guidelines for QR Code Payments in Zimbabwe and have designed the Zimbabwe reference profile to remain fail-closed on all external requirements that can only be satisfied by RBZ or the designated National Switch.

We would appreciate guidance on:

1. whether a technology supplier seeking to provide software/integration capability to the designated National Switch or licensed participants should apply directly to RBZ, engage first through Zimswitch/a licensed PSP, or follow another pathway;
2. the appropriate process for a non-production technical evaluation or sandbox/UAT engagement;
3. the authoritative sources for participant certification, MAI allocation, QR conformance, reporting and settlement/finality requirements; and
4. whether RBZ would be willing to review a technical evaluation pack demonstrating MUSITU's reference architecture and controls without live-funds operation.

Our intention is to work within Zimbabwe's regulatory and National Switch architecture and to avoid duplicating or bypassing roles assigned by the Reserve Bank.

Kind regards,

MUSITU

## Do not send without approval

These drafts are intentionally stored as preparation only. Sending them creates an external representation on behalf of MUSITU and should require explicit authorization from the product owner.

## Evidence intake rule

Any documents received in response must be:

1. retained with source/provenance and version;
2. reviewed against `ZIMBABWE_OPERATOR_ADAPTER_MANIFEST_TEMPLATE.json`;
3. mapped to the five country-profile dependencies;
4. loaded as `externally_verified` only when the document actually resolves that dependency;
5. subjected to the country-adapter conformance tests before any production discussion.
