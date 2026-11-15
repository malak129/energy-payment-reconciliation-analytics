# Excel financial reporting

Phase 5 exports actual persisted SYNTHETIC SQLite data through XlsxWriter.
It does not rematch payments, activate reconciliation runs, update manual
decisions, or consume the evaluation oracle. All Python financial aggregation
uses integer EUR cents. Workbook amounts are numeric EUR with two decimals.

## Windows PowerShell

Use the existing virtual environment, or install with `pip install -e ".[dev]"`
as described in README.md. XlsxWriter and openpyxl are existing dependencies.

```powershell
.\.venv\Scripts\energy-reconciliation.exe report --help
.\.venv\Scripts\energy-reconciliation.exe report excel --database .\data\phase4-demo.sqlite3 --output-dir .\outputs\my-report
.\.venv\Scripts\energy-reconciliation.exe report exceptions --database .\data\phase4-demo.sqlite3 --output-dir .\outputs\my-report
.\.venv\Scripts\energy-reconciliation.exe report exceptions --database .\data\phase4-demo.sqlite3 --status all --output-dir .\outputs\my-report
```

CSV defaults to unresolved cases. Supported status filters: `unresolved`, `all`,
`OPEN`, `IN_REVIEW`, `RESOLVED`, `REOPENED`. CSV money fields retain explicitly
named integer `_cents` columns. UTF-8 BOM supports Excel opening German text;
the delimiter is comma. Use Data > From Text/CSV and choose UTF-8/comma when
Excel's regional default expects semicolons. Formula-like source strings are
prefixed with an apostrophe in CSV. XLSX source strings are written as text.

Excel always includes the full selected-run case population with status and
unresolved flag. It never silently removes resolved cases from the register;
summary counts and distribution exclude them.

## Snapshot selection

Without selectors the report uses the current accepted ledger head. Use
`--dataset-id` when the database contains multiple datasets.

```powershell
.\.venv\Scripts\energy-reconciliation.exe report excel --database .\data\phase4-demo.sqlite3 --run-id syn_run_436fba1b4ac450509c106860174a7b9a --output-dir .\outputs\original-baseline
.\.venv\Scripts\energy-reconciliation.exe report excel --database .\data\phase4-demo.sqlite3 --as-of 2026-03-01 --output-dir .\outputs\selected-date
```

`--as-of` selects an **existing exact-date persisted run**, using greatest
known-at then preferring LEDGER over ENGINE at equal cutoffs. `--run-id` pins
the exact snapshot and is recommended for reproducible historical reporting.
Supplying both requires matching dates. A date without a persisted run is
rejected with instructions to persist one first. Reporting never invents a
historical result by filtering final balances or rerunning accounting rules.

For another historical business date, explicitly persist it using Phase 4:

```powershell
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\phase4-demo.sqlite3 reconcile --historical --evaluation-date 2025-06-30 --known-at 2025-07-31T23:59:59Z --actor 'SYNTHETIC_DEMO:student' --reason 'Persist historical reporting snapshot'
.\.venv\Scripts\energy-reconciliation.exe report excel --database .\data\phase4-demo.sqlite3 --as-of 2025-06-30 --output-dir .\outputs\june-historical
```

That explicit reconciliation is a database write and remains separate from
read-only export. The original head does not change for `--historical`.

## Safe output policy

Names contain export kind, business date, run ID and CSV status where applicable.
Existing destinations are refused, including concurrent exclusive-create races.
Choose a new output directory for a refreshed export of the same run. There is
no overwrite flag or automatic deletion. The workbook is fully constructed in
a temporary sibling before exclusive creation/copy to its final filename.
Normal copy failures remove the file owned by that attempt; an abrupt process
termination during publication can leave a partial file. No cross-filesystem
or database/filesystem atomicity is claimed. Excel row/cell length limits cause
an explicit refusal rather than silent record/text truncation.

## Workbook contents

| Worksheet | Grain and purpose |
|---|---|
| Executive Summary | Financial KPIs, explicitly defined settlement ratio, unresolved/resolved case counts, aging and three editable native Excel charts when data exists |
| Monthly Reconciliation | One month per row, separate period activity and cumulative opening/closing stock balances |
| Invoice Register | One eligible invoice, original/corrected amounts, allocated/outstanding debt, dates, aging and identifiers |
| Payment Register | One eligible payment, bank identity, claim versus validated account, cash/outflow/application/residual totals and matching evidence |
| Allocation Details | One selected-run allocation, original amount, linked releases, net application, confidence and decision |
| Exception Queue | One selected snapshot/base review case, pending amount, status, suggestions and decision history |
| Customer Balances | One account linked to customer; debt and identified cash credit shown separately |
| Corrections and Reversals | One adjustment effect or linked allocation release, with original references and signed cash/debt columns |
| Audit Trail | All dataset operational audit records through export, including later/other runs; use Run id filter |
| Control Checks | Stored database controls against exported calculations, Python differences/status and Excel formula rechecks |
| Data Dictionary and KPIs | Snapshot identifiers, cutoffs, definitions, conventions and field dictionary |
| Manual Decisions | Additional normalized operator intent table with actor, reason, note, targets and undo link |

The requested name “Data Dictionary and KPI Definitions” exceeds Excel's
31-character limit; its tab is abbreviated. There are 12 sheets, including the
additional explicit Manual Decisions table. No native PivotTable is claimed.

Detail tables have native filters, alternating row bands, fixed headers and
frozen identifying columns. Dates use `dd.mm.yyyy`. Long evidence/JSON stays
in the cell; expand row height or use the formula bar to read full content.
Wide normalized registers require horizontal scrolling. Do not print a very
wide raw register fit-to-page and mistake reduced text for the intended
on-screen layout. Empty tables retain headers and one blank table row.

## Interpretation and refresh

Monthly data is a restatement at the **selected run's fixed known-at cutoff**,
using effective/booked dates. It is not a collection of separately computed
contemporaneous month-end snapshots. Final month can be partial. Sum period
activity, use the last closing balance, and never sum closing balances.

Current-head case state includes live workflow status; historical reports
reconstruct unresolved membership from their selected snapshot and eligible
decisions. They do not read future live RESOLVED status. ENGINE runs explicitly
exclude financial operator overlays. Nonfinancial current defer notes can be
more recent than the financial knowledge cutoff. Operational audit history is
separately labeled through-export history and may include later runs.

This is an exported snapshot. Filtering and PivotTables are supported; editing
cells does not create database decisions. Refresh by generating a new export.
Python controls are independently checked before export. XlsxWriter stores
verified cached formula results; openpyxl reads and inspects them and does not
evaluate formulas. Excel rechecks operate on numeric EUR with cent rounding.
See KPI_DEFINITIONS.md for exact denominators, date attribution and signs.

To create a native PivotTable manually in Excel: select the Invoice Register
table, Insert > PivotTable > New Worksheet, place Account id in Rows and
Outstanding (EUR) in Values with Sum. For monthly analysis use the Monthly
Reconciliation table and sum activity columns only. Refresh after replacing a
source table with a new report. The exporter does not create PivotTables.

## Full-data demonstration and checks

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.reporting.demo --database .\data\phase4-demo.sqlite3 --output-dir .\outputs\phase5
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

The demo requires a new directory. It reports the real primary DB, backs it up
to a separate safe database, exports after an explicit demonstration allocation
and undo, validates amounts/structure, and verifies the original DB SHA-256 is
unchanged. It records actual evidence in verification.json. See
PHASE_5_VERIFICATION.md for executed results and visual-verification limits.
