# Phase 7 verification — complete, awaiting owner approval

**READY for the bounded local synthetic-data portfolio demonstration.** No known
unresolved serious financial discrepancy remains in the evaluated workflow.
Native Microsoft Excel opening/recalculation remains unverified after an actual
UI attempt. This permitted limitation is explicit; production security and general
financial correctness beyond the tested rules/data are not claimed. Phase 8 has
not begun. Nothing was published or committed.

## Exact execution results

| Check | Actual result |
|---|---|
| Original baseline suite before fixes | 232 passed in 56.89 s |
| Initial targeted defect probes | 7 failed before their 6 underlying fixes; log retained |
| Original suite plus first regressions | 239 passed in 43.24 s |
| Final full suite with coverage | **249 passed, 0 failed in 179.17 s** |
| Previous tests preserved | All 232 retained and passing; 17 new collected cases |
| Seeded Hypothesis properties | 4 properties, 252 examples configured/executed across fixed seeds |
| Ruff | All checks passed |
| Coverage | 3,525/3,885 statements = 90.7336%; 853/984 branches = 86.6870%; combined 89.9158%, displayed 90% |
| CLI help / doctor | Exit 0; dependencies, package modules, configuration and SQLite checks pass |
| Dependency compatibility | `pip check`: no broken requirements |
| Wheel build | `energy_payment_reconciliation-0.1.0-py3-none-any.whl` built successfully |
| Dependency vulnerability audit | No known vulnerabilities in auditable installed packages after pip 26.3 upgrade; unpublished editable project skipped |
| Independent financial / recovery audit | PASS, exact integer-cent arithmetic and all compared entity/month-end balances agree |
| Independent workbook inspection | PASS: 12 sheets, 3 charts/6 ranges, 56 formulas, 600 account rows, 8 summary values |
| Default isolated acceptance | PASS: generation/import/reconcile/manual allocate/undo/Excel/CSV/seven pages/reimport/rerun |
| Larger source | PASS: 750 customers, 12 periods, 10,945 unique bank events; nonnegative balances |
| Real HTTP Streamlit process | PASS: loopback read-only server healthy after 1.6746 s; own child stopped |
| Primary and clean backup | Byte-identical, integrity/FKs pass; no unauthorized incident decisions |
| Source/oracle preservation | All 33 original manifest file hashes unchanged, including oracle |

The final suite was run after all production-code changes. Subsequent changes were
documentation and independent QA scripts; the updated scripts were also executed
and Ruff checked. Initial harness-only failures and excluded partial performance
attempts are documented in QUALITY_REPORT.md and PERFORMANCE_REPORT.md rather
than misreported as product regressions or successful acceptance runs.

## Financial and oracle results

Independent recomputation finds net cash 215,688,500 cents, net allocated cash
206,799,184 cents, unapplied cash 8,889,316 cents, adjusted receivables
224,162,712 cents and outstanding receivables 17,363,528 cents. Both control
differences and all compared individual invoice/payment balance differences are
zero. Month-end movement categories and cumulative stocks agree with reporting.
Manual allocation and reversal each move 9,654 cents in the isolated acceptance;
all controls return exactly to baseline. Reimports/reruns retain the accepted
snapshot and append appropriate audit/import history without duplicate cash.

The unmodified Phase 2 oracle yields 6,904 correct automatic allocation rows,
zero incorrect/missing rows, 98 correct releases and zero incorrect releases.
Allocation precision and expected-row coverage are both 100% (6904/6904).
343 review items remain intentionally unresolved. These metrics describe the
fixed synthetic evaluation set, not universal matching accuracy. See
QUALITY_REPORT.md for payment-based denominators and category differences.

Primary SHA256 before and after all QA:
`d6674a691b1d07880e90b86ade2ad554e29030bc179b2b0fb386957720608158`.
Clean Phase 4 backup and new Phase 7 baseline backup match exactly. The preserved
incident copy retains both the incident action and explicit undo, all original
audit IDs, and zero net financial effect; no incident-only decisions remain in
the restored primary. See QUALITY_REPORT.md for exact decision IDs and arithmetic.

## Files created or changed

| File | Purpose |
|---|---|
| `REQUIREMENTS_TRACEABILITY.md` | Pre-coding risk/requirements matrix plus executed evidence for A–M |
| `QUALITY_REPORT.md` | Independent financial results, incident recovery, defects, roots, fixes, oracle metrics and limits |
| `SECURITY_REVIEW.md` | SQL/file/destructive-operation/privacy/dependency/local-access review and residual assumptions |
| `PERFORMANCE_REPORT.md` | Actual stage timings, hardware, memory, larger-data scope and reproducibility |
| `PHASE_7_VERIFICATION.md` | Completion decision, exact results, commands and acceptance assessment |
| `tests/test_quality.py` | 14 temporary-database safety, transaction, routing, schema and security cases |
| `tests/test_quality_properties.py` | 3 seeded independent engine arithmetic/adversarial properties |
| `tools/phase7_audit.py` | Read-only source/effect arithmetic, identity/hash, recovery and original-file preservation audit |
| `tools/phase7_workbook_audit.py` | Independent workbook values, references, ranges and account checks |
| `tools/phase7_acceptance.py` | New isolated default/larger source workflows and measured stage timings/memory |
| `tools/phase7_server_probe.py` | Owned-child real loopback/read-only HTTP health check |
| `.streamlit/config.toml` | Project loopback default and usage telemetry disabled |
| `persistence/database.py` | Read-only reset/restore safety, exclusive backup destination, live DDL verification |
| `persistence/overlay.py` | Reject historically invalid cross-date neutralization during incompatible rebase |
| `dashboard/services.py`, `dashboard/pages.py` | Bind pending financial confirmation to database file identity and selected dataset |
| `reporting/excel.py` | Escape whitespace/control-prefixed CSV formulas |
| `pyproject.toml` | Optional dev dependencies: Hypothesis, coverage and pip-audit; runtime dependencies unchanged |
| `.gitignore`, `README.md` | Ignore Hypothesis cache; document Phase 7 scope, reports and local launch constraint |

Paths abbreviated in the table are under `src/energy_reconciliation` where
applicable. All original tests remain intact. Generated backup, financial audit,
oracle, coverage, dependency, acceptance, workbook and server evidence resides in
ignored `outputs/phase7`; original dataset/oracle files were not regenerated there.
The independent workbook audit uses a new copy of the clean Phase 5 workbook.

## Reproduction in Windows PowerShell

Run from the repository root using the existing Python
3.12 virtual environment. Its interpreter was successfully used for every check.
The QA-only libraries were installed with pip; the vulnerable old pip installer
was upgraded. Normal project setup remains `py -3.12 -m venv .venv` followed by
`python -m pip install -e ".[dev]"`; do not recreate a populated environment merely
to rerun these checks.

Commands actually executed in this phase include:

```powershell
.\.venv\Scripts\python.exe -m pip install hypothesis coverage pip-audit
.\.venv\Scripts\python.exe -m pip install --upgrade 'pip>=26.2'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests/test_quality.py tests/test_quality_properties.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_quality_properties.py tests/test_quality.py::test_random_transaction_replay_and_rollback --hypothesis-show-statistics -q
.\.venv\Scripts\python.exe -m coverage run --branch --source=energy_reconciliation -m pytest -q
.\.venv\Scripts\python.exe -m coverage json -o outputs/phase7/coverage.json
.\.venv\Scripts\python.exe -m coverage report --skip-covered
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m energy_reconciliation --help
.\.venv\Scripts\python.exe -m energy_reconciliation doctor
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe -m pip_audit --local --format json --output outputs/phase7/dependencies-final.json --progress-spinner off --timeout 20
.\.venv\Scripts\python.exe tools/phase7_audit.py
.\.venv\Scripts\python.exe tools/phase7_workbook_audit.py
.\.venv\Scripts\python.exe tools/phase7_acceptance.py
.\.venv\Scripts\python.exe tools/phase7_server_probe.py
.\.venv\Scripts\python.exe -m energy_reconciliation.evaluation --result outputs/reconciliation/reconciliation.json --ground-truth data/synthetic/evaluation/ground_truth.json --output-dir outputs/phase7/oracle
```

The final test output is `outputs/phase7/tests-final.txt`. Oracle export refuses
to replace an existing output directory; choose a new directory when reproducing.
Workbook audit expects the Phase 7 verification copy; copy the documented clean
Phase 5 workbook to that new path if rebuilding evidence in a fresh checkout.
Financial QA fixtures are synthetic and temporary. Never substitute the primary
database for the isolated acceptance target. The scripts use assertions; run normal
Python, not `python -O`. Existing retained generated artifacts are needed for the
primary/recovery audit; they are deliberately not committed to Git.

## Acceptance and remaining limitations

All Phase 7 final acceptance criteria pass within the stated local scope. No known
incorrect automatic allocation exists on the evaluated dataset, primary integrity
and incident recovery are verified independently, manual money invariants hold,
Excel cached totals match SQLite, routing regressions pass and end-to-end execution
succeeds. Performance is measured and documented. A serious unresolved financial
defect would block readiness; none remains in these checks.

Native Excel recalculation remains an explicit gap. Security review is bounded,
not production certification. The full-source independent audit supports the
full-knowledge baseline/incident fixtures and fails closed for unsupported runtime
correction/outflow histories; broader cutoff/workflow behavior is tested separately.
Cross-date neutralized rebases now reject incompatible source activation and need
a future reviewed rebase procedure. Strict live-DDL validation requires deliberate
migration/compatibility review when dependencies alter DDL formatting. Timings are
single observations under concurrent test load; only generation/import/reconciliation
were measured for the larger dataset. No external deployment, publication, release
polish or Phase 8 task was performed. Work stops here for owner approval.
