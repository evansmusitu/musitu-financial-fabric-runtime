# Draft — MUSITU Sovereign Payments Technical Evaluation Proposal for Zimbabwe

Date: 2026-10-06  
Status: internal draft; not submitted; no regulatory or operator approval implied

## Proposed purpose

Request a structured technical evaluation with the Reserve Bank of Zimbabwe and the designated National Switch operator to determine whether MUSITU Sovereign Payments can serve as:

1. a technology layer supporting Zimbabwe's national instant-payment modernization;
2. a complementary interoperability/orchestration layer around the National Switch; or
3. a sovereign alternative technology stack should the authorities wish to compare multiple implementation options.

The evaluation should not require production funds.

## Institutional model

Preferred initial model:

- **RBZ:** regulator and scheme authority.
- **Designated National Switch / Zimswitch:** national operator for roles assigned by law or scheme rules, including routing/clearing and authoritative repository functions where applicable.
- **MUSITU:** technology supplier and systems-integration layer.
- **Banks, mobile-money operators, PSPs and fintechs:** certified scheme participants.

MUSITU does not assume authority to replace the designated National Switch.

## What MUSITU would demonstrate

A non-production reference environment can demonstrate:

- participant registry and lifecycle controls;
- payment aliases;
- request-to-pay;
- dynamic QR reference flows;
- multi-provider orchestration;
- monetary ledger integrity and reconciliation;
- idempotency and duplicate-execution resistance;
- risk/sanctions integration architecture;
- policy/authorization controls;
- mobile-money, ISO 20022 and Open Payments adaptation;
- operator-controlled production evidence gates;
- cross-border extension architecture.

The Zimbabwe QR profile remains normalized reference data until authoritative MAI allocation and approved EMV/scheme data specifications are supplied.

## Proposed evaluation topology

```
                    RBZ / Scheme Authority
                            |
                  Designated National Switch
                            |
              +-------------+-------------+
              |                           |
      MUSITU participant edge     existing participant paths
              |
     +--------+--------+--------+--------+
     |                 |                 |
   Bank A          Mobile Money        PSP/Fintech
     |                 |                 |
     +-----------------+-----------------+
                       |
             synthetic / UAT transactions
```

No live customer funds are required in the first evaluation stage.

## Evaluation scenarios

1. Bank-to-bank instant transfer.
2. Bank-to-mobile-money transfer.
3. Mobile-money-to-bank transfer.
4. Merchant dynamic QR payment instruction.
5. Request-to-pay acceptance/decline/cancel.
6. Duplicate/idempotent request handling.
7. Participant suspension and fail-closed alias resolution.
8. Risk-engine deny/unavailable behavior.
9. Reconciliation after provider/network ambiguity.
10. Operator kill controls and rollback.
11. Participant outage/recovery.
12. Cross-protocol normalization using ISO 20022 or GSMA MMAPI.

Real switch interfaces should only be added after the operator supplies authorized sandbox/UAT specifications.

## Information requested from RBZ / National Switch

To progress from reference implementation to a valid Zimbabwe integration, request:

- authoritative participant roles and onboarding/certification process;
- National Switch API/message specifications;
- QR repository integration contract;
- allocated MAI range and scheme-specific QR data definitions;
- settlement and finality rules;
- liquidity/limit management rules;
- refund, reversal and dispute procedures;
- fraud/AML integration requirements;
- reporting schemas and retention requirements;
- availability, DR and incident-management requirements;
- cryptographic/key-management profile;
- test environment and certification pack;
- regulatory/application pathway for a technology supplier versus a payment-system operator.

No interface not supplied by the relevant authority should be invented and represented as official.

## Comparative evaluation

If RBZ wishes to compare MUSITU with NIPL/UPI-derived infrastructure, request a neutral scorecard covering:

- functional requirements;
- security and resilience;
- interoperability;
- deployment/data sovereignty;
- implementation and operating cost;
- participant integration complexity;
- extensibility;
- cross-border pathways;
- scheme governance tooling;
- performance under identical workloads;
- operational references and support model.

MUSITU should not request preferential treatment and should not make unsupported superiority claims.

## Commercial models for discussion

Possible models, subject to procurement and regulatory requirements:

- perpetual or term software licence plus support;
- implementation/integration contract;
- annual maintenance and security-update contract;
- operator-hosted deployment with MUSITU support;
- managed service only where lawful and explicitly authorized;
- professional services for participant onboarding and certification tooling.

Transaction pricing is not assumed to be the primary revenue model. The objective is to avoid dependence on high domestic transaction fees where national policy seeks low-cost instant payments.

## Conditions before production

No production launch until all of the following exist:

- regulator approval for the exact role/scope;
- operator agreement and certified interfaces;
- settlement-bank/scheme settlement arrangements;
- participant certification;
- independent security assessment and closure;
- production target deployment evidence;
- DR/load/reconciliation/rollback proof;
- consumer-protection/dispute rules;
- data-protection compliance;
- explicit live-funds authorization under Financial Fabric's existing fail-closed gate.

## Internal decision

Prepare this proposal for external use only after engineering verification is green and the legal/entity/KYC representation to be used in any submission is confirmed.
