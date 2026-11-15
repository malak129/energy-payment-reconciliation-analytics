# Phase 6 verification — 2026-11-15

Implemented the seven-page local Streamlit/Plotly financial operations dashboard.
It reads actual SQLite snapshots, reuses Phase 4 financial services and Phase 5
reporting, and is bound to loopback only. Phase 7 and Phase 8 were not started.
The initial demonstration-runner defect and recovery are documented explicitly
below; the successful corrected run is distinguished from that failed attempt.

## Actual checks

| Check | Executed result |
|---|---|
| Complete pytest suite | **232 passed in 106.25 seconds**, 0 failed |
| Previous tests preserved | All **212** previous tests pass |
| New dashboard test cases | **20** pass, including seven parameterized page checks |
| Ruff lint | All checks passed |
| Ruff formatting | 69 Python files already formatted |
| Editable installation | `pip install -e ".[dev]"` succeeded using build isolation |
| Doctor | Exit 0; dependencies and package modules import |
| pip check | No broken requirements found |
| All seven pages | Pass AppTest on temporary and full actual datasets; also visited in the live browser |
| KPI/SQLite/Phase 5 Excel consistency | Exact agreement, including displayed EUR and 343 unresolved cases |
| Financial controls | **26 PASS**, all differences **0 cents** |
| Confirmed allocation and linked reversal | Pass on a separate full-data backup in the corrected run |
| Corrected run queue sequence | **343 → 342 → 343** |
| Corrected run final controls | Every control field restored exactly |
| Live browser Excel download | Downloaded successfully; bytes match the generated file and all monetary cells match SQLite |
| Filtered CSV | Generation/download control verified in browser and AppTest; content/status filters tested |
| Source files/oracle | All 33 manifest-listed file hashes unchanged |
| Database integrity | Recovered primary, successful demo copy and retained incident DB: integrity OK, zero FK violations |
| Screenshots | Actual desktop and narrow-view screenshots saved and inspected |

Verified environment: Python 3.12.14, SQLite 3.53.1, Streamlit 1.67.0,
Plotly 6.9.0. Existing runtime packages were reused. The Streamlit minimum is now
1.67, the verified API floor for the implemented width/download/testing surfaces.
No reconciliation rule, database schema version or financial sign changed.

pytest and the local HTTP server used approved execution outside sandbox temp/
socket restrictions. An initial no-build-isolation editable install failed
because setuptools was absent; the normal build-isolated installation supplied
the build backend and completed successfully. These were environment failures,
not passing checks or silently omitted requirements.

## Launch and actual browser evidence

Executed local server command:

```powershell
.\.venv\Scripts\python.exe -m streamlit run src/energy_reconciliation/dashboard/app.py --server.headless true --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false -- --database data/phase4-demo.sqlite3 --read-only
```

The health endpoint returned `ok`; the server reported 127.0.0.1:8501. No public
deployment, tunnel, account connection or Deploy action was performed. The
browser was returned to Executive Overview. The default database's financial
actions were disabled by --read-only for live browser checks.

All pages were inspected in the live in-app browser:

- Executive Overview: six money KPIs, 92.3% settlement ratio, 343 unresolved
  cases, passing controls and five Plotly views.
- Payment Reconciliation: 7,100 payments, 284 pages of 25 rows; searching
  SYN-EVENT-P-0002167 returned exactly one record.
- Manual Review Workspace: 343 unresolved cases, 14 pages; original/current
  review schema and read-only financial-action restriction visible.
- Customer Accounts: search for SYN-KONTO-000286 yielded one account; explicit
  selection displayed invoice/payment history, EUR 1,581.24 allocated, zero debt
  and separate zero cash credit.
- Financial Analytics: eight Plotly charts and contract/date filters; descriptive
  scope and snapshot-age distinction visible.
- Audit and Financial Controls: 26 passing checks, run/rule/import/decision
  sections and 22,834 operational events with 50-row SQL pagination.
- Reports and Exports: generated Excel, downloaded it, and generated the filtered
  CSV download control without overwriting files.

Actual screenshots are in outputs/phase6-screenshots:
01-overview.jpg (narrow layout), 02-desktop-overview.jpg, 03-payments.jpg,
04-manual-readonly.jpg, 05-account-drilldown.jpg, 06-analytics.jpg,
07-controls.jpg, 08-reports.jpg. Desktop layout was checked at 1440×1000 and
the initial narrow browser viewport was 333×539. The temporary viewport override
was reset. Wide registers intentionally scroll horizontally. Screenshot review
prompted extra top padding so the fixed Streamlit header does not cover the
banner when the main view is at its top. Scroll position can persist between
pages, so a scrolled view need not show the top banner at every instant.

Some browser automation waits expired while Streamlit was still replacing page
content. Fresh DOM observations showed the requested completed states; those
timeouts were not counted as successful interactions on their own.

## Financial figures actually displayed

All values come from the current accepted run
syn_run_ae2627073bcf54c99653455cb75264ae, business as-of 2026-03-01,
known-at 2026-11-14T19:45:39.473637+00:00.

| Metric | EUR / count |
|---|---:|
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
| Unresolved cases | 343 |
| Cash / receivable differences | **0.00 / 0.00** |

Settlement ratio is allocated / adjusted receivables = 92.2540516%, displayed
92.3%. It is not match accuracy. The cash disposition donut has a different,
explicit denominator: net cash. Neither ratio is relabeled as the other.

The actual source population remains 500 customers, 600 accounts, 7,200 invoices,
7,100 payments and 7,296 unique bank events. Historical financial effect rows
are never globally summed as current receipts. The cached analytical Report has
no bulk audit/provenance rows; selected financial tables and controls agree with
the full Excel Report. Full audit queries and exports use their separate paths.

## Corrected full-data demonstration

Executed:

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.dashboard.demo --database data/phase4-demo.sqlite3 --output-dir outputs/phase6-verified --reference-workbook outputs/phase5-reviewed/excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
```

The corrected harness explicitly asserted the UI's database path, used a new
SQLite backup at outputs/phase6-verified/review-demo.sqlite3, and performed the
actual Streamlit form/confirmation sequence through AppTest. It proved Prepare
did not change money, then separately checked and submitted confirmation. The
UI updated, exposed the active prior decision, accepted a separately prepared/
confirmed linked undo, and restored all original balances and counts.

```text
Case: syn_case_03091690223456d485830ef36e874083
Selected invoice: syn_invoice_2d8276c816c450e4bbb294bc682d1348
Explicit allocation: 9654 cents (EUR 96.54)
Decision: syn_decision_a6e6d8057a6d5a2198a6a089523f806a
Final copied-ledger run: syn_run_b5fd85004eca5907a886fd3be72604a7
```

| Measure | Original | Allocated | Reversed |
|---|---:|---:|---:|
| Unresolved cases | 343 | 342 | 343 |
| Allocated EUR | 2,067,991.84 | 2,068,088.38 | 2,067,991.84 |
| Unapplied EUR | 88,893.16 | 88,796.62 | 88,893.16 |
| Outstanding EUR | 173,635.28 | 173,538.74 | 173,635.28 |
| Net cash EUR | 2,156,885.00 | 2,156,885.00 | 2,156,885.00 |
| Control differences EUR | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |

Machine-readable evidence: outputs/phase6-verified/verification.json. Its
primary_unchanged=true applies to the corrected run after recovery, not to the
initial failed attempt described below. Its browser_download_verified_separately
flag is false because the standalone harness tests download controls; actual
browser download evidence is in the separate browser verification artifact.

The UI-generated workbook on the copy has 12 sheets, 3 native charts, 62 formulas
and 26 passing controls. It retains four manual decisions and the new linked
release alongside the original Phase 4 history. Every saved monetary detail
cell was read back and compared with the corresponding integer-cent report row.

## Real browser download, not only a download-button claim

The live browser downloaded:

```text
<browser-downloads>/excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
```

Retained workspace copy:

```text
outputs/phase6-browser-downloads/excel-2026-03-01-syn_run_ae2627073bcf54c99653455cb75264ae.xlsx
SHA-256: 0913a5f3b687b368ec4d731621037b85d3db3fc58f3457515279e238a14d7707
```

Its bytes exactly match the generated file under
outputs/dashboard/88020f9416104f608f0c9e4c87c30e40/. Downloaded monetary rows,
26 controls, 343 unresolved cases, table ranges, 12 sheet inventory and 3 charts
were independently inspected against the primary SQLite Report. The downloaded
baseline has 6,905 allocation rows, 393 adjustment/release rows, 22,834 audit rows
and two original manual decisions; it does not include the copied demo's actions.
Evidence is outputs/phase6-browser-downloads/verification.json.

This verifies saved/downloaded content and caches, not native Excel formula
recalculation. The Phase 5 limitation on native Excel rendering remains unchanged.

## Actual measured performance

One corrected full-data run on this workstation measured:

| Measurement | Seconds |
|---|---:|
| Cold lightweight snapshot | 2.3862 |
| Warm cached snapshot | 0.0430 |
| Count + first audit page | 0.0197 |
| Initial AppTest startup/render | 3.7685 |
| Executive Overview rerender | 0.4255 |
| Payment Reconciliation rerender | 0.2331 |
| Manual Review Workspace rerender | 0.1484 |
| Customer Accounts rerender | 0.0918 |
| Financial Analytics rerender | 0.7289 |
| Audit and Financial Controls rerender | 0.2034 |
| Reports and Exports rerender | 0.1156 |

These are perf_counter observations from the recorded run, not browser latency,
concurrency benchmarks, service-level guarantees or fabricated targets. Other
local checks were running concurrently. Cache hits avoid reconstructing input
tables; audit paging avoids loading 22,834 full event rows on each interaction.

## Initial runner defect, recovery and regression

The first invocation used outputs/phase6-demo. AppTest executes in the same
interpreter as its caller. The harness set the copied database in environment
variables but failed to isolate its own --database command-line argument. The
app correctly gave that explicit argument precedence, so the test UI still
pointed at the primary file. One confirmed synthetic allocation of EUR 96.54
reached the primary. The harness then failed when it could not find that decision
in the intended copy. This was a demonstration configuration defect, not an
over-allocation or financial-engine invariant failure. It was reported during
the work, not concealed or counted as a successful safe-copy demonstration.

Recovery performed:

1. Stopped the read-only live server before file recovery.
2. Reversed the unintended allocation through Store.reverse_decision, using actor
   SYNTHETIC_DEMO:dashboard-recovery and an explicit explanatory reason. All money
   totals and the 343-item queue returned to baseline.
3. Preserved that database, containing both the unintended decision and its
   linked audited undo, as outputs/phase6-recovery/audited-incident.sqlite3.
4. Restored the primary from the untouched pre-action backup created before the
   failed demo. All Phase 4 table counts, original accepted run, controls and
   case population were checked against outputs/phase4-demo.json.
5. Added argv isolation to the demo environment context and an explicit displayed
   UI database-target assertion before any financial interaction. Added a
   regression that supplies an inherited primary CLI argument while the intended
   UI target is a copy, and verifies mismatch detection.
6. Re-ran the complete corrected workflow on a new copy and the full test suite.

No source transaction values, original CSV files or evaluation oracle were edited.
The incident history remains inspectable instead of being deleted. Because SQLite
backup/restore can change container/header bytes, the restored primary's file
hash differs from the pre-incident container; logical source records, original
history, table counts, accepted run and financial balances match the baseline.

```text
Primary before failed run (Phase 5 baseline):
82a55eb58211b26a60c7f60e6494a75eadb7b3a23f75dbe962c8436bfe34e431
Restored primary / successful corrected-run baseline:
d6674a691b1d07880e90b86ade2ad554e29030bc179b2b0fb386957720608158
Retained incident database after audited undo:
4d83befc9967e51e62f3d22fec9324472f49b2a5d5b9f634410a180988c8379a
```

The recovered primary's hash stayed unchanged through the successful rerun and
live browser exports. All three databases passed SQLite integrity/FK checks.

## Files and commands

Created dashboard/app.py, pages.py, components.py, queries.py, analytics.py,
services.py, exports.py and demo.py, plus tests/test_dashboard.py and the three
dashboard guides/verification documents. Updated dashboard/__init__.py, the
doctor scope, README, reconciliation documentation and the Streamlit requirement.
Optional read-only/selective-loading interfaces in persistence/database.py,
persistence/service.py and reporting/data.py were documented before coding and
remain backward-compatible. No SQL schema migration was introduced.

Representative executed checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py -q
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\energy-reconciliation.exe doctor --config config.example.toml
.\.venv\Scripts\python.exe -m pip check
```

Additional verification scripts compared source hashes, primary/copy/incident
integrity, restored table counts, downloaded bytes and all monetary workbook
cells. Browser navigation, real downloads, screenshots and viewport checks were
performed against the loopback server. No screenshots, tests or performance
numbers are inferred merely from source code.

## Acceptance and known limits

All Phase 6 functional criteria now pass: all prior/new tests, Ruff, seven working
pages, exact SQLite/Excel KPIs and controls, explicit safe service operations,
cache invalidation, exports through Phase 5, preserved source data and complete
documentation. The initial failed safe-copy attempt remains a documented
recovered defect; successful later evidence does not erase it.

Limits: trusted local synthetic use only; no multi-user authentication,
production concurrency, public deployment, tamper-proof audit or Phase 7/8 work.
The UI allocates one invoice per operation; the existing CLI/service supports
explicit multi-invoice splits. Refund/correction services are displayed but no
new dedicated financial-adjustment UI is claimed. Historical selection supports
existing persisted runs only. Aging stays at snapshot as-of, while filtered cash
activity and closing-stock series follow their stated dates. Wide evidence tables
scroll; cross-browser/device coverage beyond the inspected viewports is unverified.
Native Excel recalculation/printing remains unverified; Python controls and
downloaded content are verified. No invented performance guarantee is made.

Stopped for approval before Phase 7.
