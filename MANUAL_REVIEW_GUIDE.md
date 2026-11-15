# Local synthetic manual review

This is an explicit demonstration workflow. Actor labels such as
SYNTHETIC_DEMO:student are recorded assertions, not authenticated users or access
control. Every financial action requires that label and a nonempty reason. The
system never chooses an invoice automatically from review candidates.

## Inspect before choosing

PowerShell examples assume an imported/reconciled database; replace identifiers
and amounts with values you deliberately review. Do not blindly select the first
candidate as a normal operating rule.

```powershell
$db = '.\data\phase4-demo.sqlite3'
.\.venv\Scripts\energy-reconciliation.exe db --database $db review-list
.\.venv\Scripts\energy-reconciliation.exe db --database $db review-list --reason-code missing_reference --min-cents 100 --max-cents 50000
.\.venv\Scripts\energy-reconciliation.exe db --database $db review-list --status REOPENED --from-date 2026-11-01 --to-date 2026-11-30
$cases = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-list --reason-code missing_reference | ConvertFrom-Json
$caseId = $cases[0].id
$view = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-show --case-id $caseId | ConvertFrom-Json
$view.payment
$view.balance
$view.candidate_invoices
$view.candidate_balances
$view.source_provenance
$view.decisions
```

The queue defaults to unresolved cases; --status RESOLVED exposes closed cases.
Dates filter actual opened_at UTC calendar dates. Amount filters are integer EUR
cents from the accepted current snapshot. Candidate evidence is historical,
run-specific suggested evidence; candidate_balances shows current eligible debt.
Candidates are not exhaustive and never authorize a match. Original payment
claims remain unchanged even if an operator explicitly establishes attribution.

Case version protects against another operator changing the case; ledger revision
protects against any intervening financial state change. Both are shown by
review-show/list. A stale token fails without changing money. Refresh the view and
review the changed facts before deliberately retrying.

## Status transitions and notes

| From | Supported transition |
|---|---|
| OPEN | IN_REVIEW, or RESOLVED after accepted financial resolution |
| IN_REVIEW | OPEN, or RESOLVED after accepted financial resolution |
| RESOLVED | REOPENED by an explicit undo or a new accepted snapshot with remaining review cash |
| REOPENED | OPEN/IN_REVIEW, or RESOLVED by accepted resolution |

```powershell
.\.venv\Scripts\energy-reconciliation.exe db --database $db review-state --case-id $caseId --case-version $view.case.version --status IN_REVIEW --actor 'SYNTHETIC_DEMO:student' --reason 'Start examining evidence'
$view = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-show --case-id $caseId | ConvertFrom-Json
.\.venv\Scripts\energy-reconciliation.exe db --database $db review-defer --case-id $caseId --case-version $view.case.version --ledger-revision $view.ledger_revision --actor 'SYNTHETIC_DEMO:student' --reason 'Further evidence required' --note 'Leave the cash unapplied'
```

Defer records an immutable decision/note and leaves the case unresolved. Status
commands cannot simply mark cash resolved or manually reopen a closed financial
case without an accepted action. Partial manual allocations retain an IN_REVIEW
case until all of that receipt's remaining cash has a valid disposition.

## Explicit allocation and undo

Targets must be eligible open invoices on one account. A confirmed existing
account attribution cannot be switched silently. For unmatched cash, explicit
operator targets establish attribution without editing the source account claim.
Allocated sum must not exceed available effective cash or any target's open debt.

After reviewing evidence, replace the placeholder below and choose integer cents:

```powershell
$invoiceId = 'REPLACE_WITH_REVIEWED_SYN_INVOICE_ID'
$amountCents = 100
$view = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-show --case-id $caseId | ConvertFrom-Json
$decision = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-allocate --case-id $caseId --case-version $view.case.version --ledger-revision $view.ledger_revision --target "${invoiceId}:$amountCents" --actor 'SYNTHETIC_DEMO:student' --reason 'Invoice explicitly verified from synthetic evidence' --note 'Document the basis here' --request-id 'review-example-001' | ConvertFrom-Json
```

Repeat --target INVOICE_ID:CENTS for a deliberate multi-invoice split. Duplicate
targets, float money, cross-account targets and over-allocation are rejected.
No fuzzy/reference/amount heuristic fills in omitted targets.

Optional request IDs make an identical retried intent idempotent, even if its
old revision token is now stale because the first request succeeded. Reusing the
request ID for a different actor/reason/note/target intent is rejected.

```powershell
$view = .\.venv\Scripts\energy-reconciliation.exe db --database $db review-show --case-id $caseId | ConvertFrom-Json
.\.venv\Scripts\energy-reconciliation.exe db --database $db decision-reverse --decision-id $decision.decision_id --case-version $view.case.version --ledger-revision $view.ledger_revision --actor 'SYNTHETIC_DEMO:student' --reason 'Original manual selection was incorrect' --request-id 'review-example-001-undo'
```

Undo adds a new decision and linked allocation releases. Nothing is deleted or
overwritten. A fully resolved case reopens. An already undone decision cannot be
undone again. If later cash handling released part of the allocation, an unsafe
full undo is rejected; dependent financial actions require review. Undo entries
themselves are not an unlimited chain of reversible edits.

## Corrections and synthetic outflows

All such actions occur on the current ledger evaluation date with actual UTC
approval/knowledge timestamps. They are restatements of this synthetic snapshot,
not instructions sent to a real bank. No arbitrary historical effective-date
parameter or fake banking API is provided.

```powershell
$ledger = .\.venv\Scripts\energy-reconciliation.exe db --database $db controls | ConvertFrom-Json
.\.venv\Scripts\energy-reconciliation.exe db --database $db correct-invoice --invoice-id $invoiceId --amount-cents -100 --ledger-revision $ledger.ledger.revision --actor 'SYNTHETIC_DEMO:student' --reason 'Approved synthetic receivable reduction' --request-id 'correction-example-001'
```

Positive correction cents increase receivables; negative cents reduce them. Cash
does not change. A reduction below active applications is rejected. Correction
undo records a separate equal-opposite correction linked to its original.

```powershell
$paymentId = 'REPLACE_WITH_REVIEWED_SYN_PAYMENT_ID'
$ledger = .\.venv\Scripts\energy-reconciliation.exe db --database $db controls | ConvertFrom-Json
.\.venv\Scripts\energy-reconciliation.exe db --database $db cash-outflow --payment-id $paymentId --kind refund --amount-cents 100 --bank-event-id 'SYN-LOCAL-REFUND-001' --ledger-revision $ledger.ledger.revision --actor 'SYNTHETIC_DEMO:student' --reason 'Explicit synthetic credit refund' --request-id 'refund-example-001'
```

Outflows have positive magnitudes, consume unapplied cash first, and cannot
exceed the original effective receipt. Releases are linked to their actual
reversal. A unique release or a full release vector can be determined safely;
an ambiguous partial multi-allocation outflow needs explicit
--release ALLOCATION_ID:CENTS entries. Release signatures preserve that exact
payment/invoice/amount/date basis across automatic snapshot IDs; a changed basis
is rejected rather than guessed. Synthetic local outflows use a distinct source
system and unique bank-event identity.

Bank cash is immutable. decision-reverse does not erase a refund or chargeback;
real recovered cash would be a new imported receipt. Automatic reposting or
changing an old cash release plan is unsupported. This is a deliberate safety
limit, not permission to fabricate balancing cash.

## Later reconciliation and historical runs

```powershell
.\.venv\Scripts\energy-reconciliation.exe db --database $db reconcile --actor 'SYNTHETIC_DEMO:student' --reason 'Reconcile while preserving valid manual decisions'
.\.venv\Scripts\energy-reconciliation.exe db --database $db reconcile --evaluation-date 2025-01-15 --known-at 2025-01-31T12:00:00Z --historical --actor 'SYNTHETIC_DEMO:student' --reason 'Historical source-knowledge snapshot'
```

Reconciliation defaults to the current accepted cutoffs, so an unchanged rerun
does not silently advance time or erase decisions. Older cutoffs require
--historical and do not move the current head or rewrite live review statuses.
Use db controls --run-id ID to inspect any stored financial snapshot.

If a new import conflicts with an active manual action, candidate activation
rolls back. The old decision and ledger remain accepted. Explicit decision undo
on that last accepted source is supported before retrying the pending import.
No automatic override is allowed. Complex incompatible cash-plan rebases remain
blocked for review; this phase does not invent compensating bank events.

See DATABASE_ARCHITECTURE.md for transaction boundaries, AUDIT_TRAIL.md for
history queries, and PHASE_4_VERIFICATION.md for actual executed demonstrations.
