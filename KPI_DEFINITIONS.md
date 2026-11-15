# Financial reporting definitions

All financial populations are those of exactly one immutable persisted
reconciliation run, with its dataset/source version, business as-of date,
known-at cutoff and rules version retained in the workbook dictionary. No
historical run, duplicated statement representation or source approval fixture
adds cash to another run. No report calculation rematches payments.

| Metric | Authoritative population / definition |
|---|---|
| Original issued invoices I | Sum original_cents in selected invoice outcomes, linked to original invoice issued_on |
| Signed corrections C | Sum correction_cents in selected invoice outcomes; cross-check selected correction effects' signed_receivable_cents |
| Adjusted receivables G | I + C; original invoice amount is never overwritten |
| Gross receipts P | Sum received_cents of selected payment outcomes, one row per payment |
| Refunds R / chargebacks B | Positive magnitudes from selected adjustment effects with negative signed_cash_cents, by kind |
| Net cash N | P − R − B; invoice corrections have zero cash effect |
| Net allocated A | Selected allocations minus their selected linked releases; cross-check invoice and payment outcome allocated totals |
| Unapplied U | Selected payment unapplied balances; N − A |
| Outstanding O | Selected invoice outstanding balances; G − A |
| Identified credit | Unapplied balances only for selected payment outcomes with validated_account_id |
| Suspense | Unapplied balances without validated attribution; imported account claim alone is insufficient |
| Reconciliation rate / settlement ratio | A / G when G > 0. Value-weighted share of adjusted receivables settled; undefined (`n.a.`) at G=0 |
| Unresolved exception count | Number of review case rows with unresolved=true / state OPEN, IN_REVIEW or REOPENED. RESOLVED excluded |
| Aging | Outstanding debt bucketed by max(0, as_of − due_on) days: not overdue, 1–30, 31–60, 61–90, over 90; due today is not overdue |

The rate is not event-match precision, receipt count coverage or a ratio of
allocated cash to gross cash. Manual and automatic accepted applications both
settle receivables. Unresolved count counts cases, not unique customers or EUR;
do not treat summed case amounts as another cash population.

## Monthly activity and closing balances

All periods are calendar months, truncated at the selected as-of date for the
last period. Invoice issuance uses issued_on. Receipts, refunds and chargebacks
use booked_on, not value_on or invoice month. Corrections, allocations and
releases use effective_on. Original dates and bank value dates remain available
in the registers. Monthly reporting includes eligible records known to the
selected run, so later-known earlier-effective events restate earlier periods.

Let ΔI, ΔC, ΔP, ΔR, ΔB, ΔA+ and ΔL be period issuance, signed corrections,
receipts, refunds, chargebacks, allocation increases and allocation releases.

- Adjusted activity = ΔI + ΔC.
- Net cash activity = ΔP − ΔR − ΔB.
- Net allocation activity = ΔA+ − ΔL.
- Closing outstanding = opening outstanding + adjusted activity − net allocation activity.
- Closing unapplied = opening unapplied + net cash activity − net allocation activity.
- Closing adjusted/net cash/net allocated are cumulative activities through period end.

The dataset has no migrated opening balances. Before the first eligible month,
opening stocks are zero. Gaps have zero activity and carried closing balances.
Final closing amounts are checked against the selected snapshot's controls.
These are restated balances, not proof that the system knew every event at the
original historical month end. Use explicitly persisted historical known-at
runs for that different question. Sum activity columns; never sum stock columns
or monthly percentages.

## Account/customer aggregation and adjustments

Every invoice belongs to one account, which belongs to one customer. Customer
Balances aggregates invoice outcomes by account once, so split/combined payment
allocations do not duplicate a receipt. Identified unapplied credit uses accepted
payment attribution once. Suspense is not forced into an account or netted against
customer debt. Sum account rows by customer if a customer view is needed.

Correction effects carry signed debt and zero cash. Refund/chargeback effects
carry negative cash, zero debt-face change and their attributed released amount.
Separate allocation_release rows retain original allocation links. These release
amounts are descriptive references to the same release: sum only rows with
kind=allocation_release to count releases, never sum released amounts across all
adjustment kinds. Allocation Details contains one row per selected allocation
with original, released and active amounts. Manual undo retains original intent
and linked release/opposite correction instead of changing original transactions.

## Controls and interpretation

Core exact-cent checks are N = P − R − B, N = A + U, G = A + O, and identified
credit + suspense = U. The report independently aggregates detail rows and
compares them to stored run controls. Other comparisons reconcile customer,
invoice and payment allocation totals, correction effects and final month-end
stocks. Every control shows expected EUR, actual EUR, difference EUR and PASS/FAIL.
Discrepancies remain visible; CLI returns nonzero after exporting a report with
failed controls. It does not replace failures with zero or suppress a report.

Python uses integer cents without financial float arithmetic. Excel values are
numeric EUR; Excel formula comparisons round to two decimals. Caches are supplied
from independently calculated Python results. openpyxl does not recalculate.
Workbook formula rechecks and native application recalculation are distinct
from Python control validation. The workbook is a snapshot, not a substitute for
approved operations in SQLite or a posted double-entry general ledger.
