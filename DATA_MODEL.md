# Data model — version 1

This is a SYNTHETIC portfolio simulation. Phase 1 provides immutable Pydantic
record contracts in `src/energy_reconciliation/models/records.py`. The tables,
foreign keys, indexes, transactions and cross-record checks below describe the
original domain design. Phase 4 now implements the SQLite projection in
[DATABASE_ARCHITECTURE.md](DATABASE_ARCHITECTURE.md). That document is the
authoritative physical table map; domain entities do not each map one-to-one to
tables. Original imported record contracts remain unchanged.

## Conventions and boundaries

Every entity has `id` (primary key, `syn_` identifier), `synthetic` (required literal
true), and `schema_version` (literal `1`). No real personal or bank data is allowed.
Every imported entity additionally has `dataset_id` (FK Dataset) and
`source_record_id` (nonempty external key); unique `(dataset_id, entity type,
source_record_id)`. Text is stripped, nonempty, and at most 500 characters unless
a narrower pattern applies. Unknown fields are rejected. Records are frozen.
All fields are required unless explicitly optional or defaulted below or in code.
The synthetic flag accepts only boolean true, not numeric 1. Timestamps are
normalized to UTC during record validation.

Pydantic validates individual records, types, ranges, date ordering and local
arithmetic. It does not verify foreign keys, identity collisions, invoice line
sums, allocation availability, synthetic-name authenticity or decision authority.
Those require complete-dataset checks; Phase 3 now validates generated CSV input
and enforces its in-memory matching/allocation invariants. Phase 4 adds immutable
file bytes/hashes and record provenance, database foreign keys and transactional
financial validation. General XLSX ingestion remains unimplemented. Phase 2 validates and exports
generated batches, and Phase 3 consumes their existing schemas. Record
validation can be called with `Invoice.model_validate(row)`.
Canonical monetary fields require Python integers, not CSV strings: future file
adapters must parse decimal text explicitly before validating records.

## Entity dictionary

Common fields above are omitted from the following table. `?` means optional
(default null); tuples default to empty. IDs ending `_id` are foreign keys to the
named entity except AuditEvent's polymorphic target. Monetary values are cents.

| Entity / purpose | Additional fields | Planned constraints and indexes |
|---|---|---|
| Dataset / reproducible input manifest | generator_version, seed (nonnegative int), config_sha256, content_sha256, effective_at | SHA-256 lowercase 64 hex; unique content hash + generator/config version |
| Customer / fictional billed party | imported fields; display_name, customer_type=private (private/small_business) | Names must use `Synthetic Customer` prefix in generated datasets |
| Account / one utility contract | imported fields; customer_id, contract_reference, energy_type=electricity (electricity/gas), opened_on, closed_on?, currency=EUR, synthetic_iban | unique contract_reference within dataset; index customer_id; closed >= opened |
| Invoice / issued receivable | imported fields; account_id, reference, issued_on, due_on, service_start, service_end, amount_cents, currency=EUR | positive total; due >= issue, service_end >= service_start; unique (dataset_id, reference); index (account_id, due_on) |
| InvoiceLine / explainable gross total | imported fields; invoice_id, line_number (positive int), description, net_cents, tax_cents, gross_cents | signed amounts, net + tax = gross; unique (invoice_id, line_number); sum gross = invoice amount |
| BankStatementImport / file receipt | dataset_id, source_system, file_sha256, filename, imported_at, row_count (nonnegative int) | unique (dataset_id, source_system, file_sha256); filenames are metadata, never executable paths |
| ImportRow / row-level provenance | import_id, row_number (positive int), payload_sha256, outcome, record_id?, reason | outcome accepted/duplicate/rejected/conflict; accepted/duplicate require record_id; unique (import_id, row_number); record_id links polymorphically to imported entity, checked by service |
| Payment / original incoming cash | imported fields; source_system, bank_event_id, booked_on, value_on, amount_cents, currency=EUR, account_id?, reference? | positive amount; claimed account is untrusted; unique (dataset_id, source_system, bank_event_id) across both payments and reversals; index booked_on |
| Reversal / refund or chargeback cash outflow | imported fields; source_system, bank_event_id, payment_id, kind, amount_cents, booked_on, value_on, currency=EUR, reason | kind refund/chargeback; positive magnitude; same account/dataset/currency as parent; shared bank event uniqueness; index payment_id, booked_on |
| ReconciliationRun / versioned attempt | dataset_id, input_sha256, result_sha256?, rules_version, config_sha256, as_of, known_at, started_at, completed_at?, status | running/completed/failed; known_at <= started_at; completed_at required for terminal status and >= started_at; result hash required only on completed runs; index dataset_id/as_of; immutable terminal snapshot |
| Allocation / application of cash to debt | payment_id, invoice_id, run_id, decision_id?, amount_cents, effective_on, created_at, reason_code, confidence | positive; reason exact_reference/explicit_combined/manual_approved, confidence exact/manual; manual requires decision; index payment_id/invoice_id/run_id; deterministic idempotency key |
| AllocationRelease / undo application without undoing cash | allocation_id, reversal_id?, decision_id?, amount_cents, effective_on, created_at, reason | exactly one reversal or manual decision; positive; cumulative releases <= original allocation; index allocation_id |
| Correction / receivable adjustment | invoice_id, decision_id, amount_cents, effective_on, created_at, reason, reverses_correction_id? | signed nonzero; + increases debt, - reduces it; correcting a correction requires equal opposite amount and same invoice; unique reverses_correction_id when non-null |
| ReviewCase / immutable exception snapshot | payment_id?, invoice_id?, run_id, candidate_invoice_ids (tuple), reason_code, reason, created_at | exactly one subject; invoice subject iff reason invoice_correction; payment reasons missing_reference/ambiguous/unknown_reference/amount_mismatch/account_mismatch/overpayment/reversal_conflict; unique (run_id, subject, reason_code); unique candidates stored as ReviewCandidate join rows in SQL |
| ManualDecision / explicit operator intent | case_id, action, actor, reason, created_at, supersedes_decision_id?, resolved_account_id? | allocate/release/correct_invoice/leave_unapplied/reject; optional resolved_account_id FK Account for cash attribution; decision history append-only; supersession same case, no branching/cycles; indexes case_id/created_at |
| AuditEvent / evidence of accepted operations | entity_type, entity_id, action, actor, occurred_at, payload_sha256, run_id? | application validates target type/ID; indexes (entity_type, entity_id), occurred_at; append-only; hash is a checksum, not tamper-proof security |
| OperatorInvoice / optional supplier demonstration | imported fields; operator_code, reference, issued_on, due_on, net_cents, tax_cents, gross_cents, currency=EUR | operator_code starts SYN_OPERATOR_; net + tax = gross > 0, due >= issue; unique (dataset_id, operator_code, reference); excluded from customer cash controls |

Manual allocations enforce reason/confidence/decision consistency in Pydantic.
ManualDecision records intent; its exact amounts and targets are linked immutable
Allocation, AllocationRelease or Correction effects, committed together. No
unexecuted decision is considered resolved. ReconciliationRun is a frozen value
object. Phase 4 stores completed immutable snapshots and audits failed attempts
separately; it does not mutate running run rows into completed rows.

The original ReviewCandidate join-table design is implemented as immutable
run-specific case_evidence payloads, with live candidate balances computed from
the selected ledger. Optional operator invoices remain domain contracts only.
Implemented SQL projections have monetary/currency checks and FK indexes;
foreign keys are enabled on every connection, with no ledger cascade deletion.
The shared bank_events registry enforces unique
`(dataset_id, source_system, bank_event_id)` across payments and reversals. Its
actual fields and child FKs are defined in persistence/schema.py. Registry,
original event, provenance and accepted import audit commit together. This
identity registry is not an additional cash transaction. See the physical map in
DATABASE_ARCHITECTURE.md for exact differences from the original logical design.

## Relationships

Dataset owns imported customer/account/invoice/payment records and import files.
Customer 1:N Account; Account 1:N Invoice; Invoice 1:N InvoiceLine.
Payment M:N Invoice through Allocation. Allocation 1:N AllocationRelease.
Payment 1:N Reversal. Invoice 1:N Correction. ReconciliationRun 1:N Allocation and
ReviewCase. ReviewCase 1:N ManualDecision and M:N Invoice through ReviewCandidate.
Decision effects link back through allocation/release/correction decision_id.
File 1:N ImportRow; repeated imports can point at the same original entity.
AuditEvent references any entity through validated type + ID.

## Money

EUR only. Store integer cents within +/-9,000,000,000,000,000, below signed SQLite
64-bit limits. Payment, invoice, allocation and reversal magnitudes must be >0.
No binary floats enter monetary fields; bool and float are rejected as cents.
`euros_to_cents` accepts finite Decimal or dot-decimal text with exact cent
precision; subcent input is rejected, never silently rounded. Future CSV adapters
must define locale and reject ambiguous separators rather than guessing.
Calculated line amounts use Decimal and explicit ROUND_HALF_UP to 0.01 EUR per
line, then sum integer gross lines. Tax is explanatory and does not constitute a
German tax-compliance implementation. SQL aggregate overflow must be checked in
Python using arbitrary-precision ints in future analytics. Chart-only float
conversions are allowed after exact totals, never for matching or controls.

## Dates and timezones

Business dates are ISO `YYYY-MM-DD` calendar dates. Booked date controls cash
reporting; value date is retained separately. Service dates do not move cash.
All audit/run timestamps must be timezone-aware, normalized to UTC at persistence
and serialized as ISO 8601. Europe/Berlin is the business display timezone;
tzdata is included for Windows. Excel will use real date cells formatted
`DD.MM.YYYY`, and EUR amounts with two decimals in Phase 5. Month-end means the
inclusive final business date, with a separate known-at run cutoff for late data.

## Identity and deterministic generation (Phase 2 contract)

Use `syn_<entity>_<uuid5 hex>` IDs; never Python's randomized hash(). Freeze a
project UUID namespace `5d846a52-b5cf-5791-a2b5-8da3e62ed80c` in generator
version 1, derive dataset IDs from canonical
configuration + generator version, and derive entity IDs from dataset ID, type
and stable sequence/source key. Imported bank identity uses source system + bank
event ID, not amount/date alone. Hash canonical UTF-8 JSON with sorted keys,
ISO dates, decimal strings, integer cents, stable row order and no NaN values.

The same seed, inclusive date range, count, discrepancy-rate decimal string,
generator version and dependency lock must yield the same records and manifest.
Use a local `random.Random(seed)` with a documented fixed call order; choose
amounts as integer cents. Do not mix NumPy/global RNGs. Derive synthetic effective
timestamps from configuration, never today's date. Real import/run timestamps
remain operational metadata and are excluded from input content hashes. Every
generated row includes synthetic=true and fictional names. IBAN-shaped tokens
are `DE00` + 18 digits: deliberately invalid check digits prevent their use as
payment instructions. No generator is present in Phase 1. Exact dependency
versions will be captured with the released demo; current bounds are not a lock.

Canonical generation configuration includes only schema/generator version, seed,
date range, record count and discrepancy rate, not machine-specific output paths.
Dataset content hashing excludes the manifest's own content_sha256 field to
avoid recursion. Operational run/import IDs and timestamps are excluded from
result fingerprints, which describe the financial effects and reason codes.
Duplicate file receipts reuse the original BankStatementImport; each new receipt
attempt is recorded as an AuditEvent, without inserting duplicate originals.

## Phase 2 implementation notes

Customer.customer_type and Account.energy_type are optional additions with
backward-compatible defaults. No Phase 1 financial field or rule was removed.
There is no separate Contract entity: Account represents the energy contract.
GenerationSettings uses customer_count, billing_periods and evaluation_date;
the older local Settings contract remains unchanged. Evaluation date is included
in the generator's semantic configuration. Full generation/export/oracle hash
scopes and CSV naming are documented in SYNTHETIC_DATA_GUIDE.md.

Generated correction records include synthetic approval cases, decisions, run
snapshots and audit fixtures using the existing schemas. Authoring runs are
explicitly tagged synthetic-correction-authoring-v1; they do not represent an
executed reconciliation engine. Expected allocations/releases exist only in the
separate evaluation oracle, not in canonical business input tables.

## Phase 3 projections

The engine reuses Allocation, AllocationRelease and ReconciliationRun without
changing original entity fields. MatchEvidence, ExceptionItem, PaymentOutcome,
InvoiceOutcome and AdjustmentEffect in reconciliation/results.py are immutable
result projections, not competing database entities. InputDataset retains source
provenance and modeled bank knowledge timestamps. Full field meanings, statuses,
hash scopes and knowledge assumptions are in RECONCILIATION_ENGINE.md.

ExceptionItem supports payment/reversal/invoice projection subjects and detailed
reasons; it is not a persisted ReviewCase or an executed ManualDecision. Phase 4
maps review subjects to stable live cases and turns explicit decisions into
validated ledger effects through the persistence service. Phase 3 outputs
independent snapshots and does not sum effects across different runs.
