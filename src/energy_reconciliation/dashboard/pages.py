"""Seven dashboard views. Financial writes and exports are delegated to adapters."""

from collections import Counter
from dataclasses import asdict

import plotly.express as px
import streamlit as st

from energy_reconciliation.dashboard import analytics, exports, queries, services
from energy_reconciliation.dashboard.components import (
    PALETTE,
    chart,
    controls,
    euros,
    paged_table,
    period_picker,
    table,
)

PAGES = [
    "Executive Overview",
    "Payment Reconciliation",
    "Manual Review Workspace",
    "Customer Accounts",
    "Financial Analytics",
    "Audit and Financial Controls",
    "Reports and Exports",
]


def overview(report, context):
    values = analytics.kpis(report)
    metrics = [
        (
            "Adjusted receivables",
            "adjusted_receivables_cents",
            "Original invoices plus signed corrections.",
        ),
        (
            "Gross incoming payments",
            "gross_incoming_cents",
            "Receipts booked by the selected snapshot, before outflows.",
        ),
        ("Net cash", "net_cash_cents", "Gross receipts less refunds and chargebacks."),
        ("Net allocated cash", "net_allocated_cents", "Selected allocations less linked releases."),
        (
            "Unapplied cash",
            "unapplied_cents",
            "Effective cash not currently allocated, including credit and suspense.",
        ),
        (
            "Outstanding receivables",
            "outstanding_cents",
            "Adjusted receivables less active allocations.",
        ),
    ]
    for start in (0, 3):
        for col, (name, key, definition) in zip(
            st.columns(3), metrics[start : start + 3], strict=True
        ):
            col.metric(name, euros(values[key]), help=definition)
    a, b = st.columns(2)
    a.metric(
        "Reconciliation rate",
        f"{values['settlement_ratio']:.1%}" if values["settlement_ratio"] is not None else "n.a.",
        help="Net allocated / adjusted receivables. "
        "Value-weighted settlement ratio; not match accuracy.",
    )
    b.metric(
        "Unresolved review cases",
        values["unresolved_cases"],
        help="OPEN, IN_REVIEW and REOPENED cases; RESOLVED excluded.",
    )
    controls(report)
    st.caption(
        "Global selected-snapshot balances. Monthly charts show period cash "
        "activity and cumulative closing debt, restated at the displayed "
        "knowledge cutoff."
    )
    left, right = st.columns(2)
    with left:
        chart(
            report.tables["Monthly Reconciliation"],
            "month",
            "incoming_cents",
            "Monthly cash receipts (activity)",
        )
    with right:
        figure = px.pie(
            names=["Net allocated", "Unapplied"],
            values=[
                report.controls["net_allocated_cents"] / 100,
                report.controls["unapplied_cents"] / 100,
            ],
            hole=0.65,
            color_discrete_sequence=PALETTE,
            title="Net cash disposition (balance)",
        )
        figure.update_traces(hovertemplate="%{label}: € %{value:,.2f}<extra></extra>")
        figure.update_layout(template="plotly_white", height=330, margin={"t": 55, "b": 20})
        st.plotly_chart(figure, width="stretch")
    chart(
        report.tables["Monthly Reconciliation"],
        "month",
        "closing_outstanding_cents",
        "Outstanding receivables (closing balance)",
    )
    left, right = st.columns(2)
    with left:
        categories = Counter(
            r["reason_code"] for r in report.tables["Exception Queue"] if r["unresolved"]
        )
        chart(
            [{"category": k, "cases": v} for k, v in categories.items()],
            "category",
            "cases",
            "Unresolved exception categories",
            kind="bar",
            money=False,
        )
    with right:
        chart(
            [{"bucket": k, "outstanding_cents": v} for k, v in report.aging.items()],
            "bucket",
            "outstanding_cents",
            "Outstanding aging at snapshot date",
            kind="bar",
        )


def payments(report, context):
    rows = analytics.payment_records(report)
    search = st.text_input("Search payment, reference, customer or account", key="payment_search")
    dates = period_picker(report, "payment_dates")
    if len(dates) != 2:
        st.info("Choose both dates.")
        return
    with st.expander("Payment filters", expanded=True):
        a, b, c = st.columns(3)
        statuses = a.multiselect(
            "Status", sorted({r["status"] for r in rows}), key="payment_status"
        )
        rules = b.multiselect(
            "Matching rule", sorted({v for r in rows for v in r["rules"]}), key="payment_rules"
        )
        categories = c.multiselect(
            "Exception category",
            sorted({v for r in rows for v in r["exception_categories"]}),
            key="payment_categories",
        )
        a, b = st.columns(2)
        minimum = a.number_input("Minimum amount (EUR cents)", min_value=0, value=0, step=1)
        maximum = b.number_input(
            "Maximum amount (EUR cents)",
            min_value=0,
            value=max((r["received_cents"] for r in rows), default=0),
            step=1,
        )
    selected = analytics.filter_payments(
        rows,
        search=search,
        start=dates[0],
        end=dates[1],
        statuses=statuses,
        minimum=minimum,
        maximum=maximum,
        rules=rules,
        categories=categories,
    )
    st.caption(
        "Search includes validated and claimed account references. Only "
        "validated attribution establishes customer cash balances."
    )
    current = paged_table(
        selected,
        "payments",
        columns=[
            "payment_id",
            "bank_event_id",
            "customer_name",
            "contract_reference",
            "booked_on",
            "received_cents",
            "invoice_references",
            "status",
            "allocated_cents",
            "unapplied_cents",
            "rules",
        ],
    )
    payment_id = st.selectbox(
        "Inspect payment on this page",
        [r["payment_id"] for r in current],
        index=None,
        key="payment_detail",
    )
    if payment_id:
        detail = analytics.payment_detail(report, payment_id)
        with st.expander("Original payment and matching evidence", expanded=True):
            st.json(detail["payment"])
        st.subheader("Selected allocation history")
        table(detail["allocations"])
        st.subheader("Related invoices")
        table(detail["invoices"])
        st.subheader("Corrections and releases")
        table(detail["adjustments"])


def manual(report, context):
    path = context["path"]
    states = st.multiselect(
        "Case status",
        ["OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"],
        default=["OPEN", "IN_REVIEW", "REOPENED"],
        key="case_states",
    )
    search = st.text_input("Search case, payment or reason", key="case_search")
    cases = [
        r
        for r in report.tables["Exception Queue"]
        if r["status"] in states and (not search or search.casefold() in str(r).casefold())
    ]
    current = paged_table(
        cases, "cases", columns=["case_id", "payment_id", "amount_cents", "reason_code", "status"]
    )
    case_id = st.selectbox(
        "Review case", [r["case_id"] for r in current], index=None, key="review_case"
    )
    enabled = not context["read_only"] and context["current"]
    if not enabled:
        st.info("Financial changes are disabled in read-only mode or for a historical snapshot.")
    if case_id:
        row = next(r for r in current if r["case_id"] == case_id)
        st.write(f"{row['status']} · {row['reason_code']} · remaining {euros(row['amount_cents'])}")
        if context["current"]:
            view = queries.case_view(path, case_id)
            st.subheader("Original payment and current balance")
            st.json({"original": view["payment"], "balance": view["balance"]})
            st.subheader("Suggested invoice evidence — no automatic assignment")
            table(view["candidates"])
            table(view["candidate_balances"])
            with st.expander("Prior decisions and provenance"):
                st.json(view["decisions"])
                st.json(view["source_provenance"])
            if enabled and row["status"] != "RESOLVED":
                with st.form("allocation_form"):
                    invoice_id = st.selectbox(
                        "Choose invoice explicitly",
                        [
                            i["invoice_id"]
                            for i in view["candidate_balances"]
                            if i["outstanding_cents"] > 0
                        ],
                        index=None,
                    )
                    cents = st.text_input("Allocation amount (integer EUR cents)")
                    actor = st.text_input(
                        "Local demonstration actor", "SYNTHETIC_DEMO:dashboard-operator"
                    )
                    reason = st.text_input("Required allocation reason")
                    note = st.text_area("Optional allocation note")
                    if st.form_submit_button("Prepare allocation"):
                        if not cents.isdecimal():
                            st.error("Enter positive integer EUR cents.")
                        else:
                            try:
                                st.session_state["pending_action"] = services.prepare_allocation(
                                    path,
                                    report,
                                    case_id,
                                    invoice_id,
                                    int(cents),
                                    actor,
                                    reason,
                                    note,
                                )
                            except ValueError as exc:
                                st.error(str(exc))
            events, total = queries.audit_page(
                path, report.metadata["dataset_id"], search=row["payment_id"], size=25
            )
            st.subheader("Corresponding payment audit history")
            st.caption(f"Latest {len(events)} of {total} operational events across runs.")
            table(events)
        else:
            st.json(row)
    if enabled:
        reversed_ids = {o["reverses_decision_id"] for o in report.tables["Manual Decisions"]}
        earlier = [
            o["decision_id"]
            for o in report.tables["Manual Decisions"]
            if o["action"] == "allocate" and o["decision_id"] not in reversed_ids
        ]
        with st.expander("Reverse an earlier manual allocation", expanded=bool(earlier)):
            with st.form("reverse_form"):
                decision_id = st.selectbox("Earlier allocation decision", earlier, index=None)
                actor = st.text_input("Reversal actor", "SYNTHETIC_DEMO:dashboard-operator")
                reason = st.text_input("Required reversal reason")
                note = st.text_area("Optional reversal note")
                if st.form_submit_button("Prepare reversal"):
                    try:
                        st.session_state["pending_action"] = services.prepare_reversal(
                            path, report, decision_id, actor, reason, note
                        )
                    except ValueError as exc:
                        st.error(str(exc))
    action = st.session_state.get("pending_action")
    if action and enabled:
        st.subheader("Confirm financial change")
        st.json(asdict(action))
        with st.form("confirm_form"):
            approved = st.checkbox("I confirm this exact financial change", value=False)
            if st.form_submit_button("Confirm and apply", type="primary"):
                try:
                    outcome = services.confirm(
                        path,
                        action,
                        confirmed=approved,
                        expected_dataset_id=report.metadata["dataset_id"],
                    )
                    st.session_state.pop("pending_action", None)
                    st.session_state["notice"] = (
                        f"Applied {action.kind}. Decision {outcome['decision_id']}. Balances "
                        f"refreshed."
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc) + " Refresh and prepare again if the case or ledger changed.")
        if st.button("Discard prepared change"):
            st.session_state.pop("pending_action", None)
            st.rerun()
    if st.session_state.get("notice"):
        st.success(st.session_state["notice"])
        a, b, c = st.columns(3)
        a.metric("Resulting net allocated", euros(report.controls["net_allocated_cents"]))
        b.metric("Resulting unapplied", euros(report.controls["unapplied_cents"]))
        c.metric("Resulting outstanding", euros(report.controls["outstanding_cents"]))


def customers(report, context):
    search = st.text_input("Search customer, account or contract", key="customer_search")
    accounts = [
        r
        for r in report.tables["Customer Balances"]
        if not search or search.casefold() in str(r).casefold()
    ]
    paged_table(accounts, "accounts")
    by_id = {a["account_id"]: a for a in accounts}
    aid = st.selectbox(
        "Inspect account",
        list(by_id),
        index=None,
        key="account_detail",
        format_func=lambda value: (
            f"{by_id[value]['customer_name']} · {by_id[value]['contract_reference']} "
            f"· {by_id[value]['energy_type']}"
        ),
    )
    if aid:
        detail = analytics.account_detail(report, aid)
        a, b, c = st.columns(3)
        a.metric("Account allocated", euros(detail["account"]["allocated_cents"]))
        b.metric("Account outstanding", euros(detail["account"]["outstanding_cents"]))
        c.metric("Identified cash credit", euros(detail["account"]["identified_credit_cents"]))
        st.caption(
            "Invoice totals counted once. Payment history uses validated account "
            "attribution; credit is separate from debt."
        )
        st.subheader("Invoice history")
        table(detail["invoices"])
        st.subheader("Payment history")
        table(detail["payments"])
        st.subheader("Adjustments and releases")
        table(detail["adjustments"])


def financial(report, context):
    dates = period_picker(report, "analytics_dates")
    contract = st.selectbox(
        "Contract type", ["All", "electricity", "gas"], key="analytics_contract"
    )
    if len(dates) != 2:
        st.info("Choose both dates.")
        return
    data = analytics.chart_data(report, dates[0], dates[1], contract)
    st.info(
        "Filtered descriptive analytics. Global controls remain unchanged. "
        "Contract filters exclude cash without validated account attribution."
    )
    st.caption(
        "Monthly stocks are restated at the selected run's knowledge cutoff. "
        "Aging remains at the snapshot as-of date and uses the contract filter "
        "only. Timing uses one observation per actively allocated receipt and "
        "its earliest related invoice due date."
    )
    specs = [
        ("payment_count", "Monthly payment volume (unique receipts)", False),
        ("issued_cents", "Invoice issuance (period activity)", True),
        ("net_cash_activity_cents", "Net cash (period activity)", True),
        ("closing_outstanding_cents", "Outstanding receivables (closing stock)", True),
    ]
    for start in (0, 2):
        for col, (key, title, money) in zip(st.columns(2), specs[start : start + 2], strict=True):
            with col:
                chart(data["monthly"], "month", key, title, money=money)
    a, b = st.columns(2)
    with a:
        chart(
            [
                {"days_from_due": d, "receipts": n}
                for d, n in sorted(Counter(data["timing"]).items())
            ],
            "days_from_due",
            "receipts",
            "Payment timing (days from earliest due date)",
            kind="bar",
            money=False,
        )
    with b:
        chart(
            [{"bucket": k, "outstanding_cents": v} for k, v in data["aging"].items()],
            "bucket",
            "outstanding_cents",
            "Aging at snapshot date",
            kind="bar",
        )
    a, b = st.columns(2)
    with a:
        chart(
            [{"category": k, "cases": v} for k, v in data["exceptions"].items()],
            "category",
            "cases",
            "Unresolved exceptions by booking range",
            kind="bar",
            money=False,
        )
    with b:
        rows = [
            {"month": r["month"], "settlement_percent": r["settlement_ratio"] * 100}
            for r in data["monthly"]
            if r["settlement_ratio"] is not None
        ]
        chart(
            rows,
            "month",
            "settlement_percent",
            "Closing allocation / adjusted receivables (%)",
            money=False,
        )


def audit(report, context):
    controls(report)
    table(report.checks)
    with st.expander("Reconciliation run history and rule versions"):
        table(
            [
                r
                for r in context["catalog"]["runs"]
                if r["dataset_id"] == report.metadata["dataset_id"]
            ]
        )
        meta = queries.operations_metadata(context["path"], report.metadata["dataset_id"])
        table(meta["rules"])
        table(meta["imports"])
    with st.expander("Manual decisions and linked allocation releases"):
        table(report.tables["Manual Decisions"])
        table(
            [
                r
                for r in report.tables["Corrections and Reversals"]
                if r["kind"] == "allocation_release"
            ]
        )
    st.subheader("Operational audit events")
    st.caption(
        "Application-level traceability, not tamper-proof or authenticated. "
        "Operational timestamps are independent of the business as-of date and "
        "may reference other runs."
    )
    search = st.text_input(
        "Filter entity, payment, invoice, account, run or action", key="audit_search"
    )
    bounds = st.date_input("Audit UTC date range (optional)", value=[], key="audit_dates")
    page = st.number_input("Audit page", min_value=1, value=1, step=1)
    dates = dict(start=bounds[0], end=bounds[-1]) if len(bounds) == 2 else {}
    rows, total = queries.audit_page(
        context["path"], report.metadata["dataset_id"], search=search, page=page, **dates
    )
    st.caption(f"{total:,} matching audit events. Up to 50 per page.")
    table(rows)


def reports(report, context):
    st.write(
        "Exports use this exact persisted run and its authoritative Phase 5 financial controls."
    )
    st.code(report.metadata["run_id"])
    st.caption(
        "Choose a persisted date/run in the sidebar. New exports use unique "
        "directories and never silently overwrite files."
    )
    if st.button("Generate Excel workbook", type="primary"):
        with st.spinner("Generating database-backed workbook…"):
            path, payload, failures = exports.generate(
                context["path"],
                report.metadata["dataset_id"],
                report.metadata["run_id"],
                context["exports"],
            )
            st.session_state["excel_download"] = dict(
                run_id=report.metadata["run_id"], name=path.name, data=payload, failures=failures
            )
    stored = st.session_state.get("excel_download")
    if stored and stored["run_id"] == report.metadata["run_id"]:
        if stored["failures"]:
            st.error(
                "Report generated with failed controls. Inspect Control Checks; "
                "discrepancies are retained."
            )
        else:
            st.success("Workbook generated with passing controls.")
        st.download_button(
            "Download Excel workbook",
            stored["data"],
            file_name=stored["name"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click="ignore",
        )
    st.subheader("Filtered exception CSV")
    statuses = st.multiselect(
        "Export case statuses",
        ["OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"],
        default=["OPEN", "IN_REVIEW", "REOPENED"],
    )
    category = st.selectbox(
        "Export category",
        ["All"] + sorted({r["reason_code"] for r in report.tables["Exception Queue"]}),
    )
    search = st.text_input("Export case search")
    if st.button("Generate filtered exception CSV"):
        path, payload, _ = exports.generate(
            context["path"],
            report.metadata["dataset_id"],
            report.metadata["run_id"],
            context["exports"],
            kind="exceptions",
            statuses=statuses,
            category=None if category == "All" else category,
            search=search,
        )
        st.session_state["csv_download"] = dict(
            run_id=report.metadata["run_id"], name=path.name, data=payload
        )
    stored = st.session_state.get("csv_download")
    if stored and stored["run_id"] == report.metadata["run_id"]:
        st.download_button(
            "Download exception CSV",
            stored["data"],
            file_name=stored["name"],
            mime="text/csv",
            on_click="ignore",
        )


RENDERERS = dict(
    zip(PAGES, [overview, payments, manual, customers, financial, audit, reports], strict=True)
)
