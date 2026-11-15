# Phase 3 completion and verification

Verified 14 November 2026 on Windows, Python 3.12.14.
Scope: strict Phase 2 source ingestion, deterministic in-memory reconciliation,
explainability, financial controls and separate evaluation. No SQLite persistence,
database-backed manual resolution, Streamlit or Excel reporting was implemented.
Phase 4 has not started.

## Executed result

The full existing default dataset was reconciled successfully. Outputs are in
**outputs/reconciliation/**; explicit oracle evaluation is in
**outputs/evaluation/evaluation.json**. Both locations are ignored by Git.

| Reproducibility field | Actual value |
|---|---|
| Dataset | syn_dataset_84540141918d5d3ab0859ff1baee3ff1 |
| Rules version | reconciliation-1.0.0 |
| Business evaluation date | 2026-03-01 |
| Known-at cutoff | 2026-03-01T23:59:59.999999+00:00 |
| Reconciliation run | syn_run_436fba1b4ac450509c106860174a7b9a |
| Source manifest SHA-256 | 5dd4f19dfd45050a38c52ef4bd337a8fed75f9fc35cbf667754ca29df8265e94 |
| Run input SHA-256 | 8143590589eb33e6b6d3a0400bc09b9ca082e704870573fbb65ac004e68a2f56 |
| Business result SHA-256 | 53b25d2dd1ced153f6906b81c6fa3ff1410eda5847829a44d515cfd2adb96a3b |

The source manifest and **every** original Phase 2 exported file, including the
oracle, were checked after execution against their existing hashes. All remain
unchanged. No synthetic data or ground-truth record was edited to fit the engine.
Original Pydantic entity schemas and all 105 prior tests were preserved.

## Source validation and duplicate accounting

| Source/result count | Actual |
|---|---:|
| Customers / accounts | 500 / 600 |
| Invoices / invoice items | 7,200 / 14,400 |
| Unique incoming payment events | 7,100 |
| Unique refunds / chargebacks | 98 / 98 |
| Approved correction fixtures | 98 |
| Unique cash events, receipts plus outflows | 7,296 |
| Canonical statements / duplicate copies | 13 / 5 |
| Operational source files verified | 32, plus source manifest |
| Bank representations read across tables and all statement files | 17,017 |
| Duplicate bank representations contributing zero additional cash | 9,721 |
| Of those, representations in extra duplicate statement copies | 2,425 |
| Exported source provenance occurrences, including non-bank records | 47,424 |
| Actual allocation records / evidence records | 6,904 / 6,904 |
| Actual allocation releases | 98 |
| Applied adjustment effects (98 corrections +196 outflows) | 294 |

The 9,721 duplicate representations comprise 7,296 canonical-statement mirrors
of master-table bank events plus 2,425 rows in duplicate file copies. They are
not 9,721 extra payments. The strict adapter determines duplicates from stable
event identity and equal payload; it does not trust expected receipt outcomes.
Changed payloads for an existing event fail clearly. Original text values,
source record positions, IDs and payload hashes remain in provenance.

## Financial control report

All machine calculations use integer euro cents. EUR below is display formatting.
All source cash and correction events are inside the default cutoffs.

| Measure | Actual EUR |
|---|---:|
| Original issued invoices | 2,244,345.84 |
| Signed approved invoice corrections | -2,718.72 |
| Adjusted receivables | 2,241,627.12 |
| Gross incoming payments | 2,186,839.60 |
| Refund outflows | 2,055.36 |
| Chargeback outflows | 27,899.24 |
| Net cash | 2,156,885.00 |
| Net allocated cash after releases | 2,067,991.84 |
| Unapplied cash | 88,893.16 |
| Outstanding receivables | 173,635.28 |
| Verified customer credit within unapplied cash | 2,198.54 |
| Unidentified suspense within unapplied cash | 86,694.62 |
| Cash control difference | **0.00** |
| Receivable control difference | **0.00** |

```text
2,186,839.60 - 2,055.36 - 27,899.24 = 2,156,885.00 net cash
2,156,885.00 = 2,067,991.84 allocated + 88,893.16 unapplied
2,244,345.84 - 2,718.72 = 2,241,627.12 adjusted receivables
2,241,627.12 = 2,067,991.84 allocated + 173,635.28 outstanding
2,198.54 verified credit + 86,694.62 suspense = 88,893.16 unapplied
Adjusted receivables - net cash = outstanding - unapplied = 84,742.12
```

Every invoice and payment also passes its individual bounds. Aggregate identities
are not used to conceal offsetting allocation errors. These are financial
conservation checks, not collection performance or matching-quality KPIs.

## Statuses and review queue

Active matched events = **6,757**; positive-cash unmatched events = **245**;
fully reversed events = **98**. These partition the 7,100 incoming payment events.
Across history before releases, 6,855 distinct payments had automatic applications.

| Event classification | Count |
|---|---:|
| Matched | 6,365 |
| Partial invoice payment | 196 |
| Overpaid / residual credit | 98 |
| Adjusted by linked outflow | 98 |
| Ambiguous | 104 |
| Other manual review | 141 |
| Fully reversed | 98 |

Payment allocation state and invoice settlement state are separate. A receipt
fully applied to a partly unpaid invoice is allocated cash, not unapplied cash.
The 196 partial-payment classifications include the first installment of split
payments; their invoices can be settled by a later receipt.

Invoice statuses: **6,610 settled**, **492 open**, **98 partial**. There are no
cancelled invoices in this default dataset; 98 invoices have approved adjustments.

The pending manual-review queue contains **343** items: 245 unmatched/uncertain
receipts and 98 verified residual-credit receipts. It retains amounts,
explanations, source-linked subjects and candidates without selecting a match.
No manual payment decision was executed.

| Exception reason | Count | Pending manual review? |
|---|---:|---|
| ambiguous | 104 | Yes |
| missing_reference | 98 | Yes |
| unknown_reference | 43 | Yes |
| overpayment | 98 | Yes |
| amount_mismatch | 98 | Informational partial-debt notice |
| outstanding_invoice | 590 | Informational receivable balance |

Full exception count is 1,031, including the 688 informational items. The queue
is not artificially inflated with every unpaid invoice.

## Actual separate evaluation

The runtime engine and input adapter never read evaluation/ground_truth.json.
The evaluation command was run only after normal reconciliation completed.

| Metric | Actual |
|---|---:|
| Correct automatic allocation records | 6,904 |
| Incorrect automatic allocation records | **0** |
| Missing expected automatic allocation records | **0** |
| Allocation precision: correct / produced | **100.0000%** |
| Expected-allocation coverage: correct / expected | **100.0000%** |
| Distinct payments ever automatically matched | 6,855 / 7,100 (**96.5493%**) |
| Payments with positive active applications after outflows | 6,757 / 7,100 (**95.1690%**) |
| Positive-cash unresolved payment events | 245 |
| Payments with any unapplied cash, including matched excess | 343 |
| Correct / incorrect releases | 98 / **0** |
| Outstanding balance difference from oracle | **EUR 0.00**, no per-invoice differences |
| Unapplied cash difference from oracle | **EUR 0.00**, no per-payment differences |

These are measured results on the synthetic evaluation dataset, not a claim of
production accuracy. Gross allocation coverage includes applications subsequently
released by chargebacks; active coverage deliberately counts their remaining cash.

Reason-label differences were retained and reported rather than forcing the
engine to reproduce generator intent:

| Oracle review category | Engine review reason | Payments |
|---|---|---:|
| ambiguous | ambiguous | 49 |
| missing_reference | missing_reference | 98 |
| unknown_reference | unknown_reference | 43 |
| unknown_reference | ambiguous | 55 |

Those 55 incorrect references have several plausible equal open candidates in
the observable input. The engine conservatively labels them ambiguous. They
remain unapplied in both engine and oracle; this changes no financial balance
and creates no false automatic match. Candidates are not chosen by amount.

## Historical knowledge check on actual full source files

Both additional runs used business evaluation date **2025-01-15**. The January
statement becomes known at its modeled receipt, **2025-01-31 12:00 UTC**.

| Measure | known_at 2025-01-30 23:59:59 UTC | known_at 2025-01-31 12:00 UTC |
|---|---:|---:|
| In-scope invoices | 600 | 600 |
| In-scope receipts | 0 | 326 |
| Adjusted receivables EUR | 186,764.68 | 186,764.68 |
| Net cash EUR | 0.00 | 102,872.76 |
| Net allocated EUR | 0.00 | 95,403.60 |
| Unapplied EUR | 0.00 | 7,469.16 |
| Outstanding EUR | 186,764.68 | 91,361.08 |
| Both financial control differences | 0.00 | 0.00 |

Artifacts are in outputs/historical-before and outputs/historical-after. The
older business cutoff still excludes payments booked after January 15 even
when the whole statement is later known. These runs are not compared with the
default March oracle, which explicitly assumes full source knowledge.

Invoice knowledge uses the documented issue-date assumption because Phase 2 has
no actual invoice receipt timestamps. Correction knowledge uses dated approval
evidence. This is explicit source availability modeling, not a claim to recover
historical facts absent from the dataset.

## Tests and quality checks

Final full suite: **155 passed, 0 failed, 0 errors, 0 skipped** in 29.54 seconds.
This includes all **105 prior cases** and **50 new reconciliation cases**.
Duration is an observed test-run duration, not an application benchmark.

New coverage includes exact references and normalization boundaries, missing
account inference, same-customer different-account conflicts, prohibition on
amount/name/fuzzy matching, partial/multiple/combined payments, incorrect splits,
credits, unpaid/late/cross-month invoices, future invoice references, full/partial
refunds and chargebacks, repeat reversals, unique full multi-allocation releases,
ambiguous partial-release holds, approved corrections/undo, approval reuse and
chronology errors, unsafe reductions requiring explicit releases, independent
business/known cutoffs, late known evidence, equivalent UTC offsets, empty known
snapshots and large odd-cent totals beyond binary-float integer precision.

Source/export tests cover actual generated CSVs/statements, raw-value provenance,
duplicate identities/copies, conflicting payloads, malformed integer money,
hash mismatch, malformed manifests, protected output, traversal rejection before
opening oracle paths, source-order independence and byte-identical results
across separate processes with different Python hash seeds. Separate tests verify
zero false allocations on a freshly generated full default fixture and verify
that deliberately incorrect allocations are reported as incorrect by evaluation.

Final Ruff lint and formatting checks pass. CLI reconcile --help, doctor and
pip check pass. No new dependency was needed. Tests ran with normal temporary
directory access, as required by this environment's pytest fixture permissions.

The actual full dataset was reconciled twice into different output directories.
**All four output files were byte-identical**, including provenance and the
human-readable summary. No source or oracle file changed. Preliminary development
outputs were retained separately under ignored outputs/ directories; the final
deliverables are outputs/reconciliation and outputs/evaluation.

## Files and architecture

| File | Purpose |
|---|---|
| src/energy_reconciliation/ingestion/csv_dataset.py | Strict generated-source adapter, deduplication, provenance, dates, foreign keys and approval validation |
| src/energy_reconciliation/reconciliation/results.py | Typed run options, statuses, evidence, review and financial result projections |
| src/energy_reconciliation/reconciliation/engine.py | Pure deterministic replay, matching, allocation bounds, reversals, corrections and controls |
| src/energy_reconciliation/reconciliation/export.py | Safe JSON/JSONL/Markdown output and exact EUR formatting |
| src/energy_reconciliation/utilities/serialization.py | Canonical JSON fingerprints and stable IDs |
| src/energy_reconciliation/evaluation.py | Explicit isolated oracle evaluation command and metrics |
| tests/test_reconciliation.py | 50 unit/integration/evaluation cases |
| src/energy_reconciliation/cli.py | Reconcile command, help/cutoff options and clear errors |
| ingestion/reconciliation __init__.py | Updated implemented-package scope |
| RECONCILIATION_ENGINE.md | Rules, reason/status definitions, controls, knowledge assumptions and commands |
| PHASE_3_VERIFICATION.md | This actual-results report |
| README.md, BUSINESS_RULES.md, DATA_MODEL.md | Current implemented scope and explicit Phase 3 policies |

The existing monetary representation, core schemas, financial signs, account
relationships and rounding helpers were not changed. New result types are
projections and do not replace core Invoice/Payment/Allocation entities.

## Commands executed and reproduction

From repository root in Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\energy-reconciliation.exe reconcile --help
.\.venv\Scripts\energy-reconciliation.exe doctor --config config.example.toml
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir data/synthetic --output-dir outputs/reconciliation --evaluation-date 2026-03-01
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir data/synthetic --output-dir outputs/reconciliation-repeat --evaluation-date 2026-03-01
.\.venv\Scripts\python.exe -m energy_reconciliation.evaluation --result outputs/reconciliation/reconciliation.json --ground-truth data/synthetic/evaluation/ground_truth.json --output-dir outputs/evaluation
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir data/synthetic --output-dir outputs/historical-before --evaluation-date 2025-01-15 --known-at 2025-01-30T23:59:59Z
.\.venv\Scripts\energy-reconciliation.exe reconcile --input-dir data/synthetic --output-dir outputs/historical-after --evaluation-date 2025-01-15 --known-at 2025-01-31T12:00:00Z
```

Additional read-only verification compared every output byte, source file hash,
source manifest hash, invoice status counts and provenance row count. Ruff format
was applied during development before final checks. No repository commit,
publication or external message was sent.

Inspect results:

```powershell
Get-Content .\outputs\reconciliation\summary.md
$result = Get-Content .\outputs\reconciliation\reconciliation.json -Raw | ConvertFrom-Json
$result.controls
$result.review_queue | Select-Object -First 5 subject_id,reason_code,amount_cents,explanation
$result.evidence | Select-Object -First 5 allocation_id,rule_id,account_evidence,explanation
Get-Content .\outputs\evaluation\evaluation.json -Raw | ConvertFrom-Json
```

## Acceptance assessment and remaining limits

| Criterion | Assessment |
|---|---|
| All previous tests passing | Met — all original 105 cases retained and pass |
| New tests passing | Met — 50 reconciliation cases pass |
| Ruff lint/format passing | Met |
| Actual full Phase 2 results | Met — 7,100 receipts, 7,200 invoices and all source representations processed |
| No known false automatic matches in default evaluation | Met — 0 incorrect allocations |
| No unexplained financial control discrepancy | Met — both controls zero, every balance checked |
| Deterministic reruns | Met — full default artifact bytes identical; separate hash-seed tests pass |
| Unresolved payments remain in review | Met — 245 uncertain receipts plus 98 residual-credit items retained |
| Every allocation has documented evidence | Met — 6,904 allocations and 6,904 linked evidence records |
| Actual metrics and differences reported | Met — precision, several coverage denominators, per-record balances and reason-label differences reported |

Limits are explicit: generated CSV/statement schemas only; no generic XLSX or
production-bank importer; issue-date invoice knowledge assumption; date-level
event ordering; synthetic approval fixtures; no new manual payment decisions;
no persisted posting/idempotency service. A correction requiring a new approved
release plan is rejected, not silently applied. A known outflow without its known
parent fails instead of inventing opening cash.

Ambiguous partial outflows conservatively withhold provisional applications in
an independent snapshot. This is not authorization to undo previously persisted
postings. Run timestamps are logical snapshot timestamps; actual wall-clock
execution times are not encoded as deterministic facts. No production accuracy,
tax certification, cross-platform matrix or benchmark is claimed.

The implementation is in memory. SQLite persistence, database-backed manual
resolution, the dashboard and Excel reporting remain unimplemented. Phase 3 is
complete in the verified scope; stop pending user approval before Phase 4.
