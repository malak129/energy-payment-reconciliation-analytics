# Phase 2 verification — realistic synthetic billing and payment data

Completed and verified on 14 November 2026, Windows/Python 3.12.14.
Scope: synthetic generation, integrity validation, CSV export and evaluation
fixtures only. No reconciliation engine, dashboard, database implementation or
Excel reporting system was implemented. Phase 3 has not started.

## Result and configuration

The default dataset is generated under **data/synthetic/** (ignored by Git).
It contains 34 files: 14 canonical input CSVs, 18 statement fixture files,
ground_truth.json in a separate evaluation directory, and manifest.json.

| Setting | Executed default |
|---|---|
| Seed | 42 |
| Customers | 500 |
| Billing periods | 12 |
| First service date | 2025-01-01 |
| Final service date | 2025-12-31 |
| Evaluation date | 2026-03-01 |
| Exception/discrepancy rate | 0.15 of scenario cases |
| Generator/schema version | 1 / 1 |
| Dataset ID | syn_dataset_84540141918d5d3ab0859ff1baee3ff1 |
| Core business content SHA-256 | bbf0a4dc8c8eb94727ef521cf5b57a6cffb0f63d987f20785fa656e3b00fa913 |
| Manifest file SHA-256 | 5dd4f19dfd45050a38c52ef4bd337a8fed75f9fc35cbf667754ca29df8265e94 |

The evaluation date is a fixed derived date, not the computer date. End date
defaults to the final billing month's final day, evaluation to end +60 days.
Payment events may occur after the service-date window and are included only
when booked by the evaluation cutoff.

## Exact record counts

| Entity / representation | Count |
|---|---:|
| Customers | 500 |
| Private customers | 400 |
| Small-business customers | 100 |
| Accounts / contracts | 600 |
| Electricity accounts | 367 |
| Gas accounts | 233 |
| Invoices | 7,200 |
| Invoice line items | 14,400 |
| Unique incoming payments | 7,100 |
| Refunds | 98 |
| Chargebacks | 98 |
| Total reversal events | 196 |
| Correction entries | 98 |
| Synthetic correction approval cases | 98 |
| Synthetic manual correction decisions | 98 |
| Correction-authoring run fixture | 1 |
| Correction audit fixtures | 98 |
| Canonical monthly bank statement definitions | 13 |
| Canonical statement rows / unique bank events | 7,296 |
| Duplicate statement receipts/copies | 5 |
| Total statement receipt files | 18 |
| Repeated event representations in duplicate copies | 2,425 |
| Duplicate receipt audit fixtures | 5 |
| Scenario cases | 3,600 |
| Expected application records (oracle only) | 6,904 |
| Expected release records (oracle only) | 98 |
| Active expected exception records at evaluation | 639 |
| Expected unmatched cash receipts at evaluation | 245 |
| Expected payments requiring manual reference review | 245 |

Duplicate files contribute **zero** additional bank events and **zero** additional
cash. The unique bank-event count is 7,100 receipts +196 outflows. The raw
statement copies are alternative representations of those same events.

There is no Contract model distinct from Account, so accounts.csv represents
contracts and no redundant contracts.csv is exported. InvoiceLine maps to
invoice_items.csv. All modeled records are marked synthetic.

## Exact scenario distribution

Each primary scenario case covers two consecutive invoices on one account in
the default dataset. Labels are disjoint case assignments, not all overlapping
payment attributes. Four normal timing families occupy 3,060 cases; eleven
exception families occupy 540 cases (15%).

| Primary scenario | Cases | Invoices | Incoming payment events |
|---|---:|---:|---:|
| Correct/on-time | 765 | 1,530 | 1,530 |
| Early | 765 | 1,530 | 1,530 |
| Late | 765 | 1,530 | 1,530 |
| Cross accounting month | 765 | 1,530 | 1,530 |
| Unpaid | 50 | 100 | 0 |
| Partial | 49 | 98 | 98 |
| Multiple payments per invoice | 49 | 98 | 196 |
| Combined payment | 49 | 98 | 49 |
| Overpayment | 49 | 98 | 98 |
| Missing reference | 49 | 98 | 98 |
| Incorrect reference | 49 | 98 | 98 |
| Ambiguous payment | 49 | 98 | 49 |
| Refund | 49 | 98 | 98 |
| Chargeback | 49 | 98 | 98 |
| Approved invoice correction | 49 | 98 | 98 |
| **Total** | **3,600** | **7,200** | **7,100** |

There are additionally five duplicate-file scenarios. Refund/chargeback cases
each produce two corresponding outflows in the default paired cases. The
generator deliberately cycles scenarios for coverage; these frequencies are not
an empirical estimate of utility customers' behavior.

## Financial totals

All calculations use integer cents; EUR below is display formatting only.
All source financial events fall on or before the default evaluation cutoff,
so all-date cash figures and the cumulative cutoff cash figures agree here.

| Measure | EUR |
|---|---:|
| Original invoices | 2,244,345.84 |
| Incoming payments | 2,186,839.60 |
| Refund outflows | 2,055.36 |
| Chargeback outflows | 27,899.24 |
| Signed invoice corrections | -2,718.72 |
| Adjusted invoice face value at evaluation | 2,241,627.12 |
| Net cash at evaluation | 2,156,885.00 |
| Expected active applications at evaluation | 2,067,991.84 |
| Expected outstanding receivables at evaluation | 173,635.28 |
| Expected unapplied cash at evaluation | 88,893.16 |

The last three balances are **oracle expectations**, not results from a
reconciliation engine. Hidden intended relationships are marked intent_only and
never treated as expected automatic applications. Uncertain cash remains
unapplied even though its intended invoice is known to the fixture author.

Controls checked in integer cents and displayed here in EUR:

```text
Net cash = 2,186,839.60 - 2,055.36 - 27,899.24 = 2,156,885.00
Net cash = applications + unapplied = 2,067,991.84 + 88,893.16
Adjusted invoices = 2,244,345.84 - 2,718.72 = 2,241,627.12
Adjusted invoices = applications + outstanding = 2,067,991.84 + 173,635.28
Adjusted invoices - net cash = outstanding - unapplied = 84,742.12
```

In addition to aggregate equations, validation checks per-payment and per-invoice
bounds at every authored event date, plus reversal/release ordering and limits.
No allocation is inferred from references or amounts by this phase.

## Implementation and compatibility

Before implementation, the existing model, rules, Phase 1 report and code were
inspected, and the unchanged baseline suite passed all 57 tests. The following
schema gaps were addressed explicitly:

- Customer lacked a private/business classification; added customer_type with
  default private.
- Account lacked commodity classification; added energy_type with default
  electricity. Accounts retain their established one-contract meaning.
- Corrections already required a decision link. Rather than fabricating dangling
  IDs, generated corrections include existing ReviewCase, ManualDecision,
  ReconciliationRun and AuditEvent records as clearly labeled authoring fixtures.
- Actual Allocation rows require a reconciliation run. Expected applications and
  releases therefore remain distinct evaluation-only records, not fake ledger rows.

No established monetary, reversal, correction or matching rule was changed. The
existing entities, IDs, integer cents, commercial rounding, EUR-only policy,
invalid DE00 IBAN-shaped tokens and immutable records were retained. Optional
new fields preserve older constructor payloads and all original tests.

| File | Purpose/change |
|---|---|
| data_generation/settings.py | Typed generation configuration and calendar boundaries |
| data_generation/generator.py | Seeded customers/accounts/invoices, scenario templates and synthetic approval fixtures |
| data_generation/expectations.py | Evaluation-only typed relationships, exceptions, releases and balance snapshots |
| data_generation/validation.py | Hash/schema/link validation, timeline bounds and generator control totals |
| data_generation/export.py | Deterministic CSV/JSON, monthly raw statements, duplicate copies, manifests and safe directory export |
| data_generation/__init__.py | Updated implemented-package description |
| models/records.py | Backward-compatible classification fields only |
| cli.py | generate command and configuration flags; doctor retained |
| tests/test_generation.py | 48 additional test cases including every scenario |
| SYNTHETIC_DATA_GUIDE.md | Generation, assumptions, dictionary, inspection and future evaluation workflow |
| DATA_MODEL.md / BUSINESS_RULES.md / README.md | Current scope, schema extensions and fixture semantics |
| PHASE_2_VERIFICATION.md | This executed-results report |

Module paths in the table are relative to src/energy_reconciliation, except
tests and top-level Markdown documents. No new dependency was needed. Existing
src layout, package boundaries, local settings and Phase 1 tests were retained.

## Tests and executed checks

Final full suite: **105 passed, 0 failed, 0 errors, 0 skipped** in 9.32 seconds.
This includes the original 57 Phase 1 cases and 48 new cases. Duration is an
observed test-run time, not a performance benchmark.

Coverage includes:

- Same-seed determinism and equivalent decimal-rate normalization.
- All exported bytes identical across separate processes with different
  PYTHONHASHSEED and different output directories.
- No wall-clock access in generation and independence from caller Decimal precision.
- All fifteen primary scenario families and exact exception quota/distribution.
- A reviewed small golden example: net items 1,225 and 7,099 cents, tax 233 and
  1,349 cents, invoice/payment 9,906 cents.
- Core business models and raw bank events round-trip through their existing
  Pydantic schemas; CSV fields round-trip with explicit integer/boolean/tuple conversion.
- Unique IDs, source keys, invoice/contract references and shared bank event keys.
- Valid links, invoice sums, exact integer tax rounding, dates and leap-year bounds.
- Partial, split, combined, excess, missing/incorrect reference, ambiguous,
  refund, chargeback/release, correction and cutoff semantics.
- Intent-only links cannot authorize expected applications.
- Duplicate statement bytes/hash/identity and unique accepted event coverage.
- Repeated exports are identical no-ops; foreign or modified output is refused.
- Deliberately broken foreign keys, duplicate IDs, invoice totals and cash bounds
  are rejected, not just positive fixtures accepted.
- Full default dataset size/control equations and all module imports.

Additional final results: Ruff lint PASS; Ruff formatting PASS; root and generate
CLI help PASS; doctor PASS; pip check reported no broken requirements. The final
generated files' SHA-256 values were read back from disk and verified against
manifest, as were CSV row counts, scenario counts and duplicate-copy contents.
Git ignore checks confirm generated data and ground truth are excluded.

Commands executed from repository root in Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\energy-reconciliation.exe --help
.\.venv\Scripts\energy-reconciliation.exe generate --help
.\.venv\Scripts\energy-reconciliation.exe doctor --config .\config.example.toml
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\energy-reconciliation.exe generate
git check-ignore data/synthetic/manifest.json data/synthetic/evaluation/ground_truth.json
```

During development, Ruff formatting was applied, targeted smoke data was
generated, and the full suite was run repeatedly after material changes. Tests
used normal temporary-directory access because the restricted execution sandbox
cannot create pytest's standard temporary fixtures. This is an environment
permission requirement, not a failed project test.

An earlier development export was preserved under data/phase2-initial rather
than overwritten when hidden-intent labeling was refined. The current deliverable
is data/synthetic. Development smoke output is also ignored under data/.

## Inspect and reproduce

```powershell
$root = '.\data\synthetic'
Import-Csv "$root\inputs\invoices.csv" | Select-Object -First 5 reference,issued_on,due_on,amount_cents
Import-Csv "$root\inputs\payments.csv" | Select-Object -First 5 bank_event_id,booked_on,reference,@{Name='EUR';Expression={[decimal]$_.amount_cents / 100}}
$manifest = Get-Content "$root\manifest.json" -Raw | ConvertFrom-Json
$manifest.summary.counts
$manifest.summary.scenario_counts
```

The complete CLI example and concise field dictionary are in
SYNTHETIC_DATA_GUIDE.md. The same command/configuration produces identical bytes;
an identical rerun does not alter existing output. To try another configuration,
provide a different --output-dir. Do not feed evaluation/ to normal reconciliation.

## Limitations and completion assessment

All requested generation/export/test/documentation deliverables are complete.
Default invoice count meets the 5,000–8,000 target, and every requested scenario
is represented with deterministic tests. Existing Phase 1 functionality passes.

The data models monthly advances, not metered consumption, annual settlement or
real tariffs. Tax is an assumed fixed rate, not tax advice or certified logic.
Calendar due dates do not adjust for bank holidays/weekends. Customer behavior is
balanced for test coverage, not sampled from empirical payment distributions.
Small datasets/low exception rates cannot guarantee every family; one-period
datasets explicitly omit pair-dependent scenarios.

Ground truth projects business dates assuming all fixture information is known;
it is not a historical known-at engine run. Candidate IDs are authored witnesses,
not exhaustive future engine candidate sets. Correction reversal chains, optional
operator invoices and production bank formats are not generated in v1.

Duplicate import expectations/provenance are synthetic fixtures; a general
CSV/XLSX ingestion and idempotent persistence service is not implemented. No
operational review queue, reconciliation, SQL tables, reporting dashboard or
Excel workbook was added. Cross-platform execution and a full dependency-version
matrix remain untested; verification used Windows/Python 3.12.14. Dependencies
retain the Phase 1 bounds rather than a new exact transitive lock.

Phase 2 is complete within its requested generation scope. Stop pending user
approval; do not start Phase 3.
