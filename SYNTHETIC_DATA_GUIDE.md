# Synthetic energy billing and payment data — generator version 1

All data is SYNTHETIC. The fictional provider is **SYN Energieversorgung**.
There are no real people, bank identifiers, companies, SAP connections or bank
connections. This generator authors fixtures and an evaluation oracle; it does
not reconcile payments, import files into a database or execute accounting entries.

## Generate and inspect

From the repository root in Windows PowerShell, using the installed environment:

```powershell
.\.venv\Scripts\energy-reconciliation.exe generate --help
.\.venv\Scripts\energy-reconciliation.exe generate
```

Defaults: seed 42, 500 customers, 12 periods from 2025-01-01 through 2025-12-31,
evaluation date 2026-03-01, discrepancy rate 0.15, output `data/synthetic`.
The default creates 600 accounts, 7,200 invoices and several thousand payments.
Exact verified counts and EUR totals are in PHASE_2_VERIFICATION.md.

Explicit custom example:

```powershell
.\.venv\Scripts\energy-reconciliation.exe generate --seed 17 --customers 100 --billing-periods 6 --start-date 2024-01-01 --end-date 2024-06-30 --evaluation-date 2024-08-31 --discrepancy-rate 0.20 --output-dir .\data\six-month-demo
```

Aliases: `--customer-count` for `--customers`, `--exception-rate` for
`--discrepancy-rate`. Dates are ISO, not locale-dependent strings. The start date
determines the first billing month; end date must fall in the final requested
month. Without end date, use that month's final day. Without evaluation date,
use end date + 60 days. Partial first/last service months are clipped, but the
advance installment is not prorated. Payments/reversals may occur after the
service-date window. An earlier evaluation date retains future source events
but excludes their financial effects from expected balances.

Reusing an identical output directory is a no-op after byte comparison. Different
or modified contents are refused; choose another output directory. The generator
stages new output before publishing the directory. It never recursively deletes
an existing dataset or user files. A generation error returns CLI exit code 1.

```powershell
$root = '.\data\synthetic'
$manifest = Get-Content "$root\manifest.json" -Raw | ConvertFrom-Json
$manifest.summary.counts
$manifest.summary.scenario_counts
Import-Csv "$root\inputs\customers.csv" | Select-Object -First 5
Import-Csv "$root\inputs\invoices.csv" | Select-Object -First 5 reference,issued_on,due_on,@{Name='amount_eur';Expression={[decimal]$_.amount_cents / 100}}
Import-Csv "$root\inputs\payments.csv" | Select-Object -First 5 bank_event_id,booked_on,reference,@{Name='amount_eur';Expression={[decimal]$_.amount_cents / 100}}
$truth = Get-Content "$root\evaluation\ground_truth.json" -Raw | ConvertFrom-Json
$truth.cases | Select-Object -First 5
```

CSV files are UTF-8, comma-separated, with headers and LF line endings. Money
columns contain base-10 integer cents, flags are lowercase `true`, dates are ISO,
timestamps include UTC, optional values are empty, and tuple columns are JSON
arrays. PowerShell Import-Csv returns strings: use decimal/integer conversion
explicitly. Spreadsheet double-click behavior may depend on German locale;
use Excel's Text/CSV import with comma delimiter and UTF-8 if inspecting there.
No Excel report is generated in Phase 2.

## Structure and concise data dictionary

Every modeled row has id, synthetic=true and schema_version=1. Imported entities
also have dataset_id and source_record_id. DATA_MODEL.md remains the detailed
entity contract; existing Pydantic models are reused.

| File | Entity and key fields |
|---|---|
| inputs/customers.csv | Customer: display_name, customer_type (private/small_business) |
| inputs/accounts.csv | Account/contract: customer_id, contract_reference, energy_type (electricity/gas), opened_on, synthetic_iban, EUR |
| inputs/invoices.csv | Invoice: account_id, unique reference, issue/due/service dates, positive gross amount_cents |
| inputs/invoice_items.csv | InvoiceLine: invoice_id, line_number, description, net_cents, tax_cents, gross_cents |
| inputs/payments.csv | Unique Payment: bank_event_id, source_system, claimed account_id, reference, booked/value dates, positive incoming amount_cents |
| inputs/refunds_chargebacks.csv | Reversal: payment_id, kind refund/chargeback, positive outgoing amount_cents, booked/value dates |
| inputs/corrections.csv | Correction: invoice_id, decision_id, signed amount_cents, effective date, reason; originals unchanged |
| inputs/review_cases.csv | Synthetic invoice-correction approval cases, linked to authoring run; not an engine-produced exception queue |
| inputs/manual_decisions.csv | Synthetic correction approvals: case_id, actor, action, resolved account, date and reason |
| inputs/authoring_runs.csv | Existing ReconciliationRun schema reused solely as a versioned correction-authoring fixture, explicitly identified by rules_version |
| inputs/audit_events.csv | Synthetic approval evidence for the generated corrections |
| inputs/bank_statements.csv | Canonical BankStatementImport definitions: filename, file SHA-256, modeled receipt date and row count |
| inputs/import_rows.csv | Canonical ImportRow provenance fixtures: statement, row number, original event ID and payload SHA-256 |
| inputs/statement_audit_events.csv | Synthetic duplicate-file receipt evidence; no extra cash or accepted row |
| statement_fixtures/statement_YYYY-MM.csv | Alternative raw bank representation: synthetic flag, event_kind, full existing Payment/Reversal record as record_json |
| statement_fixtures/*_duplicate.csv | Byte-identical statement copies, deliberately different filenames |
| evaluation/ground_truth.json | Evaluation-only intended links, expected applications/releases/exceptions and dated balances |
| manifest.json | Synthetic Dataset record, canonical configuration, counts/totals, input/evaluation paths, statement receipts and SHA-256 per exported file |

There is no separate Contract model. Account already means one energy contract;
therefore accounts.csv includes contract_reference and no duplicate contracts.csv
is created. InvoiceLine is supported and is exported under invoice_items.csv.
Optional operator invoices are not generated by this phase.

## Business assumptions and billing

Every fifth customer is a fictional small business and has both energy types;
other customers have one account. Primary accounts alternate by a fixed pattern
between Strom and Gas. Hence account count = customers + floor(customers/5).
Names begin `Synthetic Customer`; business names contain `SYN Betrieb`.

Each account receives one monthly **Abschlagsrechnung** for a fixed advance,
with Grundpreis and Verbrauchsabschlag items. Fixed advances intentionally avoid
pretending that simulated monthly installments are metered consumption. No
annual true-up, meter readings, tariff switching or seasonal usage engine is
included. Invoice gross amount is the sum of rounded item gross amounts.

Chosen monthly net ranges in cents (simulation parameters, not market estimates):
private Strom 6,500–16,000, private Gas 10,000–25,000; business Strom
18,000–65,000, business Gas 25,000–90,000. Each includes a 1,200–2,200 cent
Grundpreis. The assumed tax rate is a fixed 19%, rounded per line with the
existing Decimal ROUND_HALF_UP helper. This is not a tax-compliance model or
a claim about applicable historical/future rates.

Invoices are issued at service-period start and due 14 days later. Dates use the
calendar without weekend/holiday adjustment. German operational terminology is
used in synthetic descriptions; English internal field names are preserved.

## Determinism and identity

GenerationSettings is separate from Phase 1 Settings to preserve the original
doctor TOML contract and passing tests. Generation is configured through the
CLI or typed GenerationSettings API; config.example.toml remains for doctor and
local environment settings, not a generator configuration file.

One local random.Random(seed) generates account amounts, shuffles scenario cases,
then generates excess-payment cents. Financial calculation uses only integer
cents and Decimal in a local precision context. UUID5 uses the fixed namespace
from DATA_MODEL.md. Dataset identity includes generator/schema version, seed,
customer count, billing periods, start/end/evaluation dates and normalized rate;
it excludes output path. Source row/event IDs are stable synthetic sequences.

All generated timestamps derive from configured financial dates. No computer
date, wall-clock timestamp, global RNG or randomized Python hash enters output.
Canonical JSON is sorted, UTF-8, newline-terminated and excludes NaN values.
Equivalent rates such as 0.15 and 0.150 have identical semantics and bytes.

Dataset.content_sha256 covers the model business tables returned by
SyntheticDataset.business_tables, including correction support records, excluding
the Dataset manifest, ground truth and derived statement fixtures. Manifest file
hashes separately cover every exported file except manifest.json itself, avoiding
recursive hashing. Reproducibility tests compare every exported byte across
different directories and separate Python processes with different hash seeds.

## Scenario scheduling and rules

Consecutive invoices are grouped into pairs within each account; an odd final
period creates a singleton. These are authoring **cases**, not reconciliation
cases. Seeded shuffling distributes patterns across accounts/months.
`floor(case_count * discrepancy_rate)` cases cycle through the eleven exception
families below; remaining cases cycle through four normal timing families. This
is controlled scenario coverage, not a statistically estimated customer behavior
distribution. Defaults produce 540 exception cases out of 3,600 (15%).

| Family | Authored behavior and expected outcome |
|---|---|
| correct | Full invoice amount, exact reference, booked on due date |
| early | Full amount, booked issue + 2 days, before due date |
| late | Full amount, booked due + 18 days |
| cross_month | Full amount, booked next month on day 4 |
| unpaid | No bank payment; outstanding invoice, flagged after due date |
| partial | 60% integer-cent payment; exact-reference application, remaining debt, amount_mismatch label |
| multiple_payments | Two distinct bank events split an invoice into integer halves, second +2 days; total exactly settles debt |
| combined | One event equals the open gross sum of both invoices on the same account; explicit references separated by ` | ` |
| overpayment | Full settlement plus 500–4,000 cents; extra remains unapplied, flagged overpayment |
| missing_reference | Null reference; intended relationship held back, no expected automatic application |
| incorrect_reference | Nonexistent SYN-RE-UNKNOWN reference; no automatic application |
| ambiguous | One payment equals either of two same-account advances; no exact reference, neither invoice assigned automatically |
| refund | Invoice amount plus credit received, invoice applied, credit refunded +7 days; no release needed |
| chargeback | Full receipt applied then fully returned +7 days; same-date expected release reopens the invoice |
| correction | Approved 10% gross receivable reduction (integer cents), effective issue +1 day; later payment settles adjusted amount |

Payment scenario counts describe disjoint primary case labels. A payment labeled
late can also cross an accounting month; labels do not enumerate every overlapping
property. Refund and chargeback occurrence counts in cash are individual Reversal
records, usually two per paired case. Duplicate imports are an additional file
scenario: every third canonical monthly statement has one identical copy.

Tiny datasets/low rates may have too few cases to include every family. One-period
datasets exclude combined and ambiguous families because no invoice pair exists;
manifest lists these as unavailable. Default data covers every requested family.

## Financial validation and duplicate representations

All original IDs, source keys, bank event keys, invoice references and contract
references are unique. All relationships stay within the dataset and account.
Invoice line sums equal original totals; corrections retain original line items.
Payments/reversals have positive magnitudes. A reversal never exceeds its parent
receipt, and its date is not before the receipt. Correction approval links and
synthetic audit evidence are validated.

The generated timeline validator projects authored links at each event date,
checking per-invoice and per-payment allocation limits, release limits, nonnegative
available cash and outstanding balances. Refunds consume excess cash without
altering debt; chargebacks reduce cash once and release allocations once. Dated
effects are grouped atomically for the synthetic scenario. Evaluation balances
are cross-checked against a separate timeline projection and the documented
controls: net cash = allocated + unapplied; adjusted invoices = allocated + debt.
These are generation controls over an oracle, not a matching/analytics service.

Evaluation projects business dates with all fixture information assumed known;
it is not a historical known-at reconciliation run. Dates after the evaluation
remain in source files but contribute zero to the snapshot. Correction authoring
run metadata is solely synthetic approval provenance, not evidence of executing
Phase 3. Authoring hashes cover the invoice schedule and correction fixtures.

Bank statements retain unique events once in canonical tables and accepted-row
fixtures. Duplicate file receipts reuse the same statement ID/hash; only a
synthetic receipt audit record is added. Their raw rows are repeated representations,
not additional payments. No idempotent import service is claimed: that behavior
will be implemented in the ingestion/persistence phases and tested with these
fixtures. The manifest explicitly lists expected receipt outcomes.

## Ground truth and Phase 3 evaluation

Ground truth is physically separate in evaluation/. It records:

- Scenario cases and intended invoice/payment links, including hidden intent for
  payments whose observable references cannot establish a safe match.
  Those hidden links use reason_code=intent_only and are excluded from expected
  automatic applications.
- Expected automatic applications and their dated releases; these are
  ExpectedApplication/ExpectedRelease evaluation records, not ledger allocations.
- Active expected exception categories at evaluation date. These include
  informational mismatches/corrections, not just pending manual-review items.
- Per-invoice adjusted, applied and outstanding cents; per-payment received,
  reversed, applied and unapplied cents at evaluation date.
- Unmatched payment IDs (positive available cash, no active application) and
  separate manual-review IDs. Fully reversed receipts are not unmatched cash.

Candidate IDs are authored witnesses/intended targets for evaluation, not a
claim that those are the only candidates discoverable from observable input.
Uncertain receipts remain unapplied; hidden intent never authorizes allocation.
The unresolved cash/debt snapshot is deterministic even when hidden intent is
known to the fixture author. Refunded excess is no longer an active overpayment
exception after its outflow date. No correction reversals are generated in v1.

Phase 3's normal execution must consume only canonical `manifest.input_files`,
ignore manifest evaluation summaries for matching, and never read evaluation/.
Statement fixtures are alternative representations for explicit import tests;
do not add their cash to canonical payments a second time. A separate evaluation
test harness may compare future engine results with the oracle after execution.
The reconciliation package is still unimplemented and imports no generation or
ground-truth code. No automatic match is inferred by this phase.

## Tests and scope

Run the full suite and quality checks:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Tests cover all original Phase 1 checks, every scenario, exact line-tax rounding,
a fixed golden example, date boundaries/leap years, early evaluations, duplicate
representations, CSV model round trips, hash verification, safe reruns, altered
Decimal precision, different process hash seeds, and deliberately invalid links
and balances. Generated output remains ignored by Git.

CSV/XLSX ingestion, SQL persistence, reconciliation, an operational manual-review
queue, monthly reporting, Excel and Streamlit are still outside this phase.
No benchmark, tax certification or production banking behavior is claimed.
