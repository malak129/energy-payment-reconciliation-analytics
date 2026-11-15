# Financial controls and interpretation

All accepted business arithmetic uses exact integer EUR cents. Invoice/payment
identities, allocations, releases and knowledge cutoffs are preserved in immutable
run snapshots. Displayed euros are presentation values, not the arithmetic oracle.

## Conservation equations

| Symbol | Definition |
|---|---|
| I | Original issued invoices |
| C | Signed approved receivable corrections |
| P | Gross accepted incoming receipts |
| R / B | Refund / chargeback cash-outflow magnitudes |
| A | Selected allocations less their linked releases |
| N | Net cash: P − R − B |
| G | Adjusted receivables: I + C |
| U | Unapplied cash: N − A |
| O | Outstanding receivables: G − A |

Check `N = A + U`, `G = A + O` and `G − N = O − U`. Identified account credit
plus unidentified suspense equals U. Debt and credit stay separate; balances
are not netted across unrelated customers or assigned to an unverified account claim.

For each payment, cumulative outflows cannot exceed receipts and active allocation
must remain between zero and available cash. For each invoice, adjusted face is
nonnegative and active allocation cannot exceed it. Each allocation's cumulative
releases cannot exceed its original amount. Aggregate equality alone cannot prove
these entity-level bounds.

## Worked synthetic default

| Quantity | EUR |
|---|---:|
| Original invoices | 2,244,345.84 |
| Signed corrections | −2,718.72 |
| Adjusted receivables G | 2,241,627.12 |
| Incoming receipts | 2,186,839.60 |
| Refunds | 2,055.36 |
| Chargebacks | 27,899.24 |
| Net cash N | 2,156,885.00 |
| Net allocated A | 2,067,991.84 |
| Unapplied U | 88,893.16 |
| Outstanding O | 173,635.28 |

Thus `2,156,885.00 = 2,067,991.84 + 88,893.16` and
`2,241,627.12 = 2,067,991.84 + 173,635.28`. Both exact-cent differences are zero.
There are 26 report checks including source/detail/control comparisons, account
and credit attribution and final monthly closing stocks.

A 96.54 EUR manual allocation, followed by a linked full undo, moves A/U/O by
equal opposite amounts and restores all baseline control fields. Neither action
changes N. A refund/chargeback reduces N once; any required allocation release
reopens debt without subtracting cash again. A signed correction changes G and
O, not N. Unsupported/ambiguous release plans are rejected.

## Month-end and historical controls

```text
Closing outstanding = opening outstanding + issued + signed corrections
                      - allocation increases + releases
Closing unapplied = opening unapplied + incoming - refunds - chargebacks
                    - allocation increases + releases
```

Use issue dates for bills, booking dates for cash and effective dates for
allocations/releases/corrections. Monthly flows are additive; closing stocks are
cumulative and must not be summed as activity. The last reporting period can be
partial. A report selects a persisted as-of/known-at snapshot; it never invents
history by filtering today's final balances. Incompatible cross-date rebase
neutralization fails closed.

## Evaluation is a separate question

Matching precision counts correct automatic allocation rows divided by produced
automatic rows. Expected-row coverage divides correct rows by oracle-expected
rows. Both are 6904/6904 on the default fixture. The 92.3% dashboard ratio is
allocated value/adjusted receivable value; it is neither metric. 343 review items
include 98 residual-credit items plus 245 unresolved positive-cash receipts.
The separate evaluator refuses manually judged ledgers as automatic baselines.

Read [business rules](../BUSINESS_RULES.md), [KPI definitions](../KPI_DEFINITIONS.md)
and the [independent QA report](../QUALITY_REPORT.md) for detailed scope. These
controls validate a fictional receivables simulation, not statutory accounts,
tax compliance or a double-entry general ledger.
