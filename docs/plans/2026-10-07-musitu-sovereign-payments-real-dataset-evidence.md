# MUSITU Sovereign Payments Phase 5 — Real Dataset Evidence Campaign

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stress MUSITU Sovereign Payments and Financial Fabric invariants against large, independently sourced real financial datasets before any RBZ/Zimswitch outreach.

**Architecture:** Keep raw third-party datasets outside Git. Add reproducible readers/replay harnesses that record dataset provenance/checksums and clearly separate real source fields from synthetic routing/participant metadata needed to exercise MUSITU. Full-dataset validation runs in isolated verification sandboxes; CI uses small fixtures only and never downloads large external datasets.

**Tech Stack:** Python 3.13.15, standard-library CSV/ARFF parsing, existing Sovereign Payments state machines, SQLite/PostgreSQL, pytest, isolated Vercel verification, public OpenML/Elliptic/Zenodo sources.

## Global Constraints

- Continue only on `feature/musitu-sovereign-payments-20261006`; PR #2 stays draft/unmerged.
- Do not enable a sovereign production rail or live funds.
- Raw external datasets must not be committed to Git.
- Every evidence report must identify dataset source, source ID/version, checksum, row counts and limitations.
- Do not claim fraud-detection accuracy from a dataset unless a real MUSITU fraud model is actually evaluated against ground-truth labels.
- ULB PCA features may be retained/ignored for provenance but must not be relabelled as named payment attributes.
- The ULB dataset does not disclose transaction currency; monetary contract testing must use ISO 4217 `XXX` (no currency) and state this explicitly.
- Real transaction rows may be combined with synthetic MUSITU participant IDs/aliases solely to exercise payment-system invariants; reports must distinguish those fields.
- Synthetic data remains permitted only for failure cases that no public real dataset supplies, and must be labelled synthetic.
- Outreach remains blocked until the real-dataset campaign has sufficient evidence.

---

### Task 1: ULB/Worldline real-transaction parser and full-dataset invariant validator

**Files:**
- Create: `musitu_financial_fabric/app/real_dataset_evidence.py`
- Create: `musitu_financial_fabric/scripts/run_real_dataset_evidence.py`
- Create: `musitu_financial_fabric/tests/test_real_dataset_evidence.py`

**Interfaces:**
- Consumes OpenML dataset 43627 ARFF rows with `Time`, `Amount`, `Class`.
- Produces `scan_ulb_arff(path) -> dict`.
- Produces CLI JSON evidence report.

- [ ] Add focused failing tests for ARFF parsing, exact two-decimal amount-to-minor conversion, zero-amount recognition, fraud count, deterministic row fingerprint, and `SwitchTransferInstruction` validation using `currency="XXX"`.
- [ ] Prove red.
- [ ] Implement streaming parser with no pandas dependency. Never load all 284,807 rows into memory.
- [ ] For each non-zero amount row, construct a normalized `SwitchTransferInstruction` with deterministic synthetic participant/alias fields and the real amount/time-derived reference.
- [ ] Record row count, nonzero count, zero count, fraud count, total amount, min/max nonzero amount, first/last time, instruction validation count, malformed count, file SHA-256 and elapsed time.
- [ ] Focused tests pass; full sovereign/full repo regressions pass.

### Task 2: Stateful replay over real ULB rows

**Files:**
- Modify: `musitu_financial_fabric/app/real_dataset_evidence.py`
- Modify: `musitu_financial_fabric/scripts/run_real_dataset_evidence.py`
- Test: `musitu_financial_fabric/tests/test_real_dataset_state_replay.py`

**Interfaces:**
- Produces `replay_ulb_state(path, *, limit, backend) -> dict`.

- [ ] Add red tests proving identical clearing replay is idempotent, conflicting replay fails closed, labelled fraud rows can drive reference dispute cases, and replay creates no `payment_intents` or `ledger_postings`.
- [ ] Implement two sandbox participants and one reference clearing cycle.
- [ ] Replay real non-zero transaction amounts into reference clearing obligations. Direction may alternate deterministically by source row number; this routing metadata is synthetic and must be reported as such.
- [ ] Use `Class=1` only to create a reference dispute case; do not infer or score fraud.
- [ ] Record obligations processed, duplicate replay results, disputes created, balanced net-position result, audit validity and side-effect counts.
- [ ] Execute first on SQLite fixture, then real PostgreSQL.

### Task 3: Full ULB evidence run

**Files:**
- Create: `docs/sovereign-payments/REAL_DATASET_ULB_2013_EVIDENCE_<run-date>.md`
- Create: `docs/sovereign-payments/evidence/ULB_2013_<run-date>.json`

**Interfaces:**
- Input URL: `https://openml.org/data/v1/download/22102452/credit-card-fraud-detection.arff`
- Dataset ID: OpenML `43627`
- Expected source facts: 284,807 transactions, 492 fraud labels.

- [ ] Download in isolated sandbox; calculate file SHA-256 before processing.
- [ ] Run streaming validation over every row.
- [ ] Run PostgreSQL state replay at the largest practical size that completes cleanly, increasing in stages and recording each stage rather than extrapolating unrun results.
- [ ] Compare observed row/fraud counts to OpenML metadata.
- [ ] Save only aggregate evidence/checksums to Git, never raw data.
- [ ] Re-run full repository regression after any harness changes.

### Task 4: Multi-dataset expansion

**Datasets:**
- Elliptic real Bitcoin transaction graph: 203,769 transactions / 234,355 edges; licit/illicit/unknown labels.
- 2026 deployment-derived online-banking inference logs: 56,962 REST submissions; CC BY 4.0; use only with explicit caveat that it is a public demonstration deployment, not a licensed bank dataset.
- Additional real datasets may be added only after provenance/license review.

**Evidence dimensions:**
- temporal ordering and burst replay;
- high-value/long-tail amount distributions;
- duplicate/replay handling;
- AML/dispute workload generation from real labels;
- graph-linked transaction integrity;
- reconciliation invariants;
- PostgreSQL concurrency and restart recovery;
- deterministic evidence reproducibility.

## Unresolved externally observable decisions

- No fixed pass/fail throughput target is imposed yet because RBZ/Zimswitch have not supplied an official performance/certification threshold. Evidence will report measured throughput/latency without claiming compliance.
- Dataset-specific source currencies remain unknown where publishers anonymize them; no currency inference will be made.
