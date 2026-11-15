# Phase 5 completion evidence — 2026-11-15

Implemented SQLite-backed Excel financial reporting and reconciliation analytics.
Phase 6 and later work was not started. This remains a SYNTHETIC portfolio
simulation, without certified accounting, bank integration or authentication.

## Executed checks

| Check | Actual result |
|---|---|
| Full regression suite | **212 passed in 58.56 seconds**, including all 188 previous tests and 24 new reporting cases |
| Ruff lint | All checks passed |
| Ruff formatting | 57 files already formatted |
| CLI report help | Exit 0; Excel/exception exports, output directory, date, run and status selectors listed |
| Doctor | Exit 0; runtime dependencies and package modules import |
| Dependency check | No broken requirements found |
| Actual primary DB Excel export | Created, readable with openpyxl; all monetary register cells checked against Python source rows |
| Financial controls | **26 PASS**, all differences exactly zero cents |
| Workbook structure | 12 sheets, 11 native tables, 3 native charts, 62 formulas |
| Exception CSV | 343 unresolved rows, no RESOLVED rows |
| Manual allocation/undo demo | Safe copied DB only; 343 → 342 → 343 unresolved cases; all totals restored |
| Primary DB preservation | SHA-256 unchanged after export and copied-database demo |
| Original synthetic sources | All 33 manifest file hashes unchanged, including evaluation ground truth |
| SQLite integrity | Primary and safe demo copy: integrity_check=ok, zero foreign-key violations |
| Visual samples | All 12 sheet viewport samples rendered and inspected; limitations below |
| Native Excel visual/recalculation | **Unverified**: installed Excel exposed no targetable window after two launch attempts |

Environment: existing `.venv`, Python 3.12.14, SQLite 3.53.1. Existing XlsxWriter,
openpyxl and SQLAlchemy dependencies were reused. No dependency additions or
changes to the database schema were required. All old tests were preserved.
pytest used approved execution outside the sandbox's temporary-directory
restrictions; fixtures used temporary databases, never the primary DB.

## Delivered workbook and evidence

Primary workbook, relative to repository root:

```text
outputs/phase5-reviewed/excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
```

Portable workbook path (machine-specific prefix removed for public release):

```text
outputs/phase5-reviewed/excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
```

The same directory contains the unresolved CSV and verification.json.
after-allocation and after-reversal subdirectories contain the separately
requested demonstration reports. The safe copy is
outputs/phase5/review-demo.sqlite3. Generated reports and databases are ignored
by Git. Earlier QA exports remain separate; no existing report was overwritten.

The final report is the actual current Phase 4 head:

```text
Dataset: syn_dataset_84540141918d5d3ab0859ff1baee3ff1
Run: syn_run_ae2627073bcf54c99653455cb75264ae
Business as-of: 2026-03-01
Known-at UTC: 2026-11-14T19:45:39.473637+00:00
Source version: syn_sourceversion_b379f937a0375c6398d2f1cd533da7a7
Rules: reconciliation-1.0.0+manual-1
Primary SQLite SHA-256: 82a55eb58211b26a60c7f60e6494a75eadb7b3a23f75dbe962c8436bfe34e431
```

Its business balances are the original default balances after Phase 4's explicit
manual undo. One case is REOPENED; the unresolved count legitimately remains
343. Original automatic matching remains unchanged. Allocation Details has
6,905 rows: the 6,904 original automatic allocations plus the retained Phase 4
manual allocation, whose linked release makes its active amount zero.

## Actual exported populations

| Worksheet | Actual records | Native table range |
|---|---:|---|
| Monthly Reconciliation | 15 | A5:S20 |
| Invoice Register | 7,200 | A5:N7205 |
| Payment Register | 7,100 | A5:O7105 |
| Allocation Details | 6,905 | A5:L6910 |
| Exception Queue | 343 | A5:N348 |
| Customer Balances | 600 accounts | A5:K605 |
| Corrections and Reversals | 393 | A5:M398 |
| Audit Trail | 22,834 | A5:L22839 |
| Manual Decisions | 2 | A5:J7 |

The remaining sheets are Executive Summary, Control Checks, and Data Dictionary
and KPIs. The requested full dictionary name exceeds Excel's 31-character sheet
name limit. Manual Decisions is an additional normalized sheet, giving 12 sheets.
The dictionary and controls have their own native tables (11 tables overall).
There are no native PivotTables. Manual creation instructions are supplied.

All selected payments and adjustments trace to the persisted population of
7,296 unique bank events. No repeated import or independently persisted run adds
cash to the report. Audit rows explicitly represent operational traceability
through export, including other runs, rather than financial activity.

## Financial totals: exact database-to-export agreement

| Metric | EUR |
|---|---:|
| Original issued invoices | 2,244,345.84 |
| Signed invoice corrections | -2,718.72 |
| Adjusted receivables | 2,241,627.12 |
| Gross incoming payments | 2,186,839.60 |
| Refunds | 2,055.36 |
| Chargebacks | 27,899.24 |
| Net cash | 2,156,885.00 |
| Net allocated cash | 2,067,991.84 |
| Unapplied cash | 88,893.16 |
| Outstanding receivables | 173,635.28 |
| Identified credit | 2,198.54 |
| Suspense | 86,694.62 |
| Cash control difference | **0.00** |
| Receivable control difference | **0.00** |

Settlement ratio is **92.2540516%** before display rounding, shown as 92.3%:
net allocated / adjusted receivables. It is not automatic match precision or
receipt-count coverage. Aging is EUR 14,652.18 at 61–90 days and EUR 158,983.10
over 90 days; all other buckets are zero. Their sum is the full outstanding debt.
Unresolved distribution: ambiguous 104, missing reference 98, overpayment 98,
unknown reference 43, totaling 343.

All 26 checks compare independent detail aggregation to stored controls or
validate control relationships: cash signs, cash/application/residual, corrected
receivables, customer/payment/invoice totals, correction effects, identified
credit/suspense and five final monthly closing stocks. Python computes integer
cent differences. The workbook shows both Python PASS/FAIL/difference and Excel
formula rechecks. A deliberately introduced one-cent discrepancy in a temporary
test report remained visible as FAIL; no discrepancy was suppressed.

Every exported monetary detail cell was independently read back and checked
against the corresponding integer-cent report value. openpyxl inspected structure,
formats, formulas and XlsxWriter-provided caches. It did not calculate formulas.

## Monthly and historical semantics verified

The 15 monthly rows span January 2025 through March 2026, with the final month
ending on 1 March. Activity uses invoice issued_on, cash booked_on and
allocation/release/correction effective_on. Cross-month receipts remain in their
booking month, independent of invoice or value month. Cumulative closing stocks
and opening-to-closing roll-forwards are distinct columns. Closing stocks are
never summed as monthly flows.

Monthly reporting is restated at the selected run's fixed known-at cutoff.
Historical as-of selects an existing exact-date persisted run; it does not
filter today's final debt to manufacture historical results. Unknown dates/runs
and inconsistent run/date selectors fail explicitly. Tests include a persisted
pre-activity historical snapshot with zero balances, empty normalized tables,
and an undefined settlement ratio shown as n.a.

Manual decisions are included for LEDGER snapshots at their applicable knowledge
cutoff; an explicitly selected ENGINE snapshot does not claim operator financial
effects. Historical resolved snapshots remain resolved after a later undo.
Current nonfinancial defer notes remain visible without moving the financial
head; current workflow and through-export audit scopes are labeled separately.

## Full-data manual demonstration on a safe copy

The primary DB was backed up using the Phase 4 SQLite backup API. Only that
separate copy received new decisions. An explicitly labeled demonstration actor
allocated **9,654 cents (EUR 96.54)** after inspecting current eligible debt.
This demonstration selection is not a normal automatic matching rule.

```text
Case: syn_case_03091690223456d485830ef36e874083
Selected invoice: syn_invoice_2d8276c816c450e4bbb294bc682d1348
Allocation decision: syn_decision_cee13e0dcdca4b6588d3e589574515d2
Resolved run: syn_run_8234276e923f58309584d862fde23f47
Undo decision: syn_decision_207dd8b773d74841b715055d356aa079
Final run: syn_run_33663d5365945aa7833a3a9d2b360bb7
```

| Result | Original | After allocation | After reversal |
|---|---:|---:|---:|
| Unresolved cases | 343 | 342 | 343 |
| Net allocated EUR | 2,067,991.84 | 2,068,088.38 | 2,067,991.84 |
| Unapplied EUR | 88,893.16 | 88,796.62 | 88,893.16 |
| Outstanding EUR | 173,635.28 | 173,538.74 | 173,635.28 |
| Net cash EUR | 2,156,885.00 | 2,156,885.00 | 2,156,885.00 |
| Cash/receivable differences EUR | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |

Resolved cases are retained with RESOLVED status and zero remaining review cash,
excluded from the unresolved summary. Undo retains linked allocation/release
and operator history, returning the case to REOPENED. All control fields—not
only the three balances in the table—return to original values. Later read-back
of the immutable resolved run remains unchanged. Final reviewed exports contain
26 passing controls and 62 formulas at each of the three stages.

## Commands executed

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_reporting.py -q
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\energy-reconciliation.exe report --help
.\.venv\Scripts\energy-reconciliation.exe report excel --output-dir outputs/phase5-preview
.\.venv\Scripts\python.exe -m energy_reconciliation.reporting.demo --database data/phase4-demo.sqlite3 --output-dir outputs/phase5
.\.venv\Scripts\energy-reconciliation.exe doctor --config config.example.toml
.\.venv\Scripts\python.exe -m pip check
```

After control additions and visual refinements, a verification script re-exported
the original and the two existing immutable demonstration runs with read_report /
export / inspect_workbook to new directories outputs/phase5-final and then
outputs/phase5-reviewed. It compared all monetary cells and stored final evidence
in verification.json. No additional financial changes or overwrites occurred.
Separate hashlib, csv and SQLite checks verified original source hashes,
primary DB hash, unresolved CSV membership and database integrity.

## Files and architecture

- reporting/data.py: consistent read transaction, persisted run/source selection,
  normalized report rows, date-based aggregation, account balances, aging and
  exact-cent comparisons with stored authoritative controls.
- reporting/excel.py: XlsxWriter styling, native tables/charts, formula caches,
  typed EUR/dates, CSV filters and exclusive no-overwrite publication.
- reporting/cli.py and root cli.py: report command registration and doctor scope.
- reporting/demo.py: primary export, safe copied-database allocation/undo,
  monetary read-back and workbook structure checks.
- reporting/__init__.py: implemented reporting scope.
- tests/test_reporting.py: 24 new unit/integration cases covering workbook
  readability, native objects, formats, formulas, exact values, dates, stocks,
  customer aggregation, manual/history status, CSV filters, corrections/outflows,
  empty snapshots, error cases, repeatability and no DB writes/overwrites.
- EXCEL_REPORTING_GUIDE.md, KPI_DEFINITIONS.md, this verification report,
  README.md and DATABASE_ARCHITECTURE.md: usage, semantics, evidence and limits.

No competing matching engine, alternate correction sign convention, data model
migration, dashboard or oracle mutation was introduced. Source/run hashes are
retained; aggregation is limited to the selected snapshot's memberships.

## Visual verification and known limitations

The bundled renderer produced viewport samples for all 12 sheets from a QA-only
extract of the actual exported cells. The complete workbook was not trimmed.
Summary layout, three charts, header bands, statuses, currencies and table
structure were reviewed. This prompted wider customer/actor/timestamp columns.
The preview engine displayed some date cells as serial numbers and one empty
text cell as a shared-string index. Native blank content, typed date values
and dd.mm.yyyy formats were independently verified with openpyxl.
Preview chart interpolation/date rendering is not proof of Excel behavior.

Installed Excel failed to expose a targetable window after two launch attempts.
Consequently native Excel display, formula recalculation, print pagination and
interactive chart/filter behavior remain unverified. No claim that openpyxl
evaluated formulas is made. Full-workbook preview import was stopped after
stalling; visible-cell samples supplied the layout review instead.

Other explicit limits: exact persisted-date selection only; no report-time
historical recomputation; no native PivotTables; no interactive financial edits;
wide normalized registers require scrolling; long evidence is retained in cells
and may need expanded rows/formula bar; Excel uses binary numeric EUR while Python
uses integer cents; publication is no-overwrite but not crash-atomic; audit
history intentionally includes other/later runs. Very large Excel row/cell values
are refused instead of silently truncated. Reports are snapshots, not production
financial certification or a posted general ledger.

Functional Phase 5 acceptance criteria pass. Native-application visual QA is the
explicit unverified item described above. Stopped before Phase 6 for user approval.
