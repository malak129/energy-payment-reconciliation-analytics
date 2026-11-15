# Dashboard architecture — Phase 6

## Interface changes defined before implementation

No schema migration, financial model change or matching-engine change is needed.
The dashboard will reuse Phase 5 Report/read_report and Phase 4 Store operations.
The following optional, backward-compatible read interfaces are needed:

- Database(read_only=True): existing-file SQLite URI mode=ro connections,
  read transactions and schema verification without initialization writes.
- Store.load_input(..., include_provenance=False, table_names=...): optional
  selective reconstruction; defaults preserve the full existing API.
- read_report(..., lightweight=True): omit provenance, unused input tables and
  through-export audit rows for cached analytical views. Financial rows, controls
  and formulas retain the same calculation path. Export uses the complete report.

Separate modules will own read-only queries/cache identity, business-service
adapters, filtering/chart preparation, export adapters, reusable UI components,
and seven pages. Analytical readers never execute arbitrary SQL or write source
records. Financial forms stage explicit operator intent and require a separate
confirmation before calling the existing validated service, with case/ledger
revision tokens and idempotency keys. Historical snapshots are read-only.

## Implemented module boundaries

| Module | Responsibility |
|---|---|
| dashboard/app.py | Streamlit entry, loopback launch options, dataset/date/run navigation, missing/empty/schema error handling |
| dashboard/pages.py | Seven views and explicit prepare/confirm interaction |
| dashboard/components.py | Reusable EUR formatting, bounded dataframes, paging, Plotly presentation and control status |
| dashboard/queries.py | SQLite read-only readers, catalog, case evidence, filtered audit SQL and analytical caches |
| dashboard/analytics.py | Search/filter/page/drill-down and chart data preparation; authoritative KPI inputs from Report |
| dashboard/services.py | Frozen staged intent, actor/reason validation, path binding and existing Store calls |
| dashboard/exports.py | Phase 5 full Excel and filtered CSV adapters, unique output directories |
| dashboard/demo.py | Actual-data AppTest workflow, safe-copy assertion, timings, Excel comparisons and evidence |

UI modules do not import the reconciliation engine. Only existing persistence
services perform financial writes. Chart calculations reuse reporting's
monthly_rollforward, financial effects and date conventions; no matching or
alternative sign convention is introduced. EUR floats appear only at chart/table
presentation boundaries and exported Excel display; aggregation remains cents.

## Read and cache policy

Read-only Database uses SQLite URI mode=ro plus query_only=ON and foreign keys on
every connection. Verification of an existing v1 schema runs in a read transaction.
Empty/unrelated/invalid files are rejected; schema creation is prohibited in this
mode. Financial Store defaults retain existing read/write behavior and BEGIN
IMMEDIATE atomicity. Schema version/signature remain unchanged.

Lightweight Report reconstruction reads only customers/accounts/invoices/payments/
reversals/corrections, selected run/base JSON, decisions and live case metadata.
It skips original source BLOBs, provenance and bulk audit rows. Defaults of the
existing full reporting API remain compatible. Full Excel exports deliberately
use the complete reporting path. Paginated audit queries use SQLAlchemy bound
filters, counts, LIMIT/OFFSET and optional inclusive UTC date bounds.

Snapshot cache: Streamlit cache_data, max 4 entries, 120-second TTL. Case evidence:
max 8 entries, 60-second TTL. Keys include resolved path, main file mtime/size and
WAL/journal stamps plus selected dataset/run. Explicit refresh clears both caches.
Accepted and rejected financial attempts invalidate them because failures may
append audit records. No SQLAlchemy connection, live writer or mutable financial
service is cached. Returned cache data is copied by Streamlit.

Payment/account filtering operates on cached selected-run rows, appropriate to
the verified 7,100-payment dataset. Tables show 25 rows per page; audit queries
fetch 50. No claim of unbounded-data scaling or simultaneous operator safety is
made. Actual timings are recorded by the demonstration, not invented targets.

## Write boundary and state

Prepare creates frozen intent containing database path, case/version, ledger
revision, targets or original decision, actor/reason/note and a unique request ID.
An invoice selector begins empty. Every financial operation requires a separate
checkbox and confirmation button. The adapter calls Store.allocate_case or
Store.reverse_decision; original transaction, invariants, idempotency, stale
guards, effect memberships and audit remain authoritative. UI errors never
grant permission to bypass those checks. Historical selection and --read-only
disable forms. These are local demo restrictions, not authentication.

Changing the database path cannot redirect a prepared action. The demonstration
harness also isolates its own process argv before AppTest and independently
asserts the displayed database path before financial interaction. This prevents
the CLI-inheritance defect described in PHASE_6_VERIFICATION.md; a regression
test covers it. Incident history from the first failed demonstration is retained.

## Time/filter/export semantics

Sidebar selectors choose existing immutable runs; no report-time reconciliation
occurs. Current case workflow may be newer than the financial known-at cutoff.
Historical membership and eligible decisions use the established Report logic.
Audit queries intentionally show operational history through the database read,
including other runs, with UTC dates distinct from business date filters.

Filtered analytics preserve first/last partial periods and cumulative stock
history at the selected knowledge cutoff. Contract filtering uses validated
attribution; suspense is not arbitrarily assigned. Aging stays at snapshot as-of
and is labeled accordingly. Descriptive timing counts each allocated receipt once.
Global controls remain selected-run controls and are not relabeled as filtered.

Excel generation reuses read_report and export without new workbook logic.
Filtered exception CSV uses a replaced Report exception view and the same Phase 5
writer. Unique output directories preserve no-clobber semantics. Download bytes
are the exact saved file and are tied to selected run identity. Report failures
remain visible. No native Excel evaluation, PivotTable or publishing is added.

No production authentication or concurrency guarantee is implied. The application
is intended for a trusted local desktop on 127.0.0.1, with synthetic data only.
