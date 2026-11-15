# Portfolio and interview notes

Present this under **Personal projects**, not employment. It was developed with
AI-assisted implementation and verification; explain the design, inspect the code
and reproduce the checks before making personal skill claims. There is no company
affiliation, endorsement, real customer data or SAP integration.

## CV project description

Energy Payment Reconciliation & Financial Analytics is a personal Python portfolio
project simulating customer payment operations for a fictional energy utility.
It combines conservative invoice matching, an auditable SQLite review workflow,
Excel reporting and a Streamlit dashboard, with exact-cent controls tested on
deterministic synthetic data.

## Three technical CV bullets

- Built an AI-assisted Python/SQLAlchemy portfolio simulation for invoice/payment
  reconciliation, retaining immutable source records, decision history and linked
  reversals in SQLite.
- Implemented Excel financial registers and a seven-page Streamlit dashboard for
  exception review, account drill-down and cash/receivables controls.
- Validated 6,904 automatic allocation rows with zero incorrect rows on a separate
  authored synthetic oracle, alongside regression, property and transaction tests;
  this is synthetic evaluation, not a real-world accuracy claim.

Use these only if you can demonstrate and explain the corresponding implementation.

## 30-second explanation

“I made a personal project around a payment-operations problem: explaining which
bills a receipt settles and keeping unclear cases visible. It uses fictional
energy bills and payments, exact-reference matching, SQLite history and a manual
review workflow where decisions can be reversed without erasing evidence. Excel
and Streamlit expose the same financial controls. I used AI assistance and then
tested the workflow, including duplicate imports, stale decisions and financial
restoration after undo.”

## Two-minute technical explanation

“The input is a deterministic fictional dataset with private/business customers,
electricity/gas contracts, monthly advances and scenarios such as partial receipts,
missing references, duplicate statements, corrections and chargebacks. Every event
has a stable identity, and imported values pass typed and cross-record checks.

“The engine allocates only with sufficient reference/account/date evidence. Equal
amounts or plausible names cannot authorize a match. For a combined reference, the
supported split must be explicit and exact. Uncertain cash remains in a queue.

“SQLite stores immutable source data, runs and financial effects. A current ledger
selects one run's effect memberships so historical snapshots do not double-count
cash. Manual decisions require a reason, explicit targets, a separate confirmation
and current revision tokens. Undo appends linked releases; it does not delete the
original allocation. Effects and accepted audit events commit in one transaction.

“Financial arithmetic uses integer cents. I check that net cash equals allocated
plus unapplied cash and that adjusted receivables equal allocated plus outstanding
debt, including per-invoice/payment limits and monthly roll-forwards. The separate
synthetic oracle is evaluated after matching, never used by it. The default fixture
produced 6,904 correct automatic allocation rows and zero incorrect, with remaining
uncertainty retained for review. That is an authored test result, not a production
accuracy estimate. AI-assisted development and explicit limitations are documented.

“Reports and all seven dashboard pages reuse these snapshots and services. The
project demonstrates careful payment operations and data analysis rather than
SAP, actual company data or production security.”

## Business problem and decisions to discuss

The business value is traceable exception handling: separate genuine unmatched
cash from identified credit, keep debt visible, avoid duplicate receipts and
explain why an allocation was accepted or reversed. These skills relate to payment
processing; supplier purchasing is outside this project's implemented scope.

| Decision | Why it matters |
|---|---|
| Integer cents, explicit rounding | Avoid hidden binary-float differences in controls |
| Separate cash outflows and allocation releases | Prevent double reduction of cash when debt reopens |
| Immutable records and linked undo | Preserve what was known and who labelled a manual decision |
| Selected-run memberships | Prevent historical effect rows being counted as new cash |
| Fixed seed, IDs and hashes | Reproduce inputs and diagnose changes |
| Independent oracle and adversarial tests | Challenge plausible but incorrect automatic matches |
| Read-only report projections | Keep presentation from quietly rematching or posting effects |

## Likely recruiter questions

**Did you use real utility data or work for eins energie?** No. All data is fictional;
the independent project implies no employment, endorsement or access.

**Does it connect to SAP or a bank?** No. It imports its documented generated
schemas. I would need an authorized adapter specification and additional testing
for any real integration.

**Why are cases left unresolved when the data generator knows the intended invoice?**
Generator intent is evaluation-only. Observable evidence may be insufficient, and
pretending otherwise would create an unjustified match.

**Does 100% mean the application is always accurate?** No. It means 6,904 produced
allocation rows match 6,904 expected rows on the fixed synthetic oracle. Real data
would have different distributions, missing fields and policies.

**What happens after an operator mistake?** A supported allocation can be reversed
by a new linked decision. Releases reopen debt and restore available cash without
changing net bank cash; original evidence remains.

**What did testing discover?** Among Phase 7 findings were read-only reset safety,
backup destination races, schema drift and historically unsafe cross-date rebase
neutralization. Phase 8 found an overly strict check for an empty Excel demo table.
Regressions retain those lessons; see the published verification reports.

**Is the audit tamper-proof?** No. It is application-level append-only history for
a trusted local synthetic demo, not a certified external audit boundary.

**Has Excel recalculated the formulas?** Native Microsoft Excel recalculation is
unverified. Python checked saved monetary cells, cached results and structure.

**What would you improve next?** Reviewed real-format adapters, access control,
explicit migration/rebase procedures and broader compatibility/performance tests,
under clear authorized requirements. None is claimed as already implemented.

**How was AI used?** AI assisted implementation, documentation and adversarial
verification. The repository records executed checks and limitations so its claims
can be examined rather than accepted from a generated description.
