# MUSITU Sovereign Payments — Licensed Partner Selection Framework

Date: 2026-10-07  
Status: internal framework; no partner selected or contacted

## Principle

Do not choose a licensed partner merely because it is large or familiar.

The partner should be selected **after RBZ role classification and Zimswitch technical-onboarding guidance**, because the approved test topology determines which licence, switch role and settlement capability are actually needed.

## Mandatory gates

A candidate is ineligible unless all applicable gates are satisfied:

1. valid Zimbabwe financial-services/payment licence for the proposed test role;
2. willingness to sponsor/co-run a controlled sandbox or UAT;
3. technical capacity to expose or connect to the authorized Zimswitch/National Switch test interface;
4. compliance owner willing to sign off test scope;
5. ability to reconcile test transactions and evidence;
6. no requirement to bypass RBZ/Zimswitch controls;
7. acceptable data/security arrangement.

## Weighted scoring model

| Dimension | Weight |
|---|---:|
| Regulatory fit for approved test role | 25 |
| National Switch / Zimswitch integration readiness | 20 |
| Sandbox/UAT technical capability | 15 |
| Compliance and governance maturity | 15 |
| Settlement/reconciliation capability | 10 |
| API/engineering collaboration speed | 10 |
| Strategic international relevance | 5 |

Total: 100.

## Evidence required before scoring

For each candidate collect:

- current licence/authorization category;
- legal entity;
- participation in relevant payment/switch scheme;
- named technical contact;
- named compliance/regulatory contact;
- UAT/sandbox availability;
- API/protocol capability;
- settlement/reconciliation role;
- data residency/security constraints;
- commercial/onboarding requirements.

Do not score assumptions.

## Candidate profiles to consider after route clarification

The likely categories—not yet named winners—are:

- commercial bank already connected to Zimswitch;
- licensed mobile-money operator;
- licensed payment-service provider/aggregator;
- institution already capable of merchant/payment API UAT;
- regulated institution willing to sponsor a technology-supplier sandbox application.

Zimswitch itself is the infrastructure/operator relationship and should not automatically be treated as the licensed financial-services partner required by the sandbox rules.

## Decision rule

Select the candidate with the highest evidence-backed fit for the **RBZ-approved test topology**, not the candidate with the largest retail footprint.

