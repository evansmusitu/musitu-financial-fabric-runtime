# MUSITU Sovereign Payments — External Outreach Authorization Gate

Date: 2026-10-07  
Status: **NOT AUTHORIZED / NOT SENT**

This gate controls any external representation to RBZ, Zimswitch, a bank, mobile-money operator, PSP, regulator, investor or potential partner regarding MUSITU Sovereign Payments.

## Required owner authorization

No message may be sent until the product owner explicitly authorizes one or more named recipients and the exact message body.

Current status:

- RBZ NPSD outreach: **not authorized**
- RBZ Fintech Sandbox outreach: **not authorized**
- Zimswitch outreach: **not authorized**
- Licensed partner outreach: **not authorized**
- Public announcement / marketing claim: **not authorized**

## Recipient verification before sending

For every message:

1. confirm recipient address from an official public source or direct verified contact;
2. record the official-source URL or provenance;
3. confirm recipient organization and intended role;
4. ensure no secret, credential, token, internal key, customer data or non-public regulated data is included;
5. ensure attachments are intentional and approved.

## Claim-boundary check

Every external message must preserve these facts unless later evidence changes them:

- MUSITU Sovereign Payments is currently an isolated/reference implementation;
- no live customer funds are being moved through the sovereign module;
- no sovereign production rail is enabled;
- RBZ approval is not claimed;
- Zimswitch/National Switch authorization is not claimed;
- EMVCo certification is not claimed;
- actual MAI allocation is not claimed;
- participant certification is not claimed;
- settlement finality is not claimed;
- superiority over NIPL/UPI is not claimed.

## Technical evidence that may be stated accurately

Subject to owner approval, the following engineering facts are supportable by repository evidence:

- independent Python 3.13.15 verification;
- dedicated Sovereign Payments test suite;
- full Financial Fabric regression pass;
- real PostgreSQL reference UAT;
- fail-closed unconfigured switch adapter;
- country-profile evidence gate;
- zero payment intents and zero ledger postings in the reference sovereign UAT;
- hosted Core Gate and Sovereign Payments CI success on verified heads;
- public-reference evidence mapped from official RBZ/Zimswitch material.

Do not convert these engineering facts into regulatory or market claims.

## Attachment candidates

Attach only after explicit approval:

- RBZ/Zimswitch technical evaluation proposal;
- Zimbabwe public evidence matrix;
- Phase 4 conformance verification receipt;
- regulator evaluation-pack JSON generated from a reviewed manifest;
- architecture diagram / sandbox test plan;
- external evidence request checklist.

Do not attach internal secrets, credentials, provider keys, production configuration or unrelated repository material.

## Send decision record

Before sending, record:

- recipient;
- verified address/source;
- exact subject;
- exact body;
- attachment list;
- owner authorization quote/date;
- sender identity;
- intended objective;
- whether follow-up permission is granted.

## Current next action

Await explicit owner authorization to send the prepared RBZ/Zimswitch enquiries.

Until then, continue only with internal hardening, documentation, validation and evidence preparation.
