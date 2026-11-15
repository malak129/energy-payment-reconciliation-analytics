"""Filters, drill-down and chart preparation over one authoritative Report."""

from collections import Counter, defaultdict
from datetime import date

from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.reporting.data import monthly_rollforward


def kpis(report):
    c = report.controls
    return {
        **c,
        "settlement_ratio": c["net_allocated_cents"] / c["adjusted_receivables_cents"]
        if c["adjusted_receivables_cents"]
        else None,
        "unresolved_cases": sum(r["unresolved"] for r in report.tables["Exception Queue"]),
        "failed_controls": sum(r["status"] != "PASS" for r in report.checks),
    }


def payment_records(report):
    accounts = {a["account_id"]: a for a in report.tables["Customer Balances"]}
    invoices = {i["invoice_id"]: i for i in report.tables["Invoice Register"]}
    refs = defaultdict(set)
    reasons = defaultdict(set)
    for a in report.tables["Allocation Details"]:
        refs[a["payment_id"]].add(invoices[a["invoice_id"]]["reference"])
    for e in report.tables["Exception Queue"]:
        if e["unresolved"]:
            reasons[e["payment_id"]].add(e["reason_code"])
    rows = []
    for p in report.tables["Payment Register"]:
        account = accounts.get(p["validated_account_id"] or p["claimed_account_id"], {})
        rows.append(
            {
                **p,
                "customer_id": account.get("customer_id"),
                "customer_name": account.get("customer_name"),
                "contract_reference": account.get("contract_reference"),
                "invoice_references": ", ".join(sorted(refs[p["payment_id"]])),
                "rules": tuple(
                    sorted({line.split(":", 1)[0] for line in p["evidence"].splitlines()})
                )
                or ("No accepted match",),
                "exception_categories": tuple(sorted(reasons[p["payment_id"]])),
            }
        )
    return rows


def filter_payments(
    rows,
    *,
    search="",
    start=None,
    end=None,
    statuses=(),
    minimum=0,
    maximum=None,
    account=None,
    rules=(),
    categories=(),
):
    ensure(start is None or end is None or start <= end, "Date range is reversed")
    ensure(
        type(minimum) is int
        and minimum >= 0
        and (maximum is None or type(maximum) is int and maximum >= minimum),
        "Amount range must be ordered integer cents",
    )
    query = search.strip().casefold()
    return [
        p
        for p in rows
        if (
            not query
            or query
            in " ".join(
                str(p.get(k) or "")
                for k in (
                    "payment_id",
                    "bank_event_id",
                    "reference",
                    "validated_account_id",
                    "claimed_account_id",
                    "customer_id",
                    "customer_name",
                    "contract_reference",
                    "invoice_references",
                )
            ).casefold()
        )
        and (start is None or p["booked_on"] >= start)
        and (end is None or p["booked_on"] <= end)
        and (not statuses or p["status"] in statuses)
        and p["received_cents"] >= minimum
        and (maximum is None or p["received_cents"] <= maximum)
        and (
            not account
            or account in (p["validated_account_id"], p["claimed_account_id"], p["customer_id"])
        )
        and (not rules or set(rules).intersection(p["rules"]))
        and (not categories or set(categories).intersection(p["exception_categories"]))
    ]


def paginate(rows, page=1, size=25):
    ensure(
        type(page) is int and page >= 1 and type(size) is int and 1 <= size <= 100,
        "Invalid pagination",
    )
    return rows[(page - 1) * size : page * size], len(rows)


def payment_detail(report, payment_id):
    payment = next(
        (p for p in report.tables["Payment Register"] if p["payment_id"] == payment_id), None
    )
    ensure(payment is not None, "Payment not present in selected snapshot")
    allocations = [a for a in report.tables["Allocation Details"] if a["payment_id"] == payment_id]
    invoice_ids = {a["invoice_id"] for a in allocations}
    return dict(
        payment=payment,
        allocations=allocations,
        invoices=[i for i in report.tables["Invoice Register"] if i["invoice_id"] in invoice_ids],
        adjustments=[
            a for a in report.tables["Corrections and Reversals"] if a["payment_id"] == payment_id
        ],
    )


def account_detail(report, account_id):
    account = next(
        (a for a in report.tables["Customer Balances"] if a["account_id"] == account_id), None
    )
    ensure(account is not None, "Account not present in selected snapshot")
    invoices = [i for i in report.tables["Invoice Register"] if i["account_id"] == account_id]
    # Financial account history uses validated attribution, never an unvalidated claim.
    payments = [
        p for p in report.tables["Payment Register"] if p["validated_account_id"] == account_id
    ]
    ids = {p["payment_id"] for p in payments}
    return dict(
        account=account,
        invoices=invoices,
        payments=payments,
        adjustments=[
            a
            for a in report.tables["Corrections and Reversals"]
            if a["account_id"] == account_id or a["payment_id"] in ids
        ],
    )


def chart_data(report, start: date, end: date, contract="All"):
    """Restated effective-date activity; reuse the reporting roll-forward, no matching."""
    ensure(
        start <= end <= report.metadata["as_of"], "Choose an ordered range within the snapshot date"
    )
    account_ids = {
        a["account_id"]
        for a in report.tables["Customer Balances"]
        if contract == "All" or a["energy_type"] == contract
    }
    invoices = {
        i["invoice_id"]: i
        for i in report.tables["Invoice Register"]
        if i["account_id"] in account_ids
    }
    payments = {
        p["payment_id"]: p
        for p in report.tables["Payment Register"]
        if contract == "All" or p["validated_account_id"] in account_ids
    }
    events = []
    for i in invoices.values():
        events += [(i["issued_on"], "issued_cents", i["original_cents"])]
    for p in payments.values():
        events += [(p["booked_on"], "incoming_cents", p["received_cents"])]
    allocations = [
        a
        for a in report.tables["Allocation Details"]
        if a["payment_id"] in payments and a["invoice_id"] in invoices
    ]
    for a in allocations:
        events += [(a["effective_on"], "allocation_increases_cents", a["allocated_cents"])]
    for a in report.tables["Corrections and Reversals"]:
        when = a["effective_on"]
        if a["kind"] == "correction" and a["invoice_id"] in invoices:
            events += [(when, "corrections_cents", a["signed_receivable_cents"])]
        elif a["kind"] in ("refund", "chargeback") and a["payment_id"] in payments:
            events += [(when, a["kind"] + "_cents", -a["signed_cash_cents"])]
        elif (
            a["kind"] == "allocation_release"
            and a["payment_id"] in payments
            and a["invoice_id"] in invoices
        ):
            events += [(when, "releases_cents", a["released_cents"])]
    flows = defaultdict(Counter)
    before_start = Counter()
    for when, key, amount in events:
        if when <= end:
            flows[when.replace(day=1)][key] += amount
            if when.replace(day=1) == start.replace(day=1) and when < start:
                before_start[key] += amount
    monthly = [r for r in monthly_rollforward(flows, end) if r["period_end"] >= start]
    if monthly:
        r, b = monthly[0], before_start
        r["opening_outstanding_cents"] += (
            b["issued_cents"]
            + b["corrections_cents"]
            - b["allocation_increases_cents"]
            + b["releases_cents"]
        )
        r["opening_unapplied_cents"] += (
            b["incoming_cents"]
            - b["refund_cents"]
            - b["chargeback_cents"]
            - b["allocation_increases_cents"]
            + b["releases_cents"]
        )
        for key, amount in b.items():
            r[key] -= amount
        r["adjusted_activity_cents"] = r["issued_cents"] + r["corrections_cents"]
        r["net_cash_activity_cents"] = (
            r["incoming_cents"] - r["refund_cents"] - r["chargeback_cents"]
        )
        r["net_allocation_activity_cents"] = r["allocation_increases_cents"] - r["releases_cents"]
    for r in monthly:
        r["period_start"] = max(start, r["month"])
        r["payment_count"] = sum(
            r["period_start"] <= p["booked_on"] <= r["period_end"] for p in payments.values()
        )
        r["settlement_ratio"] = (
            r["closing_allocated_cents"] / r["closing_adjusted_cents"]
            if r["closing_adjusted_cents"]
            else None
        )
    due = defaultdict(list)
    for a in allocations:
        if a["net_allocated_cents"] > 0:
            due[a["payment_id"]].append(invoices[a["invoice_id"]]["due_on"])
    timing = [
        (payments[pid]["booked_on"] - min(days)).days
        for pid, days in due.items()
        if start <= payments[pid]["booked_on"] <= end
    ]
    aging = Counter()
    for i in invoices.values():
        aging[i["aging_bucket"]] += i["outstanding_cents"]
    exceptions = Counter(
        e["reason_code"]
        for e in report.tables["Exception Queue"]
        if e["unresolved"] and e["payment_id"] in payments and start <= e["booked_on"] <= end
    )
    return dict(monthly=monthly, timing=timing, aging=dict(aging), exceptions=dict(exceptions))
