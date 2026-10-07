# MUSITU Sovereign Payments Independent Verification Receipt

Date: 2026-10-06
Branch: `feature/musitu-sovereign-payments-20261006`
Verified commit: `945d53df9dc1264e06f2aa0c3285ee1095529a07`
Verification environment: isolated Vercel sandbox, Cape Town (`cpt1`)
Session: `sbx_oKBwtGnm7cd82T21BptrEUIj89yk`

## Exact source verification

The verifier cloned the public repository and checked out the exact commit:

```
HEAD=945d53df9dc1264e06f2aa0c3285ee1095529a07
```

No source mutation was used for the verification run.

## Runtime

An evidence-locked supported Python runtime was installed independently:

```
Python 3.13.15
SQLite 3.53.1
```

Dependencies were installed using the repository's `constraints-ci.txt` and editable package metadata through `uv pip`.

## Sovereign focused suite

Command:

```bash
pytest -q tests/test_sovereign_*.py
```

Result:

```
..........................                                               [100%]
```

Exit code: `0`

Observed focused sovereign test count: 26.

## Full Financial Fabric regression

Command:

```bash
python -m compileall -q app tests
python -m pytest -q
```

Result:

```
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
```

Exit code: `0`

Two deprecation warnings were emitted by the FastAPI/Starlette test stack; no test failures occurred.

## Important GitHub Actions distinction

GitHub-hosted Actions for the draft PR were still failing before runner assignment at the time of this receipt. Diagnostic metadata showed `runner_id: 0`, empty runner names and `steps: []` across both Ubuntu 24.04 and Ubuntu 22.04 jobs.

Therefore:

- the code has independent executable green verification at the exact commit above;
- GitHub-hosted CI itself is **not** claimed green;
- this receipt does not authorize production deployment, live funds, RBZ approval, Zimswitch/National Switch registration, EMVCo certification or merge of the draft PR.

## Isolation readback

Direct repository readback confirmed:

- `_PRODUCTION_IMPLEMENTED_RAILS = {"ecocash"}`;
- no `"sovereign":` entry exists in `service.RAILS`;
- the authoritative Financial Fabric required-component registry remains 39 items.

## Decision

Phase 1 plus the Zimbabwe 2026 reference-profile code is executable and regression-clean at commit `945d53df9dc1264e06f2aa0c3285ee1095529a07` in the independent verifier.

The draft PR must remain unmerged until repository CI/required checks and any review requirements are satisfied.
