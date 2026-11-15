# Phase 4 verification — 2026-11-14

**Implemented and verified: SQLite persistence, manual review workflows and
application-level financial audit history.** Phases 5–8 were not started.
All amounts below concern synthetic data. This is not a certified ledger,
bank integration, authentication system or production financial service.

## Environment and checks actually executed

Existing `.venv` was reused: Python 3.12.14, SQLite 3.53.1. SQLAlchemy was
already a project dependency; no additional dependency or service was needed.

| Check | Actual result |
|---|---|
| Full pytest suite, final code | **188 passed in 72.67s**, 0 failed |
| Previous tests | All 155 preserved and passing |
| New persistence/workflow cases | 33 passing, using temporary databases |
| Ruff lint | `All checks passed!` |
| Ruff format | `48 files already formatted` |
| CLI database help | Exit 0, all persistence subcommands listed |
| Doctor with example TOML | Exit 0; dependencies and every package module import |
| pip check | `No broken requirements found.` |
| Full default-data database demo | Exit 0; actual report saved below |
| Primary, backup and restored database integrity | Each `integrity_check = ok`; zero foreign-key violations |
| Original source files | All 33 manifest file hashes match, including ground truth |
| Git ignores | Demo database, report, backup and restored database are ignored |

The final pytest command used the approved unsandboxed test execution path
because sandbox temporary-directory restrictions interfered with test fixtures.
Test databases were temporary; tests did not reset or modify the main demo DB.
Elapsed time varies with filesystem activity; the value above is the final run.

Executed PowerShell checks from repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\energy-reconciliation.exe doctor --config .\config.example.toml
.\.venv\Scripts\energy-reconciliation.exe db --help
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\phase4-demo.sqlite3 controls
.\.venv\Scripts\energy-reconciliation.exe db --database .\data\phase4-demo.sqlite3 review-list --status REOPENED
```

The complete default dataset demo was executed with:

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.persistence.demo --input-dir data/synthetic --database data/phase4-demo.sqlite3 --report outputs/phase4-demo.json --backup outputs/phase4-demo-backup.sqlite3 --restore outputs/phase4-restored.sqlite3 --phase3-reference outputs/reconciliation/reconciliation.json
```

These destination files now exist. The demo refuses to overwrite them; choose
new names to rerun. It imports the full existing dataset, persists reconciliation,
repeats import/reconciliation, performs an explicit demonstration allocation and
undo, checks history, and backs up/restores into a new file. Operator selection
uses live payment/invoice balances, not evaluation ground truth.

A separate read-only verification script used `hashlib.sha256` for every
manifest-listed file and SQLite `PRAGMA integrity_check` / `foreign_key_check`
on all three databases. Store counts matched the demo report after those checks.

## Files created and changed

| File | Purpose |
|---|---|
| `src/energy_reconciliation/persistence/schema.py` | SQLAlchemy tables, integer checks, foreign keys, indexes and immutable-table policy |
| `src/energy_reconciliation/persistence/database.py` | SQLite connection policy, explicit transactions, version/signature checks, backup/restore and confirmed reset |
| `src/energy_reconciliation/persistence/service.py` | Immutable imports/provenance, persistent engine integration, current head, review workflow, financial decisions and queryable audit |
| `src/energy_reconciliation/persistence/overlay.py` | Validated operator effects over one automatic baseline, explicit releases, signed adjustments and controls |
| `src/energy_reconciliation/persistence/cli.py` | Database, import, reconciliation, controls, case, decision, adjustment, audit and maintenance commands |
| `src/energy_reconciliation/persistence/demo.py` | Reproducible end-to-end demonstration with new-file safeguards |
| `src/energy_reconciliation/persistence/__init__.py` | Updated package scope |
| `src/energy_reconciliation/cli.py` | Registers database subcommands; updates doctor scope |
| `src/energy_reconciliation/reconciliation/results.py` | Backward-compatible manual match evidence/classification extensions |
| `src/energy_reconciliation/evaluation.py` | Refuses to score manual judgments as automatic Phase 2 oracle matches |
| `tests/test_persistence.py` | 33 persistence/workflow unit and integration cases |
| `DATABASE_ARCHITECTURE.md` | Physical schema, transaction boundaries, source versions, historical membership, migration strategy and safety limits |
| `MANUAL_REVIEW_GUIDE.md` | Exact PowerShell workflow, filters, tokens, allocation/undo, corrections and cash outflows |
| `AUDIT_TRAIL.md` | Audit events, entity queries, transactional guarantees and traceability limits |
| `PHASE_4_VERIFICATION.md` | This actual completion evidence |
| `README.md`, `DATA_MODEL.md`, `BUSINESS_RULES.md`, `RECONCILIATION_ENGINE.md` | Updated implemented scope and links to authoritative physical architecture |

Generated local artifacts (ignored by Git): `data/phase4-demo.sqlite3`,
`outputs/phase4-demo.json`, `outputs/phase4-demo-backup.sqlite3`,
`outputs/phase4-restored.sqlite3`. Existing Phase 2/3 input and output artifacts
were reused. No reporting/dashboard implementation was added.

## Architectural decisions and compatibility

- SQLAlchemy Core with SQLite, schema version 1 and tested application marker,
  table inventory and DDL signature. Bootstrap/migrate is idempotent for v1;
  unknown schemas/versions fail rather than silently upgrading.
- Integer euro cents throughout financial calculations; UTC knowledge/audit
  timestamps and separate modeled effective dates. Original invoices and bank
  events remain immutable. Source file bytes and provenance are retained.
- Natural bank identity and canonical content distinguish duplicate occurrences
  from conflicting events. A repeated successful import records another attempt,
  not another receipt. Complete source revisions cannot omit previously accepted
  core financial records.
- Existing Phase 3 matching engine is reused. Immutable ENGINE and LEDGER runs
  explicitly select effect memberships. Only the current-head pointer is
  superseded; historical runs remain readable. Global historical allocations
  must never be summed as current balances.
- Manual decisions are explicit append-only intent with actor/reason, optional
  note, request-id retry protection and linked undo. Demonstration actors use
  `SYNTHETIC_DEMO:` labels; this does not imply authentication.
- `BEGIN IMMEDIATE` serializes writers; ledger revision and case version detect
  stale operations. Accepted financial operations atomically write effects,
  controls, snapshot, audit and head. Rejections roll back financial changes and
  can append a separate rejected-attempt audit record.
- Current operations use the ledger's effective evaluation date and actual UTC
  decision knowledge time. Historical queries cannot see future decisions.
  Historical reconciliation does not activate a head or mutate live cases.

One important replay regression was discovered and fixed: after a new source
added an automatic receipt, an already undone manual allocation could still
block replay because its cancelled intermediate leg exceeded the new debt
balance. Explicitly linked, fully reversed effects can now remain as net-zero
historical pairs during rebase. Active decisions still reject conflicting new
automatic results. A regression test proves rejection preserves the old head,
explicit undo remains possible, then the new source can be accepted. Original
financial records, decisions, releases and historical snapshots remain intact.

## Full default dataset: actual persisted counts

| Object | Count |
|---|---:|
| Customers / accounts | 500 / 600 |
| Invoices / invoice items | 7,200 / 14,400 |
| Unique bank events / payments | 7,296 / 7,100 |
| Source refunds / chargebacks | 98 / 98 |
| Source corrections | 98 |
| Statements | 13 |
| Source records / retained operational files | 37,703 / 33 |
| Source occurrences | 47,424 |
| Source versions / import batches | 1 / 2 |
| Immutable reconciliation runs / current heads | 5 / 1 |
| Review case records / manual decisions | 343 / 2 |
| Historical allocations / releases | 20,713 / 295 |
| Audit events | 22,834 |

The two import outcomes were IMPORTED and DUPLICATE for the same version.
Bank-event/payment counts did not increase on repeat import. Unchanged
reconciliation reruns reused results without creating financial effects.
Historical allocation/release row counts span independent automatic bases and
manual snapshots; they are not the current allocation count or extra cash.
Five stored runs comprise the original engine baseline and later engine/ledger
snapshots at the manual decision knowledge cutoffs.

## Financial controls and explicit allocation/undo

| Control (EUR) | Initial | After allocation | After undo |
|---|---:|---:|---:|
| Original invoice amount | 2,244,345.84 | 2,244,345.84 | 2,244,345.84 |
| Signed corrections | -2,718.72 | -2,718.72 | -2,718.72 |
| Adjusted receivables | 2,241,627.12 | 2,241,627.12 | 2,241,627.12 |
| Gross incoming cash | 2,186,839.60 | 2,186,839.60 | 2,186,839.60 |
| Refunds | 2,055.36 | 2,055.36 | 2,055.36 |
| Chargebacks | 27,899.24 | 27,899.24 | 27,899.24 |
| Net cash | 2,156,885.00 | 2,156,885.00 | 2,156,885.00 |
| Net allocated | 2,067,991.84 | 2,068,088.38 | 2,067,991.84 |
| Unapplied cash | 88,893.16 | 88,796.62 | 88,893.16 |
| Outstanding receivables | 173,635.28 | 173,538.74 | 173,635.28 |
| Identified credit | 2,198.54 | 2,198.54 | 2,198.54 |
| Suspense | 86,694.62 | 86,598.08 | 86,694.62 |
| Cash control difference | **0.00** | **0.00** | **0.00** |
| Receivable control difference | **0.00** | **0.00** | **0.00** |
| Unresolved review items | **343** | **342** | **343** |

Equations checked after accepted operations:
`net cash = gross incoming - refunds - chargebacks = net allocated + unapplied`;
`adjusted receivables = original invoices + signed corrections = net allocated + outstanding`;
`unapplied = identified credit + suspense`.

The explicit allocation was 9,654 cents (€96.54):

- Case: `syn_case_03091690223456d485830ef36e874083`
- Payment: `syn_payment_12a67b5df30c517099b264267d11f208`
- Invoice: `syn_invoice_6dc7af1e9e5b5d36bee7c4ca15ebbdd5`
- Decision: `syn_decision_fd20c5e9a4ad5abe983a0ce480454abb`
- Undo: `syn_decision_84a20bea30025bc38db99b0ad9ee05ee`

The case became RESOLVED, the allocation survived a rerun, then linked undo
made it REOPENED. Ledger revisions were 1 → 2 → 3. All final control fields,
including identified credit and suspense, equal the original values. There
were 6,904 original automatic allocations; those remained unchanged.

The selected payment's seven audit actions were CASE_OPENED,
ALLOCATION_CREATED, CASE_RESOLVED, DECISION_ALLOCATE, ALLOCATION_RELEASED,
CASE_REOPENED and DECISION_REVERSE. The original run remains queryable, and
backup/restore returned the identical current result and counts.

## Reproducibility and immutable source evidence

Original Phase 3 result and database baseline compare equal as complete objects:

```text
Initial run: syn_run_436fba1b4ac450509c106860174a7b9a
Initial result SHA-256: 53b25d2dd1ced153f6906b81c6fa3ff1410eda5847829a44d515cfd2adb96a3b
Final run: syn_run_ae2627073bcf54c99653455cb75264ae
Final result SHA-256: db6b3f55a6819a59f47d2ed328a146be0ee1c273d96ca6c2880e17909a583437
Source manifest SHA-256: 5dd4f19dfd45050a38c52ef4bd337a8fed75f9fc35cbf667754ca29df8265e94
Ground-truth SHA-256: d5d0310d2cd791bd1abc59bf5d828faa7835df5bc8a7d1519f5630c22989637f
```

Final result identity differs because it records operator allocation/release
history and later knowledge time. Financial balances return exactly. The
oracle was only hashed by the separate verification check; normal persistence,
matching, manual workflow and demo do not consume it.

## Test coverage and acceptance

New tests cover schema/FK/check constraints, immutability, version mismatch,
duplicate/overlapping statements, conflicting identities, partial-import rollback,
DB-only reconstruction, repeat reconciliation, explicit/split allocation and undo,
defer/state transitions, idempotency keys, stale/two-writer operations, failed
financial-write rollback, source history, historical cutoffs, correction/undo,
refund/chargeback cash and explicit releases, audit references, backup/restore,
reset confirmation and the complete demo on a small temporary dataset.

All Phase 4 acceptance criteria pass for the documented supported synthetic
workflow: prior and new tests, Ruff, idempotency, persistent reversible manual
decisions, immutable historical traceability, zero control differences, explicit
ambiguous-case handling, preserved originals and the full-data demo.

## Known limitations

- Import supports complete existing generated bundles and overlapping statement
  fixtures within them, not arbitrary bank deltas, XLSX or external formats.
- Schema version 1 has tested bootstrap/version validation; no speculative future
  migrations exist. Unknown schemas require an explicit future migration.
- Local demonstration actors are labels, not permissions or authenticated users.
  SQLite triggers/application policy are not a tamper-proof audit boundary.
- Manual posting uses the accepted evaluation date, not arbitrary retroactive
  dates. Actual operator knowledge timestamps differ from modeled source receipt
  times by design. New automatic source results must remain compatible with
  active decisions; otherwise activation rolls back for explicit review/undo.
- Refunds/chargebacks are immutable cash events, not erasable manual allocations.
  Ambiguous partial releases require explicit plans. Unsupported rebase plans
  or corrections requiring unprovided allocation releases fail safely.
- Rejected-attempt auditing is application-level, not every possible parser,
  process-crash or raw SQL failure. Backup is a point-in-time SQLite copy; CLI
  completion audit occurs after that copy. DB commits and optional JSON exports
  are not a distributed atomic transaction.
- No posted general ledger, certified accounting compliance, Excel reporting,
  dashboard, external authentication or Phases 5–8 functionality is claimed.

Phase 4 is complete within these explicit boundaries. Stopped for user approval
before Phase 5.
