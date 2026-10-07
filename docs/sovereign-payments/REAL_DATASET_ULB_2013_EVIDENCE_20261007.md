# MUSITU Sovereign Payments — ULB 2013 Real Dataset Evidence

Date: 2026-10-07  
Implementation head: `8d512039cf074bb699fb22b78221686fe849bfd8`  
Status: isolated real-dataset engineering evidence; not production certification

## Dataset provenance

Dataset: ULB / Worldline Credit Card Fraud Detection, mirrored by OpenML as dataset `43627`.

Observed raw ARFF SHA-256:

`f9b190614995080ee8ba205a75b538704a55f093b8c1991de10de4f23f6461de`

Observed deterministic MUSITU row fingerprint:

`d983586bf7eb24068dc59823a55beee21bc3286a526e1764fa8bf8455c6a92d4`

Raw data was downloaded into isolated verification sandboxes and **was not committed to Git**.

## Published/observed population

Observed and asserted against the public dataset metadata:

- source rows: **284,807**
- fraud-labelled rows: **492**
- legitimate rows: **284,315**
- zero-amount rows: **1,825**
- non-zero amount rows: **282,982**
- time range: `0.0` to `172792.0`

The dataset does not disclose transaction currency. MUSITU therefore used ISO 4217 `XXX` solely for contract validation and made no currency inference.

## Full streaming contract scan

Every non-zero real transaction amount was converted exactly to integer minor units and passed through `SwitchTransferInstruction`.

Results:

- validated instructions: **282,982**
- malformed rows: **0**
- full scan elapsed: **3.722 s**
- scan rate: about **76,528 rows/s**
- live funds moved: **false**
- production authorized: **false**
- fraud accuracy evaluated: **false**

No PCA feature was renamed or treated as a known payment semantic.

## Stateful SQLite replay

The replay combined real ULB amounts/time order/fraud labels with synthetic MUSITU participant IDs and deterministic synthetic debit/credit direction.

### 10,000-row stage

- clearing obligations: **9,885**
- fraud labels / reference disputes: **38 / 38**
- chained audit events: **9,926**
- elapsed: **10.337 s**
- audit chain valid
- net positions balanced
- identical idempotent replay returned the same obligation
- conflicting replay failed closed
- payment intents: **0**
- ledger postings: **0**

### 50,000-row stage

- clearing obligations: **49,572**
- fraud labels / reference disputes: **148 / 148**
- audit events: **49,723**
- elapsed: **48.794 s**
- all correctness invariants passed

### Full 284,807-row stage

- clearing obligations: **282,982**
- zero-amount rows skipped: **1,825**
- fraud labels / reference disputes: **492 / 492**
- chained audit events: **283,477**
- elapsed: **281.589 s**
- about **1,005 obligations/s** sequentially
- audit chain valid
- net positions balanced with sum `0`
- idempotency passed
- conflicting replay failed closed
- payment intents: **0**
- ledger postings: **0**

Result: **PASS**

## Stateful PostgreSQL replay

PostgreSQL version: **18.6**, UTF-8, local isolated sandbox.

### 10,000-row stage

- obligations: **9,885**
- fraud labels/disputes: **38 / 38**
- audit events: **9,926**
- elapsed: **40.928 s**
- about **244 source rows/s**
- all correctness invariants passed

### 50,000-row stage

- obligations: **49,572**
- fraud labels/disputes: **148 / 148**
- audit events: **49,723**
- elapsed: **210.299 s**
- about **238 source rows/s**
- audit chain valid
- net positions balanced
- idempotency passed
- conflict replay failed closed
- payment intents: **0**
- ledger postings: **0**

Result: **PASS**

## Important performance finding

The sequential PostgreSQL reference replay is materially slower than SQLite in this harness.

That is **not yet evidence of production throughput**, because the harness is single-process, intentionally audit-heavy, and opens transactions/connections according to the current reference-path behavior. It is, however, a real scaling signal that requires further connection-pooling/concurrency/load investigation before MUSITU makes national-scale performance claims.

No RBZ or Zimswitch throughput/certification threshold is currently available to compare against.

## What this dataset did and did not test

It **did test**:

- exact real monetary amount ingestion;
- 284k-row deterministic normalization;
- clearing-obligation persistence;
- real temporal ordering;
- idempotent duplicate behavior;
- conflicting-replay fail-closed behavior;
- chained audit integrity at 283k events;
- dispute-path exercise from 492 real fraud labels;
- PostgreSQL and SQLite state behavior;
- absence of unintended payment/ledger movement.

It **did not test**:

- Tazama/Watchman fraud-detection accuracy;
- live bank/card authorization;
- official Zimswitch interface compatibility;
- settlement finality;
- network latency;
- RBZ/Zimswitch certified throughput;
- production concurrency capacity.

## Next real datasets

The next evidence passes are:

1. Elliptic real Bitcoin transaction graph for AML/graph-linked transaction stress;
2. 2026 deployment-derived online-banking inference logs for recent latency/operational traces, with the explicit caveat that the source system was a public demonstration service rather than a licensed bank;
3. additional transaction-level datasets only after provenance/license review.
