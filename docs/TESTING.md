# Testing, reproducibility and CI

The complete suite creates its own synthetic fixtures and temporary databases.
It needs no committed dataset, API key, private primary database or financial
service. Use Python 3.11+ and install the development extra as shown in the README.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe tools/release_check.py --customers 12 --billing-periods 2 --discrepancy-rate 1
```

Use normal Python, not `python -O`; some historical QA scripts use assertions.
The portable release check uses explicit failures for its financial checks and
never accepts a path to a pre-existing primary database. It generates temporary
inputs and uses the established safe-copy report demonstration for manual effects.

## Layers of evidence

| Layer | What is challenged |
|---|---|
| Foundation | Strict Pydantic schema boundaries, exact money/rounding, configuration, imports and diagnostics |
| Generation/ingestion | Deterministic bytes/hash-seed independence, identities, dates, links, malformed data, conflicting duplicates and oracle isolation |
| Engine | Exact/combined/partial/excess references, uncertain matches, outflows, corrections and historical knowledge |
| Persistence | Atomic rollback, FK/check constraints, stale/concurrent requests, idempotency, history and backup safety |
| Reporting | Every monetary cell versus report rows, formulas/caches, tables/charts, flow/stock dates, historical/manual visibility and CSV injection |
| Dashboard | Seven real AppTest pages, service confirmations, cache invalidation, routing, filters, empty/error and read-only states |
| Seeded properties | Independent arithmetic, no over-allocation, reversals, input order, misleading references, transaction rejection and replay |
| Release acceptance | Fresh generated sources → SQLite → safe-copy allocation/undo → Excel/CSV → all pages; independent arithmetic and separate oracle |

Four property seeds are 20261115–20261118, with 100/80/60/12 passing examples
recorded in Phase 7. Reproduce their statistics:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_quality_properties.py tests/test_quality.py::test_random_transaction_replay_and_rollback --hypothesis-show-statistics -q
.\.venv\Scripts\python.exe -m coverage run --branch --source=energy_reconciliation -m pytest -q
.\.venv\Scripts\python.exe -m coverage report
```

Phase 7 measured 90.73% statement and 86.69% branch coverage (89.92% combined).
These are dated observations, not a claim that all possible financial behavior
is covered. Its 249 passing cases are retained; Phase 8 adds a regression for the
demonstration checker's valid empty Excel table before manual decisions exist.
See [current release verification](../PHASE_8_VERIFICATION.md) for final counts.

## Default-size acceptance and evaluation

```powershell
.\.venv\Scripts\python.exe tools/release_check.py --evidence outputs/release-check.json
```

This exercises seed 42, 500 customers and 12 periods and writes a **new** optional
JSON evidence file. It evaluates the automatic baseline separately, requires zero
incorrect/missing allocations and individual oracle balance differences, and
verifies financial restoration on manual undo. Temporary workbooks are validated
and removed with their temporary directory; run the README demo to keep reports.

The original Phase 7 scripts also inspect private historical incident/backup and
workbook artifacts. Those artifacts are intentionally excluded from publication;
the original incident audit cannot be replayed from a clean clone alone. The
portable release check and full pytest suite can. See [quality report](../QUALITY_REPORT.md)
for historical evidence and bounded independent-audit scope.

## GitHub Actions

[Quality checks](https://github.com/malak129/energy-payment-reconciliation-analytics/actions/workflows/ci.yml)
runs on push, pull request and manual dispatch. The matrix selects Ubuntu with
Python 3.11/3.12 and Windows with Python 3.12. Each job installs the project,
checks dependency compatibility, runs Ruff and the full suite, builds a wheel and
runs the small portable financial/dashboard acceptance workflow. Permissions are
read-only repository contents; no secrets or remote financial services are used.

Local Windows checks do not establish Linux compatibility or a successful GitHub
run. The workflow badge and Phase 8 release report distinguish actual remote
results from configured intent. Dependency ranges allow platform-appropriate
resolution rather than copying a Windows-only transitive environment lock.

For dependency advisory checks, run `python -m pip_audit --local` in the development
environment. The unpublished local project can be skipped by PyPI advisory lookup;
that is not proof the application code has been security-certified.
