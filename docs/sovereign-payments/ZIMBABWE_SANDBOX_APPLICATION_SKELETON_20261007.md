# MUSITU Sovereign Payments — Zimbabwe Sandbox Application Skeleton

Date: 2026-10-07  
Status: preparation only; **not submitted**

## 1. Applicant position

Proposed applicant role for pre-application discussion:

**Technology supplier / payment-infrastructure integration layer under evaluation.**

MUSITU should not self-classify as a payment-system operator or payment-service provider until RBZ confirms the applicable regulatory role.

## 2. Product

**MUSITU Sovereign Payments**, a module of MUSITU Financial Fabric.

Reference capabilities currently implemented and tested:

- participant registry and certification lifecycle;
- alias/address directory;
- request-to-pay;
- QR reference repository and Zimbabwe 2026 profile;
- generic sovereign switch contract;
- clearing/net-position reference ledger;
- dispute/refund/reversal lifecycle;
- country-profile evidence gate;
- country-adapter conformance harness;
- regulator evaluation-pack generator;
- SQLite and PostgreSQL execution;
- fail-closed production/live-funds controls.

## 3. Problem statement

Evaluate whether MUSITU can provide a sovereign, locally controlled technology/integration layer supporting Zimbabwe's existing national payment architecture without replacing roles assigned to RBZ, Zimswitch, licensed banks, mobile-money operators or other regulated participants.

## 4. Proposed sandbox/UAT scope

Initial test should remain synthetic or operator-UAT only unless RBZ explicitly authorizes otherwise.

Candidate scenarios:

1. bank-to-bank normalized transfer instruction;
2. bank-to-mobile-money normalized instruction;
3. mobile-money-to-bank normalized instruction;
4. merchant dynamic QR payment instruction;
5. request-to-pay accept/decline/cancel;
6. idempotency and duplicate replay;
7. participant suspension/fail-closed resolution;
8. risk-engine fail/deny behavior;
9. clearing/net-position calculation;
10. dispute/reversal mapping;
11. reconciliation after ambiguous provider/network status;
12. operator kill/rollback controls.

## 5. Technical architecture

```
RBZ / scheme authority
        |
Designated National Switch / Zimswitch
        |
licensed test participant(s)
        |
MUSITU Sovereign Payments adapter layer
        |
MUSITU Financial Fabric controls
(policy | risk | audit | reconciliation | ledger boundary)
```

Country-specific protocol behavior must be sourced from authoritative operator specifications. The generic MUSITU adapter contract is not represented as the official Zimswitch interface.

## 6. Current evidence

Current engineering evidence includes:

- Python 3.13.15 independent verifier;
- full Financial Fabric regression green;
- dedicated Sovereign Payments CI green;
- PostgreSQL 18.6 real execution;
- reference UAT;
- audit-chain verification;
- no-payment/no-ledger side-effect proof for the reference UAT;
- country-adapter fail-closed conformance;
- public RBZ/Zimswitch evidence matrix;
- production-rail isolation.

## 7. External blockers

The Zimbabwe profile remains blocked on:

- authoritative National Switch message interface;
- actual MAI allocation/process evidence;
- EMV/Zimbabwe QR conformance evidence;
- participant certification/UAT pack;
- operative settlement-finality rules.

These cannot be satisfied by MUSITU engineering alone.

## 8. Proposed customer/fund boundary

Initial position:

- no retail customer acquisition;
- no unrestricted live customer funds;
- no public merchant launch;
- no claim of production settlement;
- synthetic/UAT values only unless RBZ and the licensed partner authorize limited live testing;
- explicit transaction and participant limits set by the approved sandbox plan.

## 9. Proposed safeguards

- fail-closed production rail allow-list;
- explicit actor/evidence/authorization binding;
- idempotency and replay controls;
- audit-chain integrity;
- participant status controls;
- country-profile dependency gate;
- no inferred operator mappings;
- no promotion from reference to externally verified without evidence;
- rollback/kill procedure before any live test.

## 10. KPIs for an approved test

Candidate KPIs, to be agreed with RBZ/operator:

- successful authorized transaction-instruction rate;
- duplicate/replay rejection rate;
- status reconciliation accuracy;
- audit completeness;
- dispute/reference lifecycle correctness;
- participant suspension enforcement;
- recovery after simulated outage;
- latency/throughput under operator-approved workload;
- zero unauthorized fund movement;
- zero production-boundary bypasses.

No KPI threshold is represented as an RBZ requirement until supplied by RBZ/operator.

## 11. Licensed partner section

To be completed only after RBZ confirms the live-test route.

Required partner facts:

- legal entity and RBZ licence category;
- National Switch participation status;
- UAT/sandbox capability;
- sponsor/settlement role if applicable;
- technical owner;
- compliance owner;
- written authorization for test scope.

## 12. Requested regulatory treatment

The application should ask RBZ to specify:

- whether sandbox participation is required;
- whether MUSITU is treated as technology supplier, fintech applicant, critical outsourced service, PSO/PSP applicant or another category;
- whether a licensed partner must be applicant/co-applicant;
- which regulations/guidelines apply;
- which requirements may be tested under controlled conditions;
- the permitted duration, participants, values and transaction volumes.

## 13. Production boundary

Sandbox/UAT success must not itself activate production.

Production remains separately blocked pending:

- RBZ role/approval;
- Zimswitch/operator authorization;
- participant certification;
- settlement arrangement;
- external security review;
- target deployment evidence;
- explicit live-funds authorization.

