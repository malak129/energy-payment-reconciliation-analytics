# SQLite persistence — schema version 1

Phase 6 adds an optional Database(read_only=True) analytical connection mode and
selective input loading, preserving the schema and default financial service
behavior. The Streamlit dashboard caches lightweight Phase 5 projections and
uses existing validated Store operations only after explicit confirmation.
See DASHBOARD_ARCHITECTURE.md for cache/transaction boundaries and
PHASE_6_VERIFICATION.md for the initial demonstration defect and recovery.

Phase 5 reporting reads this unchanged schema in a consistent read transaction.
It selects one immutable run and source version; it does not sum historical
effect rows or rerun reconciliation. No Phase 5 database migration was needed.
See EXCEL_REPORTING_GUIDE.md and KPI_DEFINITIONS.md for exact source mappings,
historical selection and the separately labeled through-export audit scope.

SYNTHETIC local portfolio simulation. Phase 4 uses SQLAlchemy Core and SQLite,
not SAP, production banking infrastructure or certified accounting software.
The existing Phase 3 engine is reused unchanged for automatic reconciliation.

## Snapshot strategy and the Phase 3 persistence issue

Phase 3 allocation IDs belong to independently computed runs. Summing allocations
from several runs would double-count cash. Phase 4 therefore persists immutable
ENGINE runs and immutable LEDGER snapshots. A ledger snapshot selects exactly
one automatic base and replays eligible append-only operator effects over it.
run_allocations and run_releases record snapshot membership; controls always
describe one selected run, never all historical rows.

ledger_heads is a mutable pointer with a revision token. Activating a validated
new snapshot supersedes that pointer, without altering its predecessor. Identical
reconciliation reruns reuse the existing ID/results and do not increment revision
or insert allocations again. Actual attempt/audit records may still increase.

Manual actions are applied only if effective_on <= evaluation date and created_at
<= known_at. Their effective date is the current ledger evaluation date; arbitrary
backdated/future manual posting is not supported. created_at and audit timestamps
are actual aware UTC application times. Imported synthetic bank availability
continues to use the modeled statement receipt timestamps established in Phase 3.
Actual local import time is separate audit metadata, preserving reproducibility
of the original synthetic historical baseline.

Before a financial operation, the engine recomputes source knowledge at operation
time. If existing financial balances changed, the action is rejected until an
explicit reconciliation refresh. New automatic results cannot overwrite manual
decisions: replay must satisfy every cash/debt bound before activation. A conflict
rolls back the candidate run and leaves the previous ledger accepted. Explicit
undo on the last accepted source remains possible while a newer import is pending;
the operator can then retry reconciliation of that pending source.

A regression test found that a cancelled historical allocation could otherwise
block a later automatic payment. Fully reversed allocations/corrections may now
be represented as neutral historical effect pairs during rebase when applying
the cancelled leg would conflict with the new base. Original effects, linked
releases, decisions and original snapshots remain stored. Active decisions still
reject conflicting automatic results. This corrects snapshot replay, not source
data or the automatic matching rules.

## Tables and relationships

| Group | Actual tables and purpose |
|---|---|
| Schema | schema_versions: version, expected DDL signature and applied UTC timestamp |
| Dataset identity | datasets: immutable synthetic configuration identity; changing source contents belong to versions |
| Original records | source_records: canonical complete Pydantic payload, table/type, SHA-256 and synthetic marker |
| Customers/contracts | customers, accounts, invoices, invoice_items: indexed FK projections; original invoice amount never updated |
| Bank identity | bank_events: shared unique (dataset_id, source_system, bank_event_id), positive integer magnitude and payment/refund/chargeback kind |
| Cash details | payments, reversals: typed bank-event children; reversal parent FK points to payments |
| Source statements | bank_statements, source_import_rows: statement identity, row/event links and receipt metadata |
| Imported approvals | source_authoring_runs, source_approval_cases, source_approval_decisions, source_corrections: original Phase 2 approval fixtures, distinct from real application workflow |
| Source versions | source_versions, version_records, version_files, source_heads: immutable source membership and latest accepted source pointer |
| Original files/provenance | source_files stores exact bytes/path/hash; source_occurrences stores each original row occurrence, its field values and duplicate flag |
| Import attempts | import_batches: successful IMPORTED/DUPLICATE attempts with actor/time; failed attempts are separate rejected audit records |
| Reconciliation | rule_versions, reconciliation_runs: immutable complete ENGINE/LEDGER JSON, hashes, cutoffs, base-run FK and controls |
| Current ledger | ledger_heads: selected run and monotonic revision |
| Review | review_cases: stable dataset/payment/reason identity, status/version; case_evidence retains run-specific candidate evidence |
| Operator intent | manual_decisions: immutable sequence, action, targets, actor/reason/note, effective/knowledge timestamps, optional original decision link |
| Financial effects | allocations, allocation_releases, adjustments: immutable linked effects and explicit money signs |
| Membership | run_allocations, run_releases, run_adjustment_effects: effects selected by one snapshot |
| Traceability | audit_events: append-only application history with structured details and entity filters |

Original model payloads preserve optional fields and original domain schemas.
Normalized source values are immutable; untrimmed source values remain in exact
file bytes and occurrence payloads. The database reconstructs InputDataset from
version membership and payloads, so reconciliation does not need the CSV directory
after import. Operational source files include the manifest but exclude oracle
contents. Source approval fixtures never masquerade as executed application runs.

## Constraints and transaction boundaries

Every SQLAlchemy connection enables foreign_keys and a 30-second busy timeout.
Native backup connections also enable FK checking. IDs, foreign keys and unique
constraints cover source identity, contract/reference uniqueness, statement rows,
bank identity, decision sequence, single undo, snapshot membership and allocation
identity within a creation run. Indexed foreign keys support lookup paths.

CHECK constraints cover synthetic markers, EUR, positive/signed bounded cents,
integer storage, line sums, release authority XOR, allowed statuses and valid JSON.
Python/Pydantic rejects float money, including 1.0. SQLite INTEGER affinity can
coerce a mathematically whole SQL literal to an integer; storage checks are not
a claim to detect its original Python type. Service validation supplies that
boundary. Per-payment/invoice aggregate constraints are checked by transactional
services, not by summing all historical SQL rows.

All financial writers use BEGIN IMMEDIATE. The lock serializes SQLite writers;
case versions and ledger revisions additionally reject stale operator intent.
Operations commit their decisions, effects, run, controls, case updates, head
revision and accepted audits together. Any failure rolls back all these writes.
A separate transaction may then append a clearly REJECTED audit event. Rejected
events do not claim a successful financial action. Only completed valid snapshots
enter reconciliation_runs; failed attempts are recorded in audit, not as partial
financial snapshots.

Import commits dataset/version membership, original records, exact files,
provenance, batch and audit together. Same record ID/payload is reused; changed
immutable payload or reused bank identity is rejected. Same bundle twice records
a DUPLICATE attempt without duplicating cash. Overlapping/duplicate statement
representations are deduplicated by stable event identity. Reimporting an older
already accepted version does not move the current source pointer backwards.

The CLI imports complete generated bundles, not arbitrary bank CSV deltas. A new
complete revision cannot omit previously accepted core records; source removal
cannot erase cash. Earliest modeled bank knowledge is retained across revisions.
The lower-level normalized InputDataset API is used for controlled integration
tests; the operational directory adapter additionally validates file/checksum and
statement provenance. Generic individual bank formats/XLSX remain unsupported.

## Immutability, schema versioning and migrations

Application code never updates source/effect/run/decision/audit rows. UPDATE and
DELETE triggers protect these tables against ordinary accidental writes. Only
source_heads, ledger_heads and live review_cases are mutable caches, with audited
application transitions. A database owner can remove triggers or edit files;
this is not tamper-proof storage.

Schema version 1 uses a documented bootstrap/stamp approach instead of adding
Alembic. db init and db migrate create an empty v1 schema or verify the current
application marker, table inventory, version and stored expected schema signature.
They do not silently add tables to an existing database or mutate unknown versions.
An unrelated database, future version or mismatched signature is rejected. Future
versions require an explicit reviewed migration and tests before changing the
stamp. The stamp is not cryptographic verification of live DDL against an attacker.
Initialization idempotency, foreign keys and unknown-version refusal are tested.

## Backup, restore and reset

Backup uses sqlite3.Connection.backup rather than copying a potentially active
database file. It requires a new destination and checks SQLite integrity and
foreign keys. Restore requires a new target and verifies the application/schema.
The snapshot and audit state at backup time are preserved. CLI backup records
BACKUP_CREATED in the live database after the copy; that new event is naturally
outside the preceding backup snapshot.

Reset requires the literal confirmation RESET-SYNTHETIC-DEMO and a new mandatory
backup path. It validates the application database, takes a backup, closes local
connections, removes only the exact named database file, and initializes a fresh
schema. It never recursively deletes directories. External processes holding
the file can cause a safe failure. Tests use temporary databases, never the full
demo database. No reset was performed on the full demonstration database.

## Commands

```powershell
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 init
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 migrate
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 import --input-dir .\data\synthetic --actor 'SYNTHETIC_DEMO:student' --reason 'Import synthetic data'
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 reconcile --actor 'SYNTHETIC_DEMO:student' --reason 'Create baseline'
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 controls
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 counts
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\demo.sqlite3 backup --target .\outputs\demo-backup.sqlite3 --actor 'SYNTHETIC_DEMO:student' --reason 'Local backup'
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\restored.sqlite3 restore --backup .\outputs\demo-backup.sqlite3
```

Use --dataset-id before the subcommand when selecting among imported datasets.
Case/payment/invoice financial commands also infer scope from their explicit IDs.
See MANUAL_REVIEW_GUIDE.md, AUDIT_TRAIL.md and PHASE_4_VERIFICATION.md for workflow,
actual counts/results and limits. No Excel, dashboard or Phase 5–8 functionality
is included.
