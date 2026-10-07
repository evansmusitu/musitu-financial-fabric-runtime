# Zimbabwe Sovereign Payments — Public Evidence Matrix

Date: 2026-10-07  
Status: public-reference evidence only; no external dependency is treated as verified

## Decision rule

Public RBZ/Zimswitch material can establish **requirements, roles and reference architecture**. It cannot substitute for an operator-issued interface contract, an actual MAI allocation, a certification result, or an operative settlement-finality rulebook.

Accordingly, every dependency below is stored as `reference`, not `externally_verified`.

| Dependency | Public evidence | What it proves | Why it remains blocked |
|---|---|---|---|
| `national_switch_message_interface` | RBZ QR Guideline §§7.2–7.3, 17, 21.6; Zimswitch “Build with us” and clearing/settlement pages | Inter-provider routing/clearing defaults to the National Switch; the National Switch hosts the National QR Repository; Zimswitch publicly offers APIs and is Zimbabwe's national switch/clearing house | No public National Switch wire protocol, endpoint contract, authentication profile, message schema, or certification fixtures for ZIPIT/national-switch integration |
| `authoritative_mai_allocation` | RBZ QR Guideline §9.1(a),(c),(e) | MAI IDs must be coordinated with/issued through the National Switch and the first two digits identify scheme allocation | MUSITU has not been issued an actual MAI ID and no authoritative allocation record exists for MUSITU |
| `emvco_conformance` | RBZ QR Guideline §§20.1–20.6, 21.7–21.8 and Annexure 1 | Zimbabwe adopts EMVCo merchant-presented QR requirements; dynamic QR uses amount, nonce, expiry; Tag 01 11/12 and Tag 62-05 are specified | Regulatory adoption of EMVCo does not prove MUSITU implementation conformance or certification |
| `participant_certification_pack` | RBZ QR Guideline §§6.2, 8.1, 9.1(b)–(f), 18 | Approval, scheme-rule, participant responsibility, reporting and oversight requirements are public | The actual National Switch participant certification/UAT pack is not published in the material reviewed |
| `settlement_finality_rules` | RBZ QR Guideline §7.3(a), §9.6; Zimswitch Clearing and Settlement Services | RBZ requires equivalent/strong settlement finality and operating rules covering settlement; Zimswitch publicly states it provides real-time clearing and settlement | Public sources do not disclose the operative rulebook, settlement windows, liquidity model, exception handling, or evidence needed to assert finality |

## Public Zimswitch developer material reviewed

Zimswitch publicly states that it provides secure, documented APIs to developers and fintechs. Its linked public developer portal exposes Zimswitch Online / ConnectUP style e-commerce and card-payment APIs, including payment initiation, status, refunds/back-office operations, authentication, tokenization and related services.

That material is useful evidence that Zimswitch supports API-based integrations, but it is **not treated as the authoritative ZIPIT/National Switch instant-payment message interface**.

## Official sources

- RBZ Guidelines for Quick Response (QR) Code Payments in Zimbabwe, March 2026  
  https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf
- RBZ National Payment Systems Guidelines / Circulars index  
  https://www.rbz.co.zw/index.php/financial-markets/national-payment-system/guidelines-directives-and-circulars
- Zimswitch Build with us  
  https://zimswitch.co.zw/build-with-us/
- Zimswitch Clearing and Settlement Services  
  https://zimswitch.co.zw/clearing-and-settlement-services/
- Zimswitch ZIPIT  
  https://zimswitch.co.zw/solutions/zipit/
- Zimswitch Online  
  https://zimswitch.co.zw/zimswitch-online/
- Zimswitch public developer portal  
  https://zimswitch.docs.oppwa.com/integrations/widget

## Promotion boundary

A dependency may be changed from `reference` to `externally_verified` only when the relevant authority/operator evidence is obtained and bound through the existing country-profile evidence gate with:

- evidence reference;
- actor;
- authorization decision ID.

Public web material alone does not satisfy that promotion.
