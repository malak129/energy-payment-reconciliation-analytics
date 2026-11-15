# Local financial operations dashboard

Phase 6 uses Streamlit and Plotly over persisted SYNTHETIC data. The visible
banner is “SYNTHETIC DATA — PORTFOLIO DEMONSTRATION”. There is no real-company
branding, external bank connection, authenticated operator system or public
deployment. All financial changes go through the existing Phase 4 services.

## Install and prepare a database in Windows PowerShell

From the repository root, using Python 3.11+ (tested with Python 3.12):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\energy-reconciliation.exe doctor --config .\config.example.toml
```

Skip venv creation if the existing project environment is already installed.
Streamlit 1.67+ (the verified API floor) and Plotly are runtime dependencies.
Activation is optional;
calling the interpreter directly avoids PowerShell execution-policy changes.

Use the existing data/phase4-demo.sqlite3 for the verified default state. For a
new project database, generate/import/reconcile first:

```powershell
.\.venv\Scripts\energy-reconciliation.exe generate --output-dir .\data\synthetic-new
$db = '.\data\dashboard-demo.sqlite3'
.\.venv\Scripts\energy-reconciliation.exe db --database $db init
.\.venv\Scripts\energy-reconciliation.exe db --database $db import --input-dir .\data\synthetic-new --actor 'SYNTHETIC_DEMO:student' --reason 'Import portfolio dataset'
.\.venv\Scripts\energy-reconciliation.exe db --database $db reconcile --actor 'SYNTHETIC_DEMO:student' --reason 'Establish dashboard snapshot'
```

Existing generated input is data/synthetic; generation is unnecessary when
reusing it. Commands refuse conflicting existing data rather than overwriting.
An initialized empty DB, missing DB, invalid schema or imported-but-unreconciled
dataset produces an explanatory dashboard message; the dashboard never creates
a missing database or runs reconciliation automatically.

## Launch locally

Read-only browsing of the actual Phase 4 database:

```powershell
.\.venv\Scripts\python.exe -m streamlit run .\src\energy_reconciliation\dashboard\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false -- --database .\data\phase4-demo.sqlite3 --read-only
```

Open http://127.0.0.1:8501 in a local browser. Ctrl+C in the server terminal stops
it. The loopback binding is intentional; no deployment/publication is required.
`--read-only` disables financial forms while keeping analysis and exports
available. Analytics always use read-only database connections in either mode.

For practice, back up to a **new** file and launch that copy without --read-only:

```powershell
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\phase4-demo.sqlite3 backup --target .\data\dashboard-practice.sqlite3 --actor 'SYNTHETIC_DEMO:student' --reason 'Create separate financial practice database'
.\.venv\Scripts\python.exe -m streamlit run .\src\energy_reconciliation\dashboard\app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true --browser.gatherUsageStats false -- --database .\data\dashboard-practice.sqlite3 --exports .\outputs\dashboard-practice
```

The backup CLI appends its completion audit to the source after copying. For a
demo that preserves the primary file unchanged during a successful run, use the
Python demonstration below; its backup adapter has no source audit write.

Optional environment variables supply defaults:
ENERGY_RECONCILIATION_DB, ENERGY_RECONCILIATION_EXPORTS and
ENERGY_RECONCILIATION_READ_ONLY=1. Explicit app CLI database/export arguments
take precedence. No .env file or secrets are required. The demo harness isolates
its own CLI arguments before testing the app and asserts the intended UI target.

## Navigation and snapshot selection

The sidebar shows the local database path, dataset, persisted as-of dates and
persisted reconciliation runs. Default is Current accepted ledger. Historical
views use immutable stored runs and cannot submit financial changes. Selecting
an as-of date lists existing exact-date runs; it does not recompute history.
The business date and knowledge cutoff are both visible. Refresh database clears
cached snapshot and case evidence; external changes also invalidate through
database/journal/WAL file identity and a bounded cache lifetime.

| Page | Workflow |
|---|---|
| Executive Overview | Six monetary KPIs, settlement ratio, unresolved cases, controls and charts for receipts, cash disposition, closing debt, categories and aging |
| Payment Reconciliation | Search IDs/references/customers/accounts; filter dates, state, integer-cent amount range, rule and exception category; paginate and inspect allocations, invoices and evidence |
| Manual Review Workspace | Filter cases, inspect originals/candidates/history, deliberately choose an invoice, prepare and separately confirm allocation or linked undo |
| Customer Accounts | Search customer/account/contract and inspect electricity/gas contract debt, credit, invoices, validated payments and adjustments |
| Financial Analytics | Filter activity by date and contract type, with volume, issuance, net cash, closing debt, timing, aging, categories and settlement ratio charts |
| Audit and Financial Controls | Exact checks, run/rule/import history, decisions/releases and SQL-paginated audit events filtered by entity/action/reference and UTC date |
| Reports and Exports | Generate/download the selected run's Phase 5 Excel workbook and status/category/search-filtered exception CSV |

Detail registers use 25-row pages, audit uses 50 rows. Payment drill-down selects
from the current page; account drill-down searches the complete selected account
population. Search can match validated or claimed account references, but cash
balances and customer payment histories use validated attribution only.

## Manual review and explicit confirmation

Use a separate copied database for interview practice. Confirm its path in the
sidebar before any change. Select Manual Review Workspace and a case. Read the
original payment, remaining cash, reason, suggested evidence and current invoice
balances. Suggestions are not assignments and no invoice is preselected.

Choose an invoice explicitly. Enter positive integer EUR cents (9654 means
96.54 EUR), a nonempty reason, a clearly labeled local actor and optional note.
Prepare allocation captures exact intent plus case/ledger revision tokens. It
does not move money. Inspect the confirmation preview, tick “I confirm this exact
financial change”, then choose Confirm and apply. Successful service validation
refreshes balances, queue and caches. Repeat submissions of the same prepared
intent use an idempotency key instead of posting twice.

The UI allocates one invoice per operation; repeat explicit partial allocations
or use the existing Phase 4 CLI for supported multi-invoice splits. All targets
remain subject to available-cash, outstanding-debt and account invariants.

To undo, expand Reverse an earlier manual allocation, explicitly select an active
allocation decision, enter a reason, Prepare reversal, then separately confirm.
Original intent is retained with a linked release. A resolved case may disappear
from unresolved filters; the reversal selector still exposes eligible prior
allocations. Resulting balances and corresponding audit history are available.

Stale case/ledger tokens fail without money changes. Refresh and review changed
facts before preparing new intent. Failed financial service attempts can append
rejected-attempt audits. Prepared actions are tied to their database path, so
changing the sidebar path cannot redirect confirmation to another file. This is
local demo safety, not multi-user authorization or production concurrency.

## Financial interpretation

All KPIs reuse Phase 5 integer-cent calculations and selected-run memberships.
Reconciliation rate is net allocated / adjusted receivables, undefined when the
denominator is zero. It is not matching accuracy. Credit and debt remain separate.
Monthly receipt/correction/net-cash columns are activity; closing outstanding is
a cumulative stock. Monthly history is restated at the selected knowledge cutoff.

Financial Analytics filters change descriptive views, not global controls.
Contract filters exclude receipts without validated attribution. The first/last
activity months respect partial date boundaries. Aging remains the selected
snapshot's as-of aging and applies the contract filter only. Timing has one
observation per actively allocated receipt, measured from the earliest related
invoice due date; it does not imply causality. Audit history uses actual UTC
operation dates, can reference other/later runs, and is not a financial posting sum.

## Reports and downloads

Choose the persisted date/run in the sidebar, then Generate Excel workbook.
Download appears after generation. Every generation uses a new UUID directory
under the configured output root, preserving Phase 5 no-overwrite behavior.
The workbook contains the complete selected report, including audit and manual
history, not only the current screen's filtered payment rows. Control failures
remain visible in the workbook and UI.

CSV uses the export page's case status, category and text filters. Clearing all
statuses exports only headers. The Phase 5 writer retains integer `_cents`
columns, UTF-8 BOM and formula-prefix escaping. A generated download stays tied
to its original run; selecting a different run hides the prior download. No
native PivotTables or Excel formula recalculation claims are added by the UI.

## Verification and limits

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.dashboard.demo --database .\data\phase4-demo.sqlite3 --output-dir .\outputs\phase6-new-demo --reference-workbook .\outputs\phase5-reviewed\excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

The demonstration requires a new output directory. It compares the real SQLite
KPIs with the existing Excel report, tests all pages, creates a separate backup,
uses confirmed UI allocation/undo, generates report/download controls, and saves
actual timing and verification JSON. Browser/download/screenshot evidence and
the recovered initial runner defect are described candidly in
PHASE_6_VERIFICATION.md. No Phase 7/8, public hosting, authenticated roles,
production concurrency or tamper-proof audit is claimed.
