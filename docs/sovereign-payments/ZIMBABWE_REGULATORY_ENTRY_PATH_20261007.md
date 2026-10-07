# MUSITU Sovereign Payments — Zimbabwe Regulatory Entry Path

Date: 2026-10-07  
Status: internal execution guidance; not legal advice; no application submitted

## Recommended path

### 1. Do not begin by self-classifying MUSITU as a PSO/PSP

The current engineering objective is to offer MUSITU as a technology/integration layer that can work with Zimbabwe's designated National Switch and licensed institutions.

That role may not require MUSITU itself to become the operator of a retail payment system. RBZ should classify the intended role before MUSITU takes on unnecessary licensing obligations.

The first regulatory question should therefore be:

> Is MUSITU being evaluated as a technology supplier/critical service provider to the designated National Switch or licensed participant, as a sandbox fintech participant, or as a prospective payment-system operator/provider?

## 2. Pre-application inquiry to RBZ

Use:

- `fintech@rbz.co.zw` for regulatory sandbox eligibility/process;
- `npsd@rbz.co.zw` for National Payment Systems role/pathway guidance.

Ask RBZ to determine whether the proposed non-production technical evaluation should proceed through:

1. a direct technology-supplier engagement;
2. the Fintech Regulatory Sandbox;
3. a licensed PSP/bank/Zimswitch partnership;
4. a payment-system recognition/approval process; or
5. another path designated by RBZ.

The Sandbox Guidelines expressly say applicants should contact the Sandbox Team before application so the Bank can provide the eligibility checklist.

## 3. Why the sandbox is a credible route

RBZ's published Sandbox eligible-products list includes:

- APIs;
- mobile money services;
- retail payments;
- money transfer services;
- financial-inclusion products;
- cybersecurity products;
- regulatory technology products.

MUSITU Sovereign Payments falls squarely within several of those categories at the reference/UAT level.

However, the Sandbox Guidelines also say the sandbox is not needed where the regulatory status can be determined without live market testing. Therefore MUSITU should **not assume** a sandbox application is required until RBZ confirms it.

## 4. Partnership requirement

RBZ permits entities outside the regulated financial sector to apply, but before live testing such an entity must enter into partnership with a licensed financial-services business in Zimbabwe.

For MUSITU this means the likely live-test topology is:

```
RBZ sandbox / NPSD oversight
        |
licensed Zimbabwe partner
(bank / licensed PSP / other eligible regulated institution)
        |
MUSITU Sovereign Payments reference adapter
        |
authorized Zimswitch / National Switch UAT interface
```

A partnership should be pursued only after RBZ/Zimswitch clarify the permitted test model and integration prerequisites.

## 5. Technical evidence already available

RBZ's Sandbox eligibility criteria require existing solutions to provide technical test results or independent external validation.

MUSITU currently has engineering evidence including:

- independent Python 3.13.15 verification;
- full Financial Fabric regression;
- dedicated hosted Sovereign Payments CI;
- real PostgreSQL 18.6 execution;
- reference end-to-end UAT;
- fail-closed adapter conformance;
- audit-chain proof;
- zero-payment-intent / zero-ledger-posting reference UAT;
- production rail isolation;
- public evidence and external-dependency gating.

These can support a pre-application discussion, but they are not a substitute for independent third-party validation if RBZ requests it.

## 6. Sandbox application evidence required by RBZ

A formal application would need, among other items:

- applicant organization/governance;
- financial standing;
- technical and business expertise;
- regulatory status, if any;
- product/problem statement;
- benefits/business model/use cases;
- end-to-end service illustration;
- technical architecture;
- sandbox test design;
- test targets and KPIs;
- preferred test duration;
- regulated-partner arrangement before testing;
- customer and transaction boundary conditions;
- applicable legal/regulatory requirements;
- requested regulatory relaxations, if any;
- evidence that eligibility criteria are satisfied;
- readiness, safeguards and potential-loss assessment;
- post-sandbox Zimbabwe deployment intention.

## 7. Recommended sequence

### Stage A — now

- Keep Sovereign Payments isolated and non-production.
- Send the technical information request to Zimswitch after owner authorization.
- Send the role/pathway inquiry to RBZ NPSD / Sandbox Team after owner authorization.
- Do not seek live credentials or customer-funds access yet.

### Stage B — after replies

- Load authoritative documents into the country-adapter evidence gate.
- Build the real Zimswitch adapter from supplied specs.
- Obtain actual MAI allocation/process evidence.
- Run operator-provided certification/UAT pack.
- Determine whether RBZ requires sandbox participation.

### Stage C — if sandbox is required

- Select a licensed Zimbabwe partner.
- Prepare Annex 2 eligibility evidence and Annex 4 application pack.
- Define a no/low-risk first test with explicit customer, value, transaction and time limits.
- Submit only after the partner and test model are confirmed.

### Stage D — post-sandbox / production path

- Complete applicable PSP/PSO/technology-outsourcing requirements determined by RBZ.
- Complete Zimswitch participant/operator certification.
- Complete independent security validation and target deployment evidence.
- Only then consider changing any production/live-funds gate.

## 8. Current decision

**Recommended role today:** technology supplier / integration platform under evaluation.

**Sandbox:** plausible and well-aligned, but not yet assumed mandatory.

**Standalone PSO/PSP application now:** not recommended before RBZ role classification.

**Licensed financial-services partner:** required before live sandbox testing if MUSITU is treated as an entity outside the regulated financial sector.

## Official public sources

- RBZ Fintech Regulatory Sandbox FAQ: https://frs.rbz.co.zw/FAQs
- RBZ Fintech Regulatory Sandbox Guidelines: https://www.rbz.co.zw/documents/BLSS/Fintech/FINTECH-REGULATORY-SANDBOX-GUIDELINES.pdf
- RBZ QR Code Payments Guideline, March 2026: https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf
- RBZ NPS Guidelines/Circulars: https://www.rbz.co.zw/index.php/financial-markets/national-payment-system/guidelines-directives-and-circulars
