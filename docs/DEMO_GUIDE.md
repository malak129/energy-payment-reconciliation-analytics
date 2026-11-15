# Safe portfolio demonstration

Allow a few minutes for generation, imports and exports. Use fictional data and
run from the repository root. The [README quick start](../README.md#quick-start-preserve-a-baseline-explore-a-working-copy)
contains the exact first-run PowerShell sequence, verified locally in Phase 8.

## 1. Establish a baseline

Generate `data/portfolio`, initialize/import/reconcile into
`data/portfolio-baseline.sqlite3`, and export its workbook. The fixed business
date is 2026-03-01 and known-at cutoff is the end of that day, so the initial
automatic run and its financial controls are reproducible.

Restore into the **new** `data/portfolio-working.sqlite3` using the README command.
The source baseline is validated read-only; an existing restore destination is
refused. Neither the private development primary nor its backup is needed or
distributed. Do not reset or delete an existing database to follow this guide;
use new source/output/database names for another demo.

## 2. Explore in Streamlit

```powershell
.\.venv\Scripts\python.exe -m streamlit run src/energy_reconciliation/dashboard/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false -- --database data/portfolio-working.sqlite3 --exports outputs/portfolio/ui
```

Open the local URL it prints. Keep loopback binding; do not click Deploy or use
a public tunnel. Add application argument `--read-only` to disable financial
edits. Stop the server with Ctrl+C in its terminal when finished.

| Page | Reviewer walkthrough |
|---|---|
| Executive Overview | Read six monetary KPIs, 343 unresolved items, 92.3% value-weighted settlement and passing controls |
| Payment Reconciliation | Search `SYN-EVENT-P-0002167`; compare receipt allocation with remaining invoice debt |
| Manual Review Workspace | Filter `missing_reference`, inspect source evidence and candidates without treating them as authority |
| Customer Accounts | Search `SYN-KONTO-000286`, select the fictional contract, compare debt with identified cash credit |
| Financial Analytics | Compare monthly receipts/activity with cumulative closing balances and inspect date/contract filters |
| Audit and Financial Controls | Review all exact-cent differences, immutable run identity and paginated operational history |
| Reports and Exports | Export the selected persisted run to Excel and generate a filtered exception CSV |

The initial default-source baseline has 343 OPEN cases and no runtime manual
decisions; screenshots use this fresh state. Historical development screenshots/
reports can include an already undone demonstration decision and REOPENED cases.
Both can have identical money totals while retaining different histories.

## 3. Demonstrate explicit manual allocation and undo

Use only the working copy, with `--read-only` omitted. Confirm the displayed
database path before preparing any financial action.

1. In Manual Review Workspace, inspect a missing-reference case and its source
   evidence. A candidate or equal amount is not sufficient authority in real work.
   This is an explicitly labelled synthetic demonstration choice.
2. Select one eligible invoice and a positive integer-cent amount within both
   outstanding invoice debt and available payment cash. Enter an actor such as
   `SYNTHETIC_DEMO:portfolio` and a reason explaining the demonstration.
3. Prepare the allocation. Review the staged payment/invoice, amount and reason;
   preparation alone changes no money. Check the separate confirmation checkbox
   and submit confirmation.
4. Observe the increased net allocation and reduced unapplied cash/debt. Net cash
   stays unchanged. The audit contains the decision and effect; a fully allocated
   case is RESOLVED and leaves the unresolved queue.
5. On that case, select its active allocation decision and prepare a linked
   reversal with an explicit reason. Review and separately confirm it.
6. Verify restored balances and REOPENED status. The original allocation and new
   release remain in history. Do not try to erase the earlier decision.

The UI handles one invoice per action; CLI/service supports explicit split targets.
If another action changes the revision, refresh and prepare again. Do not bypass a
stale or rejected confirmation. Historical selected runs cannot accept edits.

For an automated, safe-copy version using the existing supported report demo:

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation.reporting.demo --database data/portfolio-baseline.sqlite3 --output-dir outputs/portfolio/manual-demo
```

This requires a new output directory, creates its own review database, allocates/
undoes there, exports three stages, checks every monetary workbook detail cell
and verifies the input baseline bytes did not change. It selects an eligible
synthetic target explicitly; it is not an automatic matching rule.

## 4. Export and inspect

```powershell
.\.venv\Scripts\python.exe -m energy_reconciliation report excel --database data/portfolio-working.sqlite3 --output-dir outputs/portfolio/after-demo
.\.venv\Scripts\python.exe -m energy_reconciliation report exceptions --database data/portfolio-working.sqlite3 --output-dir outputs/portfolio/after-demo --status unresolved
```

Open the generated XLSX in a compatible viewer. The 12 sheets include source-linked
registers, monthly roll-forwards, account balances, manual decisions, audit and
controls. Three native charts and formulas accompany verified cached values;
native Microsoft Excel recalculation remains unverified. Dashboard exports use
new unique directories and do not overwrite prior reports.

## Troubleshooting

If Python is missing, install Python 3.12 and recreate the setup from the README.
For a port conflict, choose `--server.port 8508`; do not stop another application.
If a destination exists, choose a new path. An identical source-generation rerun
is safe, but export/restore intentionally refuse existing destinations. If a
schema or financial validation fails, retain the evidence and investigate instead
of editing original records or changing ground truth. See
[manual service commands](../MANUAL_REVIEW_GUIDE.md) for advanced operations.
