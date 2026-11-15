# Application audit trail

The audit trail is local application traceability for SYNTHETIC data. It is not
tamper-proof, authenticated, legally certified or a production accounting log.
A database owner can remove SQL triggers or alter database files. SHA-256
fingerprints are integrity/reproducibility evidence, not digital signatures.

## Event content

audit_events stores immutable event ID, actual UTC timestamp, explicit local
demo actor, action, entity type/ID, reason and structured JSON details. Optional
foreign keys link dataset, reconciliation run, payment, invoice and account.
All events carry the synthetic marker. Queries expose SQLite's append row order
as sequence, preserving operation order even when timestamps are equal.

Accepted financial changes and their audit events commit together in one
BEGIN IMMEDIATE transaction. Failure rolls back all financial writes and may
append a separate *_REJECTED event afterward. Unknown entity references remain
in details instead of violating foreign keys. Validation/parser failures before
a financial operation need not create a successful transaction or partial run.

| Event family | Evidence |
|---|---|
| IMPORT_IMPORTED / IMPORT_DUPLICATE | Batch/source version, actor, reason, unique cash and duplicate representation counts |
| RECONCILIATION_COMPLETED | Run ID, historical/current flag, controls; repeat attempts reuse immutable results |
| SNAPSHOT_ACTIVATED | New revision and superseded run; earlier result remains readable |
| CASE_OPENED / CASE_IN_REVIEW / CASE_RESOLVED / CASE_REOPENED / CASE_OPEN / CASE_TOUCHED | State/version changes and explicit reasons |
| REVIEW_NOTE / REVIEW_DEFERRED | Operator explanation without falsely resolving cash |
| DECISION_ALLOCATE / DECISION_REVERSE / DECISION_CORRECTION / DECISION_REFUND / DECISION_CHARGEBACK | Explicit intent, linked effects, reason, note and revision |
| ALLOCATION_CREATED | Amount, payment, invoice, account, run and optional manual decision |
| ALLOCATION_RELEASED | Original allocation, cents, reversal/decision authority and related entities |
| CORRECTION_HANDLED / REFUND_HANDLED / CHARGEBACK_HANDLED | Signed debt/cash effect and source linkage within a particular snapshot |
| *_REJECTED | Rejected attempted operation and explanation; no successful financial posting implied |
| BACKUP_CREATED / DEMO_RESET | CLI backup/reset activity; reset's prior history remains in mandatory backup |

Snapshot adjustment events describe that run's projection of an effect. Repeated
independent snapshots can reference the same source adjustment; that does not
mean repeated bank cash. Likewise historical allocation rows must never be
summed without run membership. Financial controls come from one accepted run.

Imported Phase 2 audit/approval fixtures are preserved as original source
records, separate from runtime audit_events. Their fictional historical actors
are not presented as authenticated users who operated the local application.

## Query history

From repository root in Windows PowerShell:

```powershell
$db = '.\data\phase4-demo.sqlite3'
.\.venv\Scripts\energy-reconciliation.exe db --database $db audit
.\.venv\Scripts\energy-reconciliation.exe db --database $db audit --payment-id 'REPLACE_WITH_SYN_PAYMENT_ID'
.\.venv\Scripts\energy-reconciliation.exe db --database $db audit --invoice-id 'REPLACE_WITH_SYN_INVOICE_ID'
.\.venv\Scripts\energy-reconciliation.exe db --database $db audit --account-id 'REPLACE_WITH_SYN_ACCOUNT_ID'
.\.venv\Scripts\energy-reconciliation.exe db --database $db audit --run-id 'REPLACE_WITH_SYN_RUN_ID'
```

Allocation/release events provide per-invoice/account links even for multi-invoice
decisions. Their structured details link the decision ID. Review inspection
shows prior case decisions and original source provenance; immutable stored runs
provide the surrounding financial state. audit supports a dataset filter via
the db --dataset-id option. Filters return matching events, not a fabricated
full historical balance calculation.

## Backup and retention

The SQLite backup API captures a consistent point-in-time database, including
source bytes, run JSON, effect membership, decisions and audit history. Restore
uses a new file and verifies application schema. An audit event written after
a backup is naturally not part of the preceding copy. The lower-level backup
utility has no financial side effect; the explicit CLI also records its action.

Normal commands cannot update/delete source, effect, decision, run or audit
rows. A full demo reset is the sole destructive workflow and requires the exact
confirmation token plus a new backup destination. It creates a new empty database;
the old database's complete history is retained in that backup. No recursive
directory deletion is used. Reset is tested only on temporary test databases.

No retention deletion, signing service, identity provider, encryption-at-rest
system or regulated-accounting certification is claimed in this phase.
