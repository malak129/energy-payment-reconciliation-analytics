# Scope and limitations

This is a personal synthetic portfolio project, developed with AI-assisted
engineering and verified through executed checks. It is not a real utility
deployment, an eins energie integration/endorsement, SAP experience or professional
employment experience.

## Business and input scope

Only EUR customer receivables and authored CSV/statement fixture schemas are
implemented. There is no production-bank/XLSX importer, live payment service,
supplier/purchasing workflow, FX, fees, interest, write-offs, direct-debit mandate
management, migration opening balances or double-entry general ledger. An optional
operator-invoice schema is not a purchasing engine.

Bills model monthly advances rather than actual metered consumption, annual
settlement or company tariffs. Tax and calendar assumptions are illustrative;
there is no tax/accounting certification or bank-holiday calendar. Customer names
are explicitly fictional; DE00 IBAN-shaped tokens deliberately have invalid
check digits and are not payment instructions.

## Evidence, dates and financial decisions

The generator balances scenarios for coverage, not empirical utility behavior.
100% allocation-row precision/coverage describes only the authored default oracle;
it cannot estimate real-world accuracy. Fifty-five oracle unknown-reference cases
are conservatively labelled ambiguous by the engine without any false allocation.

Invoice availability uses issue-date assumptions because actual receipt timestamps
are absent. Historical output selects persisted business/knowledge cutoffs; no
report-time rematching is performed. Late evidence requires an explicit supported
new run. Runtime operator decisions use the accepted evaluation date. Incompatible
new automatic results or unsafe cross-date neutralization fail closed rather than
silently rebase financial history. A general reviewed migration/rebase workflow
remains future work.

Manual UI allocations target one invoice at a time; the CLI/service can accept
explicit splits. Correction/outflow services exist, but dedicated UI forms for
all such operations are not implemented. Candidate evidence never substitutes for
operator authority or exact matching rules.

## Security and operations

Use a trusted local desktop and loopback only. Actor labels are not authentication;
there is no role management, encryption at rest, tamper-proof audit, hosted service
hardening or production multi-user concurrency guarantee. SQLite locks/version
tokens and tested transactions are bounded application safeguards. A malicious
filesystem owner can replace code/data outside that trust model.

Source files, operational audit and export details can contain local paths; do not
substitute real customer data or credentials. The public screenshot gallery uses
relative paths and fictional data only. Project Streamlit defaults apply when
launched from the repository root; retain explicit loopback arguments. Review
[security findings](../SECURITY_REVIEW.md) before modifying deployment assumptions.

## Reporting and performance

Excel output is verified structurally and numerically against SQLite with Python.
openpyxl reads values/caches; it does not recalculate formulas. Native Microsoft
Excel opening, recalculation, printing and interaction remain independently
unverified. There are three charts and native tables, but no native PivotTables.
Wide registers/evidence need scrolling. Excel/chart floats are display boundaries;
Python financial aggregation remains integer cents.

The Phase 7 default/750-customer timings are single observations on a specific
Windows machine under concurrent load. They are not latency guarantees, browser
benchmarks or evidence of unbounded scale. Audit pagination and small bounded
caches reduce repeated work at the tested scale. See [performance evidence](../PERFORMANCE_REPORT.md).

## Public reproducibility

The repository excludes generated data, databases/backups, original incident
artifacts, workbooks, logs, environments and caches. Generate your own fixtures
and run the portable release check. Historical verification reports deliberately
retain their dated results and may reference excluded development evidence; those
paths are not promised downloads. Current release status is authoritative in
[Phase 8 verification](../PHASE_8_VERIFICATION.md).

Local setup was verified on Windows/Python 3.12; remote matrix results are stated
only once GitHub reports them. Requirements use bounded version ranges, not an
immutable cross-platform lock. Future dependency changes require CI and schema
compatibility review. Possible future adapters/authentication/migrations are
roadmap ideas, not hidden or incomplete release capabilities.
