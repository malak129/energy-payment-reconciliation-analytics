# Financial payment reconciliation — rules reconciliation-1.0.0

SYNTHETIC portfolio simulation. Phase 3 implements strict generated-source
ingestion and a deterministic in-memory reconciliation snapshot. Phase 4 wraps
this same engine with SQL persistence and explicit database-backed manual
decisions. Phases 5 and 6 now provide persisted Excel reporting and a local
Streamlit dashboard; the automatic engine itself remains unchanged.
BUSINESS_RULES.md remains the financial contract; this document makes its
operational choices explicit. Original invoices, payments and source files are
never overwritten.

The standalone Phase 3 command and automatic baseline output remain compatible.
The persistence service reconstructs imported inputs from SQLite, runs this
engine, then validates eligible operator effects over one baseline. Immutable
ENGINE and LEDGER snapshots have explicit allocation/release memberships;
historical rows must never be summed as current cash. See
DATABASE_ARCHITECTURE.md for activation, knowledge cutoffs and conflict rollback,
and MANUAL_REVIEW_GUIDE.md for explicit allocation/undo. Result types now also
accept MANUAL-1 evidence and manually_matched classification without changing
automatic output. The Phase 2 oracle evaluator accepts automatic baselines only;
operator judgments require their own audit evidence.

## Run from Windows PowerShell

Install the project as described in README.md, then run from repository root:

```powershell
.\.venv\Scripts\energy-reconciliation.exe reconcile --help
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir .\data\synthetic --output-dir .\outputs\reconciliation --evaluation-date 2026-03-01
```

The default input/output paths are those above. Without evaluation date, the
command uses Dataset.effective_at's calendar date, not the current computer date
or the oracle. Without known_at, it uses evaluation day end in UTC.

```powershell
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir .\data\synthetic --output-dir .\outputs\historical --evaluation-date 2025-01-15 --known-at 2025-01-31T12:00:00Z
```

The command prints a control summary and produces:

| File | Contents |
|---|---|
| reconciliation.json | Typed run, source hashes, allocations, releases, evidence, adjustment effects, payment/invoice outcomes, exceptions, review queue and controls |
| review_queue.json | Pending manual items, each with subject, reason, remaining amount, explanation and candidates |
| source_provenance.jsonl | Every source record occurrence, including duplicates, original text cells, location and canonical payload fingerprint |
| summary.md | Human-readable financial controls, classifications and exception counts |

Money is integer EUR cents in machine-readable results. CLI exit 0 means a valid
snapshot was produced; unresolved review items do not make a run invalid. Exit 1
means critical input or financial validation failed. Identical output reruns are
no-ops after byte comparison. Different existing contents are refused: choose
another output directory. Outputs are staged before publication and ignored by Git.

## Architecture and input contract

`ingestion/csv_dataset.py` reads the actual fourteen Phase 2 input CSVs and
manifest-listed statement receipts. It uses existing Pydantic record schemas;
there is no competing Invoice or Payment model. `reconciliation/engine.py`
accepts an InputDataset and RunOptions and returns a ReconciliationResult.
`reconciliation/export.py` serializes it. `evaluation.py` is separate and opt-in.
The runtime engine and source adapter import no generation or oracle code.

The adapter is deliberately specific to generated Phase 2 CSV/statement schemas,
not a generic bank-format or XLSX importer. It enforces canonical contained paths
under inputs/ and statement_fixtures/, CSV headers, required fields, literal
synthetic flags, EUR, ISO dates and integer money text. Float amounts, duplicate
headers, malformed records and unknown columns fail with source context.

File checksums are verified for every operational input and statement file.
The Dataset's core business content fingerprint is recomputed. Foreign keys,
unique IDs/source keys, normalized invoice references, line totals, account
dates, outflow limits, approval links and audit target/payload hashes are checked.
Invalid future-dated records also fail validation rather than disappearing from
an earlier-cutoff run. Checksums detect inconsistency; they are not signatures.

Bank identity is `(dataset_id, source_system, bank_event_id)`, shared across
Payment and Reversal. Equal identity and equal canonical record is a duplicate;
changed payload or ID for that identity is a fatal conflict. Distinct event IDs
with equal dates/amounts remain distinct cash. Raw statement records must agree
with canonical payment/reversal tables and accepted-row provenance. Receipt
outcomes are determined from actual hashes, not trusted from expected_outcome.

All repeated representations are retained in source_provenance.jsonl. Normalized
model values are used for rules, while original CSV cells and files remain
available. Provenance row_number counts CSV records including the header;
ImportRow.row_number counts data records only. Raw statements are alternative
representations, never additional cash. Evaluation paths, hashes of evaluation
file contents and manifest oracle summaries are not used for matching.

## Time, ordering and knowledge

Two independent cutoffs apply:

- evaluation_date: inclusive business date for invoices, effective corrections,
  receipts and outflows.
- known_at: an offset-aware timestamp normalized to UTC, controlling which source
  information is available to the snapshot.

Phase 2 has no separate invoice receipt timestamp. The explicit availability
assumption is therefore invoice issue date at 00:00 UTC. Bank events become known
at their earliest validated statement imported_at. Corrections require the
correction, case, decision and any associated audit evidence to be known; the
latest of their timestamps controls availability. The fixture authoring run's
final completion date is not used to conceal its individual dated approvals.
True historical invoice ingestion times require future source metadata.

Eligible events are replayed by business date. On the same date the order is
invoice issuance, corrections (original before its undo), receipts, then outflows;
stable IDs break ties. No intraday bank ordering is inferred from dates. Late
known backdated evidence restates a new snapshot rather than modifying the old
one. No future invoice is applied to an earlier receipt, and no payment is
automatically retried after later invoice issuance or reopening.

The in-memory API rejects a known outflow whose parent is not known/effective at
the requested cutoffs. It cannot invent an opening cash balance. Invalid authority
and a correction reducing face value below active allocations fail clearly; the
latter needs an explicit approved release plan from the Phase 4 manual workflow.

## Matching hierarchy and evidence

Normalization strips outer whitespace and changes case only. Internal spaces,
punctuation and leading zeros are preserved. There is no fuzzy matching.

| Rule | Preconditions | Financial effect |
|---|---|---|
| REF-SINGLE-1 | Unique normalized reference, invoice issued and not cancelled, same EUR account or a missing claim inferred from the unique reference | Allocate min(receipt available, invoice open); residual stays cash |
| REF-COMBINED-1 | Explicit references separated by a literal pipe, each unique, same account, every target open, receipt equals total open balance | Apply each exact open amount; mismatch allocates nothing |
| Review only | Missing/unknown reference, account conflict, malformed/duplicate reference list or uncertain split | No allocation; provide candidate evidence |

Names, amounts and shared customer identity never authorize a match. An account
claim may restrict candidate lists but is not validated cash attribution until
explicit references establish the relationship. A matching reference may infer
the account if the original claim is missing. A conflicting account claim always
goes to review, even if both contracts belong to the same customer.

Every Allocation uses the original model and has one MatchEvidence record with
rule ID, reason code, original validated reference text, normalized invoice
reference, account-evidence kind and explanation. Original untrimmed text is
retained separately in provenance. Confidence is exact, never a probability.

Multiple receipts can settle one invoice over time. Single exact references can
partially settle invoices. Extra receipts against an already settled, still-valid
invoice become verified account credit rather than negative receivables. Explicit
combined references with a short/excess total or any closed target do not get an
invented split.

## Reversals and corrections

Positive Payment magnitudes increase cash. Positive Reversal magnitudes decrease
cash once. Outflows use unapplied cash first. If one active allocation must be
released, the engine emits an AllocationRelease linked to that original allocation
and reversal. A full withdrawal requiring all remaining allocations has a unique
release vector and may release every one; a partial withdrawal with several
possible invoice releases is ambiguous.

For that ambiguous case, provisional simulation is discarded and replayed with
the affected payment held entirely out of automatic allocation. Its linked
outflows are still cash, its remaining net cash stays unapplied, and candidates
are placed in manual review. Holds grow monotonically, so replay terminates.
No persisted ledger entries are undone by this procedure: Phase 3 produces an
independent snapshot and has not committed any provisional allocation. This
conservative hold is not an instruction to rewrite a persisted ledger. Phase 4
validates explicit operator effects over the selected baseline and preserves
historical membership; incompatible activation fails atomically.

Corrections affect receivables only and retain their supplied approval and reason.
One correction approval cannot be reused as a second correction. Undo entries
must be equal and opposite, on the same invoice, reference one non-undo original,
occur no earlier, and undo it at most once. Unknown originals cannot be undone in
a historical snapshot. Manual payment decisions are not silently ignored: the
adapter currently accepts only correction approvals; executing payment-resolution
decisions is implemented separately by the Phase 4 persistence service.

AdjustmentEffect records make cash and debt signs explicit. A refund of excess
cash does not release debt allocations; a chargeback may reopen debt through a
release. Original invoices, invoice items and transactions remain unchanged.

## Statuses, exceptions and transitions

Payment allocation status and invoice settlement status are separate projections.
The legal balance-derived transitions in BUSINESS_RULES.md are preserved.

| Projection | Meaning |
|---|---|
| Payment allocated | All remaining effective cash is applied; its invoice can still be partly unpaid |
| Payment partial | Some effective cash is applied and residual cash remains |
| Payment unapplied | No active application and effective cash remains |
| Payment reversed | Effective cash is zero after full outflows |
| matched classification | Receipt automatically applied through explicit evidence |
| partial_payment classification | Receipt was smaller than its invoice's open balance at processing time; later receipts may settle that invoice |
| overpaid classification | Verified residual account credit; includes a receipt against an already settled invoice |
| adjusted classification | Positive cash remains applied after a linked outflow |
| ambiguous / manual_review | Event lacks safe allocation evidence or is held for reversal resolution |
| Invoice open / partial / settled / cancelled | Derived from adjusted face versus active applications |

Invoice adjusted and overdue are independent flags. Payment late/cross_month
flags describe evidenced invoice relationships; they are null when no allocation
relationship establishes the dates. Fully reversed payments still retain their
original allocation evidence and release history.

| Exception reason | Handling |
|---|---|
| missing_reference | Pending payment review, no automatic application |
| unknown_reference | No valid exact reference; candidates are review-only |
| ambiguous | Several plausible equal open candidates or malformed/repeated reference tokens; no selection |
| account_mismatch | Explicit references conflict with account evidence |
| invoice_not_open | Invoice not issued at receipt date or cancelled |
| combined_amount_mismatch | Explicit multi-invoice amount does not equal positive open sum |
| reversal_conflict | Several partial-release choices; payment held during snapshot replay |
| overpayment | Verified residual cash needing a disposition decision |
| amount_mismatch | Informational: fully applied short receipt still leaves invoice debt |
| outstanding_invoice | Informational open receivable; does not identify matching cash |

Only requires_manual_review=true items appear in review_queue.json. The full
exception list also retains informational invoice balances and partial-payment
discrepancies. Partial-payment notices disappear if subsequent receipts settle
their invoice. Excess-refund notices disappear once no residual cash remains.
Candidates show the processing-time open balances, not an allocation instruction.

## Financial controls and counts

All totals are Python integers; aggregate sums have no SQLite integer limitation.
Each application is capped by invoice debt and effective payment cash. Releases
cannot exceed the original allocation. Approved negative corrections cannot
produce a negative receivable. Bounds are checked during replay and at closing.

```text
G = original issued invoices + signed approved corrections
N = gross incoming payments - refunds - chargebacks
A = allocations - allocation releases
U = N - A                       (unapplied cash)
O = G - A                       (outstanding receivables)
N - A - U = 0
G - A - O = 0
G - N = O - U
identified customer credit + unidentified suspense = U
```

All quantities use both cutoffs. Source_counts explain excluded records. The
adapter validates all original records even if an event is outside those cutoffs.
Matched event count means payments with positive active applications. Unmatched
event count means positive remaining cash and no active application; reversed
events are separate. A matched overpayment can still be in manual review for
its residual. Financial control equations are conservation identities, not
collection rates, matching precision or other business-performance KPIs.

## Reproducibility and integrity

Run identity combines rules version, cutoffs, source manifest/file hashes,
validated record fingerprints and bank availability. Allocations, releases,
evidence and projections have deterministic UUID5 identifiers under that run.
The result hash covers canonical JSON excluding run metadata to avoid recursion.
All exported business arrays have stable ordering. Different output directories,
equivalent UTC offsets and different Python hash seeds do not change output.

Run started_at and completed_at use known_at as deterministic logical snapshot
timestamps, not a fabricated measurement of actual execution duration. Results
are immutable independent snapshots. They must not be merged into a persisted
ledger by summing allocations across snapshots; Phase 4 implements idempotency
and snapshot/ledger relationships as documented in DATABASE_ARCHITECTURE.md.

## Separate evaluation

Only the explicit evaluation command/test harness reads ground truth:

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.evaluation --result .\outputs\reconciliation\reconciliation.json --ground-truth .\data\synthetic\evaluation\ground_truth.json --output-dir .\outputs\evaluation
```

It validates the result fingerprint, dataset identity and evaluation date. Correct
automatic allocations compare exact (payment, invoice, cents, effective date)
multisets, independently of oracle/run-specific allocation IDs. Releases are
compared through their payment/invoice/reversal links. Precision divides correct
allocations by produced allocations; expected-allocation coverage divides by
expected allocations. Empty denominators are null. All-payment coverage is
reported separately, including an explicit distinction between ever matched and
currently actively applied payments. Percentages use Decimal, not binary floats.

Per-invoice outstanding and per-payment unapplied differences are reported, not
hidden behind net totals. Reason-label differences are also reported. The oracle
assumes full source knowledge; historical known_at snapshots may legitimately
differ. The runtime never reads oracle files or forces balances to oracle values.

## Verification and limits

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

PHASE_3_VERIFICATION.md records actual default-data results, evaluation metrics
and tests for the original automatic engine. Its limits remain synthetic CSV
formats, assumed invoice availability and date-level event ordering. The engine
itself remains pure and in-memory; Phase 4 adds SQLite snapshots and an explicit
manual resolution service around it. See PHASE_4_VERIFICATION.md for those
results and limits. There is no certified accounting/banking integration,
production UI. The implemented local demonstration UI is documented in
DASHBOARD_USER_GUIDE.md; Excel reporting is documented in EXCEL_REPORTING_GUIDE.md.
