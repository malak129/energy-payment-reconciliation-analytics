# Phase 7 requirements-to-tests matrix

Prepared before implementation. Primary financial state is read-only throughout
Phase 7. All destructive, adversarial and financial workflow tests use isolated
temporary databases or newly generated benchmark/demo databases.

| Requirement | Existing coverage | Independent Phase 7 challenge / planned evidence |
|---|---|---|
| A financial conservation and account totals | engine/persistence/report tests | Raw SQLite source/effect recomputation, per-payment/invoice bounds, account totals and monthly roll-forward without production KPI functions |
| B source identity, links and hashes | generation/ingestion/schema tests | Complete logical table hashes vs clean Phase 4 backup; source bytes/hash/oracle isolation; selected memberships and incident delta audit |
| Phase 6 recovery | dashboard argv regression | Independent primary/clean-backup comparison, preserved incident decision/undo and exact zero net effect; subprocess routing test with primary read-only sentinel |
| C matching stress and adversarial evidence | test_reconciliation scenarios | Randomized and intentionally misleading references, shuffled event order, historical knowledge and unsafe release/correction combinations |
| D randomized properties | deterministic fixture tests | Hypothesis seeded scenarios for conservation, bounds, deterministic replay and reversal; randomized isolated transactional workflows |
| E database and workflow safety | stale/concurrent/rollback/backup tests | Live schema tampering, read-only destructive adapters, overwrite races, rollback faults and original source/run immutability |
| F dashboard | seven AppTest pages and manual workflow | Actual service routing under inherited CLI/environment arguments, read-only restrictions, pending confirmation scope and export identity |
| G Excel | sheet/table/chart/format tests | Independent raw SQLite-to-workbook sums and chart/formula/range inspection; attempt native Excel opening/recalculation |
| H local security/privacy | explicit actor/SQLAlchemy/local launch | SQL injection probes, path/symlink/overwrite/reset boundaries, synthetic identifiers, secrets/log/dependency review and loopback configuration |
| I performance/robustness | Phase 6 snapshot timings | Timed generation/import/reconciliation/export/dashboard/query stages and larger isolated dataset with environment/memory context |
| J end-to-end | prior demos | New isolated generation → import → reconcile → explicit allocation → undo → Excel/CSV → Streamlit → repeat import/run; primary digest unchanged |
| K oracle metrics | independent evaluation command | Reevaluate automatic baseline against unmodified Phase 2 oracle with explicit precision/coverage denominators |
| L evidence and readiness | historical verification reports | QUALITY_REPORT, SECURITY_REVIEW, PERFORMANCE_REPORT and PHASE_7_VERIFICATION with actual results and unresolved limits |

## Executed evidence

Final suite: 249 passed, including all 232 unchanged previous tests. The above
planning matrix was created before fixes; this section records actual evidence.

| Requirement | Executed tests / artifact | Result and scope |
|---|---|---|
| A | `tools/phase7_audit.py`, `independent-audit.json` | Exact raw-source/effect arithmetic; payment/invoice/account/customer balances, credit/suspense, seven monthly flow categories and closing stocks; full-knowledge baseline/incident fixtures |
| B | raw audit; existing generation/ingestion/persistence tests | SQLite/FK integrity, source/file/result hashes, ENGINE and LEDGER identity reconstruction, original primary/backup equality; all 33 source/oracle files unchanged |
| Incident | raw primary/clean/incident comparison; `test_demo_isolates_inherited_cli_arguments_and_checks_target` | No incident decisions in primary; preserved incident allocation+undo net zero; original audit IDs retained in separate incident artifact |
| C | `tests/test_reconciliation.py`; `test_plausible_amount_and_reference_never_suffice`; random order/reversal tests | Existing exact/combined/partial/over/ambiguous/late/duplicate/refund/correction/cutoff/malformed cases plus randomized challenges |
| D | `test_random_cash_conservation_order_and_determinism`, `test_random_reversal_independent_cash_and_debt`, misleading-reference and transaction properties | Four explicit seeds; 252 examples across four properties, no weakened bounds |
| E | existing fault/concurrency/history/backup tests; new read-only reset, empty restore, destination race, live drift and cross-date tests | Rejected operations preserve money; independent direct replay challenge rejects historically invalid rebase |
| F | all `tests/test_dashboard.py`; replacement and dataset confirmation tests; acceptance AppTest seven pages | Real adapters, state/cache/filter/empty/read-only/manual workflows; inherited argv regression retained; primary digest unchanged |
| G | `tests/test_reporting.py`; `phase7_workbook_audit.py`; acceptance workbook check | 12 sheets, 3 charts/6 ranges, 56 formulas, 600 accounts and 8 independent summary values; historical/format/export tests pass; native Excel attempt incomplete |
| H | `test_sql_metacharacters_are_literal_case_ids`, three CSV prefix cases, loopback/default and overwrite checks; dependency audit | No known vulnerabilities in auditable distributions after pip upgrade; editable project skipped; path/symlink review is bounded, not exhaustive hostile-filesystem testing |
| I | acceptance timings/process memory; server health probe | Actual default and 1.5x customer workload; single-run contention-qualified measurements |
| J | `tools/phase7_acceptance.py`, `acceptance.json`, server probe | Complete isolated source → import → run → allocate → reverse → Excel/CSV → seven pages → duplicate import/run; exact primary digest preserved |
| K | explicit evaluation CLI, `outputs/phase7/oracle/evaluation.json`; coverage JSON | 6904 correct / 0 incorrect; 100% precision/expected-row coverage; no balance differences; coverage denominators documented |
| L | five requested Phase 7 Markdown reports plus README update | Findings, fixes, commands, limitations and readiness documented |
| M | final test log, Ruff, financial audit, oracle, acceptance and hash evidence | Acceptance met for the bounded local synthetic demonstration; native Excel limitation explicitly retained |

Existing tests were preserved; no historical test was removed to improve counts.
The full audit script deliberately rejects earlier-known-at and local runtime
correction/outflow cases; those are covered by independent small arithmetic
properties and existing engine/workflow scenarios, not misrepresented as part of
the full-source audit. No exhaustive security penetration test, browser performance
study or production capacity certification was performed.
