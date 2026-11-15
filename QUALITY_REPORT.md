# Phase 7 quality report — 15 November 2026

Scope: local synthetic-data portfolio demonstration only. No Phase 8 work,
publication, financial policy expansion, or changes to evaluation ground truth.

## Independent financial audit

`tools/phase7_audit.py` uses read-only native SQLite, source records, selected-run
allocation/release memberships and separate integer arithmetic. Production KPI
functions are not its financial oracle. It compares resulting entity balances,
account/customer debt, identified credit and month-end stocks with persisted
outcomes and report projections. It rejects unsupported early knowledge cutoffs
and runtime correction/outflow fixtures instead of pretending to audit them.
Those paths have separate engine/workflow tests. Historical cutoff tests are
therefore test evidence, not coverage by this full-knowledge audit script.

| Independently recomputed quantity | Integer cents |
|---|---:|
| Original invoices | 224,434,584 |
| Signed approved corrections | -271,872 |
| Adjusted receivables | 224,162,712 |
| Gross incoming payments | 218,683,960 |
| Refunds | 205,536 |
| Chargebacks | 2,789,924 |
| Net cash | 215,688,500 |
| Net allocated cash | 206,799,184 |
| Unapplied cash | 8,889,316 |
| Outstanding receivables | 17,363,528 |
| Identified account credit | 219,854 |
| Unidentified suspense | 8,669,462 |

Both conservation differences are zero:
`215688500 = 206799184 + 8889316`;
`224162712 = 206799184 + 17363528`.
Every selected invoice/payment balance matches separate arithmetic. Cumulative
releases never exceed their original allocation. Every independently accumulated
month-end entity stock is nonnegative; report month-end cash/debt stocks agree.
Account rows are unique and customer debt is grouped through source account links.
All 37,703 immutable source payload hashes and stored source-file bytes verify;
foreign-key and SQLite integrity checks pass. ENGINE input/config hashes and UUID5
run identifiers are independently reconstructed, and every stored result hash verifies.

## Phase 6 incident recovery

The primary and clean Phase 4 backup are byte-identical, including case statuses,
head/revision, source identities, historical runs, decisions and audit history.
SHA256: `d6674a691b1d07880e90b86ade2ad554e29030bc179b2b0fb386957720608158`.
The newly preserved Phase 7 baseline backup has the same digest.

The separate incident copy remains at
`outputs/phase6-recovery/audited-incident.sqlite3`; it was not erased or rewritten.
It contains incident allocation `syn_decision_efdf4bb7be2f5c498ed0a961078325d9`
and explicit undo `syn_decision_e90e0dcc666b4cf6b4fa9b802382d16a`.
The primary contains neither incident decision. Its legitimate Phase 4 allocation
and undo remain, each 9,654 cents. Incident-copy manual allocation and release
totals are each 19,308 cents, including the original legitimate pair. Its current
account/customer debt, unapplied cash and allocated cash equal the clean baseline.
All baseline audit IDs remain in the incident copy; that copy has 38,022 audit events.
Restoration intentionally means incident-only history is retained separately,
not injected back into the restored primary.

## Defects and fixes

| Defect / root cause | Implemented fix | Regression evidence |
|---|---|---|
| Read-only `reset` could unlink the database before recreation failed | Reject before backup/delete | `test_readonly_reset_cannot_delete_database` |
| Restore initialized an empty purported backup, mutating its source | Validate source using a read-only Database | `test_restore_empty_source_does_not_initialize_it` |
| Backup exists-check raced with another writer | Exclusive destination reservation with `xb`, read-only source | `test_backup_concurrent_same_destination_no_overwrite` |
| Version stamp accepted missing live triggers/indexes | Compare actual tables/indexes/triggers with versioned DDL | `test_live_schema_drift_is_rejected` |
| Pending action could follow a replacement database at the same path | Bind confirmation to file identity and selected dataset | replacement and selected-dataset confirmation tests |
| Rebase neutralized cross-date allocation/correction undo pairs despite historical effects | Fail closed when incompatible neutralization spans effective dates | `test_cross_date_neutralization_cannot_create_negative_month_end` |
| Default Streamlit bind was not constrained by project configuration | Repository loopback default, telemetry disabled | `test_streamlit_defaults_to_loopback` |
| CSV escape checked only the first character | Check formula prefixes after whitespace and initial control characters | three whitespace/control-prefix cases |

The first seven targeted regression cases failed before their six underlying fixes
(`outputs/phase7/initial-probes.txt`) and passed afterward. The cross-date defect
does not change allocation policy: incompatible source activation now fails instead
of storing a financially misleading historical projection. Same-date neutral pairs
remain supported. A reviewed retroactive rebase workflow is outside current scope.

## Randomized and adversarial testing

Hypothesis seeds: 20261115 (100 cash/order examples), 20261116 (80 reversal
examples), 20261117 (60 misleading reference examples), 20261118 (12 isolated
transaction workflows). Database persistence is disabled in Hypothesis settings;
fresh UUID-named temporary databases isolate each workflow example. The workflow
property tests duplicate requests, bounded partial allocations, rejected oversized
corrections, explicit undo, duplicate imports and stable reconciliation reruns.
The statistics rerun recorded 100/80/60/12 passing examples, zero failing
examples, and 16 invalid generation attempts in the first property. Raw evidence
is `outputs/phase7/property-statistics.txt`; invalid draws are not financial failures.
Existing rollback fault injection, two-operator concurrency, foreign-key, stale
revision, historical immutability and routing tests remain unchanged.

Shrinking exposed mistakes in the new QA harness: the minimum `face=1,
amounts=[1]` exposed an incorrect fixture accessor; `divisor=1` exposed comparison
of response metadata (`reused`) rather than stable financial identity. These were
harness errors, not financial failures. Other harness corrections used the actual
`case.version`, `decision_id`, lowercase CSV field and 64-bit Windows memory API
contracts. No invariant or ground-truth expectation was relaxed.

## Oracle and report evidence

The unchanged Phase 2 oracle reports 6,904 correct automatic allocations, zero
incorrect/missing allocations and 98 correct releases with zero incorrect releases.
Precision is correct/all actual automatic allocation rows: 6904/6904 = 100%.
Expected-allocation coverage is correct/all expected rows: 6904/6904 = 100%.
Active matched payment coverage is 6757/7100 = 95.1690%; ever matched payment
coverage is 6855/7100 = 96.5493%. There are 343 review items and 245 positive-cash
unmatched payments; these counts have different definitions. There are zero
individual invoice/payment balance differences. Fifty-five oracle unknown-reference
cases are conservatively labelled ambiguous; this category distinction causes no
incorrect allocations. No fuzzy names or amount similarity authorize a match.

Independent workbook inspection checks eight summary amounts against the raw audit,
all 600 account debt rows without duplicate aggregation, all table boundaries,
12 worksheets, three charts with six valid source ranges, and 56 formulas with
valid references and populated caches. This corrects reliance on historical
unverified formula-count claims. The existing reporting suite additionally checks
currency/date types, partial periods, historical snapshots, manual visibility,
formula injection, export reproducibility and all control rows.

Native Excel was activated and its local file picker reached. Subsequent actions
encountered minimized-window and detected-user-input guards. Workbook opening and
native recalculation could not be verified; cached XML inspection is not native
Excel calculation. The verification copy remains `outputs/phase7/native-excel.xlsx`.

Final execution counts, performance, coverage and readiness are recorded in
PHASE_7_VERIFICATION.md, PERFORMANCE_REPORT.md and machine evidence under
`outputs/phase7`. Security limits are recorded in SECURITY_REVIEW.md.
