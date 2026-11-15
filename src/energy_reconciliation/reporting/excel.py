"""Business-facing XLSX and exception CSV from validated integer-cent report data."""

import csv
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from energy_reconciliation.reporting.data import Report

EUR = '#,##0.00 "€";[Red](#,##0.00) "€";0.00 "€"'
DATE = "dd.mm.yyyy"
SHEETS = [
    "Executive Summary",
    "Monthly Reconciliation",
    "Invoice Register",
    "Payment Register",
    "Allocation Details",
    "Exception Queue",
    "Customer Balances",
    "Corrections and Reversals",
    "Audit Trail",
    "Control Checks",
    "Data Dictionary and KPIs",
    "Manual Decisions",
]
EMPTY_COLUMNS = {
    "Monthly Reconciliation": [
        "month",
        "period_end",
        "issued_cents",
        "corrections_cents",
        "incoming_cents",
        "refund_cents",
        "chargeback_cents",
        "allocation_increases_cents",
        "releases_cents",
        "adjusted_activity_cents",
        "net_cash_activity_cents",
        "net_allocation_activity_cents",
        "opening_outstanding_cents",
        "opening_unapplied_cents",
        "closing_adjusted_cents",
        "closing_net_cash_cents",
        "closing_allocated_cents",
        "closing_unapplied_cents",
        "closing_outstanding_cents",
    ],
    "Invoice Register": [
        "invoice_id",
        "reference",
        "account_id",
        "customer_id",
        "issued_on",
        "due_on",
        "original_cents",
        "correction_cents",
        "adjusted_cents",
        "allocated_cents",
        "outstanding_cents",
        "status",
        "overdue_days",
        "aging_bucket",
    ],
    "Payment Register": [
        "payment_id",
        "bank_event_id",
        "reference",
        "claimed_account_id",
        "validated_account_id",
        "booked_on",
        "value_on",
        "received_cents",
        "reversed_cents",
        "net_cash_cents",
        "allocated_cents",
        "unapplied_cents",
        "status",
        "classification",
        "evidence",
    ],
    "Allocation Details": [
        "allocation_id",
        "payment_id",
        "invoice_id",
        "account_id",
        "effective_on",
        "allocated_cents",
        "released_cents",
        "net_allocated_cents",
        "decision_id",
        "origin_run_id",
        "confidence",
        "reason",
    ],
    "Exception Queue": [
        "case_id",
        "payment_id",
        "bank_event_id",
        "payment_reference",
        "booked_on",
        "category",
        "amount_cents",
        "status",
        "unresolved",
        "reason_code",
        "reason",
        "candidate_evidence",
        "review_history",
        "resolution_details",
    ],
    "Customer Balances": [
        "customer_id",
        "customer_name",
        "account_id",
        "contract_reference",
        "energy_type",
        "original_cents",
        "correction_cents",
        "adjusted_cents",
        "allocated_cents",
        "outstanding_cents",
        "identified_credit_cents",
    ],
    "Corrections and Reversals": [
        "effect_id",
        "original_record_id",
        "kind",
        "effective_on",
        "invoice_id",
        "payment_id",
        "account_id",
        "signed_cash_cents",
        "signed_receivable_cents",
        "released_cents",
        "decision_id",
        "reverses_record_id",
        "reason",
    ],
    "Audit Trail": [
        "event_id",
        "occurred_at_utc",
        "actor",
        "action",
        "entity_type",
        "entity_id",
        "payment_id",
        "invoice_id",
        "account_id",
        "run_id",
        "reason",
        "details_json",
    ],
    "Manual Decisions": [
        "decision_id",
        "action",
        "case_id",
        "effective_on",
        "created_at_utc",
        "actor",
        "reason",
        "note",
        "reverses_decision_id",
        "details_json",
    ],
}
DEFINITIONS = {
    "Reconciliation rate": (
        "Net allocated / adjusted receivables (A/G). Value-weighted settlement "
        "ratio; n.a. when G=0. Not match accuracy."
    ),
    "Unresolved exceptions": (
        "Count of selected-run review cases with status OPEN, IN_REVIEW or "
        "REOPENED. Resolved cases excluded."
    ),
    "Monthly basis": (
        "Restated effective-date activity using the selected run's fixed known-at "
        "cutoff. Not separate contemporaneous month-end runs."
    ),
    "Period activity": (
        "Issued invoices by issued_on, receipts/outflows by booked_on, "
        "corrections/allocations/releases by effective_on. Final month may be "
        "partial."
    ),
    "Closing balances": (
        "Cumulative eligible activity through period_end. Never sum closing balances across months."
    ),
    "Aging": (
        "Outstanding invoice amount by max(0, as_of - due_on): not overdue, 1–30, "
        "31–60, 61–90, over 90 days. Due today is not overdue."
    ),
    "Customer balances": (
        "One row per account, linked to one customer. Sum account rows once. "
        "Credits remain separate from receivable debt; suspense excluded from "
        "customer attribution."
    ),
    "Adjustment signs": (
        "Signed receivable correction changes debt only. Refund/chargeback signed "
        "cash is negative. Allocation release reopens debt/unapplied cash, with no "
        "second cash outflow."
    ),
    "Release amounts": (
        "Correction/reversal effect rows show attributed releases, and "
        "allocation_release rows show the same releases individually. Filter "
        "kind=allocation_release to total releases once."
    ),
    "Audit scope": (
        "All dataset application events through export, including other or later "
        "runs. Filter Run id. Audit rows are traceability, never financial "
        "postings."
    ),
    "Historical case status": (
        "Selected snapshot determines unresolved membership. Current head uses live "
        "workflow state; older runs derive status from that snapshot and eligible "
        "decisions, without future cache state."
    ),
    "Excel precision": (
        "Python calculations/controls use integer cents. Excel stores numeric EUR "
        "in binary floating point; formulas ROUND differences to two decimals. "
        "Export is a static snapshot, not an editable ledger."
    ),
    "Formula verification": (
        "Python independently validates every exported control. XlsxWriter supplies "
        "cached results. openpyxl inspects formulas/values but does not calculate "
        "them."
    ),
    "PivotTables": (
        "Normalized native tables are PivotTable-ready. No native PivotTable is "
        "created. In Excel select a table, Insert > PivotTable > New Worksheet, "
        "then choose rows and sum EUR fields."
    ),
    "Dictionary sheet name": (
        "Data Dictionary and KPI Definitions exceeds Excel's 31-character limit; "
        "the tab is named Data Dictionary and KPIs."
    ),
    "Empty tables": (
        "Empty exports retain headers and one blank native-table body row. The "
        "blank row is not a business record."
    ),
}


def label(key):
    return key.removesuffix("_cents").replace("_", " ").capitalize() + (
        " (EUR)" if key.endswith("_cents") else ""
    )


def sum_formula(report, sheet, key):
    col = xl_col_to_name(EMPTY_COLUMNS[sheet].index(key))
    return f"SUM('{sheet}'!{col}6:{col}{max(6, 5 + len(report.tables[sheet]))})"


def write_workbook(report: Report, path: Path):
    with xlsxwriter.Workbook(path, {"strings_to_formulas": False, "strings_to_urls": False}) as wb:
        wb.set_properties(
            {
                "title": "Synthetic energy reconciliation",
                "author": "SYNTHETIC portfolio simulation",
                "created": datetime(2000, 1, 1),
                "comments": report.metadata["run_id"],
            }
        )
        wb.set_calc_mode("auto")
        styles = {
            "body": wb.add_format({"font_name": "Arial", "font_size": 10, "valign": "vcenter"}),
            "wrap": wb.add_format(
                {"font_name": "Arial", "font_size": 10, "text_wrap": True, "valign": "top"}
            ),
            "title": wb.add_format(
                {"font_name": "Arial", "font_size": 16, "bold": True, "font_color": "#17324D"}
            ),
            "note": wb.add_format(
                {"font_name": "Arial", "font_size": 10, "italic": True, "font_color": "#586776"}
            ),
            "header": wb.add_format(
                {
                    "font_name": "Arial",
                    "font_size": 10,
                    "bold": True,
                    "bg_color": "#17324D",
                    "font_color": "white",
                    "text_wrap": True,
                    "valign": "vcenter",
                    "align": "center",
                }
            ),
            "money": wb.add_format({"font_name": "Arial", "font_size": 10, "num_format": EUR}),
            "date": wb.add_format({"font_name": "Arial", "font_size": 10, "num_format": DATE}),
            "percent": wb.add_format(
                {"font_name": "Arial", "font_size": 10, "italic": True, "num_format": "0.0%"}
            ),
            "fail": wb.add_format({"bg_color": "#FCE4D6", "font_color": "#9C2222", "bold": True}),
            "warn": wb.add_format({"bg_color": "#FFF2CC", "font_color": "#805D13"}),
        }
        sheets = {name: wb.add_worksheet(name) for name in SHEETS}
        for name, ws in sheets.items():
            ws.hide_gridlines(2)
            ws.set_tab_color("#17324D" if name == "Executive Summary" else "#8B9BAA")
            ws.set_default_row(19)
            ws.set_zoom(90)
            ws.write(
                0,
                0,
                "Energy reconciliation" if name == "Executive Summary" else name,
                styles["title"],
            )
            ws.write(
                2,
                0,
                f"SYNTHETIC. As of {report.metadata['as_of']:%d.%m.%Y}. Currency EUR",
                styles["note"],
            )
            ws.set_landscape()
            ws.set_paper(9)
            ws.fit_to_pages(1, 0)
            ws.set_header("&LSynthetic energy utility&RReconciliation report")
            ws.set_footer("&L" + report.metadata["run_id"] + "&RPage &P of &N")
        for name, rows in report.tables.items():
            write_table(
                sheets[name], rows, EMPTY_COLUMNS[name], "T_" + name.replace(" ", ""), styles
            )
        sheets["Monthly Reconciliation"].write(
            1,
            0,
            "Period activity and cumulative closing balances. "
            "Final month ends at the selected as-of date.",
            styles["note"],
        )
        sheets["Audit Trail"].write(1, 0, report.metadata["audit_scope"], styles["note"])
        sheets["Corrections and Reversals"].write(
            1,
            0,
            "Total releases using kind=allocation_release only. "
            "Other rows attribute the same release to its adjustment.",
            styles["note"],
        )
        write_summary(wb, sheets["Executive Summary"], report, styles)
        write_controls(sheets["Control Checks"], report, styles)
        dictionary = [{"term": k, "definition": str(v)} for k, v in report.metadata.items()]
        dictionary.extend({"term": k, "definition": v} for k, v in DEFINITIONS.items())
        for name, cols in EMPTY_COLUMNS.items():
            for col in cols:
                meaning = (
                    "Numeric EUR, exported from exact integer cents."
                    if col.endswith("_cents")
                    else "Typed calendar date."
                    if col.endswith("_on") or col in ("month", "period_end")
                    else "Stable synthetic identifier."
                    if col.endswith("_id")
                    else "Snapshot source/evidence field."
                )
                dictionary.append({"term": f"{name}: {label(col)}", "definition": meaning})
        write_table(
            sheets["Data Dictionary and KPIs"],
            dictionary,
            ["term", "definition"],
            "T_Dictionary",
            styles,
        )
        sheets["Data Dictionary and KPIs"].set_column(0, 0, 48)
        sheets["Data Dictionary and KPIs"].set_column(1, 1, 115)
        sheets["Data Dictionary and KPIs"].set_default_row(45)


def write_table(ws, rows, columns, table_name, styles):
    if len(rows) > 1_048_570:
        raise ValueError("Excel row limit exceeded; no rows were silently dropped")
    ws.freeze_panes(5, min(2, len(columns)))
    ws.repeat_rows(0, 4)
    ws.set_row(4, 42)
    defs = []
    for col, key in enumerate(columns):
        fmt = (
            styles["money"]
            if key.endswith("_cents")
            else styles["date"]
            if (key.endswith("_on") or key in ("month", "period_end"))
            else styles["body"]
        )
        width = (
            20
            if key.endswith("_cents")
            else 15
            if fmt == styles["date"]
            else 42
            if key.endswith("_id")
            else 26
        )
        if key in ("customer_name", "actor"):
            width = 46
        elif key.endswith("_utc"):
            width = 42
        if key in (
            "reason",
            "evidence",
            "definition",
            "details_json",
            "candidate_evidence",
            "review_history",
            "resolution_details",
            "note",
        ):
            width = 64
            fmt = styles["wrap"]
        ws.set_column(col, col, width, fmt)
        defs.append({"header": label(key), "header_format": styles["header"], "format": fmt})
        for index, row in enumerate(rows, 5):
            value = row.get(key)
            if value is None:
                continue
            if key.endswith("_cents"):
                if type(value) is not int:
                    raise ValueError(f"Non-integer money in {table_name}.{key}")
                ws.write_number(index, col, float(Decimal(value) / 100), fmt)
            elif isinstance(value, date):
                ws.write_datetime(index, col, datetime.combine(value, datetime.min.time()), fmt)
            elif isinstance(value, str):
                if len(value) > 32767:
                    raise ValueError(
                        f"Excel cell length exceeded in {table_name}.{key}; export refused"
                    )
                ws.write_string(index, col, value, fmt)
            else:
                ws.write(index, col, value, fmt)
    ws.add_table(
        4,
        0,
        max(5, 4 + len(rows)),
        len(columns) - 1,
        {"name": table_name, "columns": defs, "style": "Table Style Medium 2", "banded_rows": True},
    )
    if not rows:
        ws.write(1, 0, "No records in selected snapshot", styles["note"])
    if "status" in columns:
        col = columns.index("status")
        ws.conditional_format(
            5,
            col,
            max(5, 4 + len(rows)),
            col,
            {
                "type": "text",
                "criteria": "containing",
                "value": "REOPENED",
                "format": styles["warn"],
            },
        )
    ws.print_area(0, 0, max(5, 4 + len(rows)), len(columns) - 1)


def write_summary(wb, ws, report, styles):
    ws.set_column("A:A", 36)
    ws.set_column("B:B", 23)
    ws.set_column("C:C", 3)
    ws.set_column("D:L", 11)
    ws.write(3, 0, "Knowledge cutoff (UTC)", styles["note"])
    ws.write(3, 1, report.metadata["known_at_utc"], styles["note"])
    metrics = [
        ("Adjusted receivables", "adjusted_receivables_cents"),
        ("Gross incoming payments", "gross_incoming_cents"),
        ("Refunds", "refund_cents"),
        ("Chargebacks", "chargeback_cents"),
        ("Net cash", "net_cash_cents"),
        ("Net allocated cash", "net_allocated_cents"),
        ("Unapplied cash", "unapplied_cents"),
        ("Outstanding receivables", "outstanding_cents"),
    ]
    ws.write_row(5, 0, ["Financial position", "EUR"], styles["header"])
    for r, (title, key) in enumerate(metrics, 6):
        ws.write(r, 0, title, styles["body"])
        ws.write_number(r, 1, float(Decimal(report.controls[key]) / 100), styles["money"])
    ws.write(15, 0, "Settlement ratio (allocated / AR)", styles["body"])
    g, a = report.controls["adjusted_receivables_cents"], report.controls["net_allocated_cents"]
    ws.write_formula(15, 1, '=IF(B7=0,"n.a.",B12/B7)', styles["percent"], a / g if g else "n.a.")
    unresolved = sum(r["unresolved"] for r in report.tables["Exception Queue"])
    ws.write(17, 0, "Unresolved review cases", styles["body"])
    ws.write_number(17, 1, unresolved, styles["body"])
    ws.write(18, 0, "Resolved cases in register", styles["body"])
    ws.write_number(18, 1, len(report.tables["Exception Queue"]) - unresolved, styles["body"])
    ws.write_row(22, 0, ["Outstanding aging", "EUR"], styles["header"])
    for r, (bucket, cents) in enumerate(report.aging.items(), 23):
        ws.write(r, 0, bucket, styles["body"])
        ws.write_number(r, 1, float(Decimal(cents) / 100), styles["money"])
    distribution = {}
    for row in report.tables["Exception Queue"]:
        if row["unresolved"]:
            distribution[row["reason_code"]] = distribution.get(row["reason_code"], 0) + 1
    distribution = sorted(distribution.items(), key=lambda x: (-x[1], x[0]))
    ws.write_row(32, 0, ["Unresolved category", "Cases"], styles["header"])
    for r, (reason, count) in enumerate(distribution, 33):
        ws.write(r, 0, reason.replace("_", " "), styles["body"])
        ws.write_number(r, 1, count, styles["body"])
    specs = [("bar", "Outstanding by aging (EUR)", "Executive Summary", 23, 27, 0, 1, "D23")]
    if report.tables["Monthly Reconciliation"]:
        specs.insert(
            0,
            (
                "line",
                "Monthly gross cash receipts (EUR)",
                "Monthly Reconciliation",
                5,
                4 + len(report.tables["Monthly Reconciliation"]),
                0,
                4,
                "D6",
            ),
        )
    if distribution:
        specs.append(
            (
                "bar",
                "Unresolved cases by category",
                "Executive Summary",
                33,
                32 + len(distribution),
                0,
                1,
                "D40",
            )
        )
    for kind, title, source, first, last, category, value, anchor in specs:
        chart = wb.add_chart({"type": kind})
        chart.add_series(
            {
                "name": title,
                "categories": [source, first, category, last, category],
                "values": [source, first, value, last, value],
                "line": {"color": "#287C8E", "width": 2},
                "fill": {"color": "#287C8E"},
                "smooth": False,
            }
        )
        chart.set_title({"name": title, "name_font": {"name": "Arial", "size": 12}})
        chart.set_legend({"none": True})
        chart.set_chartarea({"border": {"none": True}})
        chart.set_x_axis(
            {
                "num_font": {"name": "Arial", "size": 10},
                **(
                    {
                        "date_axis": True,
                        "num_format": "mmm-yy",
                        "major_unit": 2,
                        "major_unit_type": "months",
                    }
                    if kind == "line"
                    else {"min": 0, "num_format": "#,##0"}
                ),
            }
        )
        chart.set_y_axis(
            {"min": 0, "num_format": "#,##0"}
            if kind == "line"
            else {"num_font": {"name": "Arial", "size": 10}}
        )
        chart.set_size({"width": 680, "height": 285})
        ws.insert_chart(anchor, chart)
    ws.conditional_format(
        "B18", {"type": "cell", "criteria": ">", "value": 0, "format": styles["warn"]}
    )
    ws.print_area("A1:L55")
    ws.fit_to_pages(1, 2)


def write_controls(ws, report, styles):
    # Formula rechecks remain readable beside independently calculated Python results.
    ws.set_column(0, 0, 67)
    ws.set_column(1, 4, 23)
    ws.set_column(5, 6, 18)
    ws.write_row(
        4,
        0,
        [
            "Control equation / comparison",
            "Database expected (EUR)",
            "Export actual (EUR)",
            "Python difference (EUR)",
            "Excel difference (EUR)",
            "Python status",
            "Excel recheck",
        ],
        styles["header"],
    )
    refs = {
        "original_invoice_cents": ("Invoice Register", "original_cents"),
        "signed_correction_cents": ("Invoice Register", "correction_cents"),
        "adjusted_receivables_cents": ("Invoice Register", "adjusted_cents"),
        "gross_incoming_cents": ("Payment Register", "received_cents"),
        "net_cash_cents": ("Payment Register", "net_cash_cents"),
        "net_allocated_cents": ("Allocation Details", "net_allocated_cents"),
        "unapplied_cents": ("Payment Register", "unapplied_cents"),
        "outstanding_cents": ("Invoice Register", "outstanding_cents"),
        "identified_credit_cents": ("Customer Balances", "identified_credit_cents"),
    }
    for r, check in enumerate(report.checks, 5):
        ws.write(r, 0, check["check"], styles["body"])
        for col, key in [(1, "expected_cents"), (2, "actual_cents"), (3, "difference_cents")]:
            ws.write_number(r, col, float(Decimal(check[key]) / 100), styles["money"])
        key = check["check"].removeprefix("Database = export: ")
        if key in refs:
            ws.write_formula(
                r,
                2,
                "=" + sum_formula(report, *refs[key]),
                styles["money"],
                check["actual_cents"] / 100,
            )
        ws.write_formula(
            r, 4, f"=ROUND(C{r + 1}-B{r + 1},2)", styles["money"], check["difference_cents"] / 100
        )
        ws.write(r, 5, check["status"], styles["body"])
        ws.write_formula(r, 6, f'=IF(E{r + 1}=0,"PASS","FAIL")', styles["body"], check["status"])
    ws.add_table(
        4,
        0,
        4 + len(report.checks),
        6,
        {
            "name": "T_Controls",
            "style": "Table Style Medium 2",
            "columns": [
                {"header": x, "header_format": styles["header"]}
                for x in [
                    "Control equation / comparison",
                    "Database expected (EUR)",
                    "Export actual (EUR)",
                    "Python difference (EUR)",
                    "Excel difference (EUR)",
                    "Python status",
                    "Excel recheck",
                ]
            ],
        },
    )
    ws.set_row(4, 42)
    ws.freeze_panes(5, 1)
    ws.conditional_format(
        5,
        5,
        4 + len(report.checks),
        6,
        {"type": "text", "criteria": "containing", "value": "FAIL", "format": styles["fail"]},
    )


def write_exception_csv(report, path, status="unresolved"):
    allowed = {"all", "unresolved", "OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"}
    if status not in allowed:
        raise ValueError("Unsupported exception status filter")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=EMPTY_COLUMNS["Exception Queue"], lineterminator="\n"
        )
        writer.writeheader()
        for row in report.tables["Exception Queue"]:
            if (
                status == "all"
                or status == "unresolved"
                and row["unresolved"]
                or row["status"] == status
            ):
                # CSV has no cell types. Escape spreadsheet formula prefixes in text only.
                writer.writerow(
                    {
                        k: "'" + v
                        if isinstance(v, str)
                        and (
                            v.lstrip().startswith(("=", "+", "-", "@"))
                            or v.startswith(("\t", "\r", "\n"))
                        )
                        else v
                        for k, v in row.items()
                    }
                )


def export(report: Report, output_dir: Path, *, kind="excel", status="unresolved") -> Path:
    if kind not in ("excel", "exceptions"):
        raise ValueError("Export kind must be excel or exceptions")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".xlsx" if kind == "excel" else f"-{status}.csv"
    destination = (
        output_dir / f"{kind}-{report.metadata['as_of']}-{report.metadata['run_id']}{suffix}"
    )
    if destination.exists():
        raise FileExistsError(
            f"Report already exists: {destination}; choose a new output directory"
        )
    # Build completely before exclusive publication. Never replace another export.
    with tempfile.TemporaryDirectory(prefix=".report-", dir=output_dir) as temporary:
        pending = Path(temporary) / ("report" + suffix)
        if kind == "excel":
            write_workbook(report, pending)
        else:
            write_exception_csv(report, pending, status)
        with destination.open("xb") as stream:
            try:
                with pending.open("rb") as source:
                    shutil.copyfileobj(source, stream)
            except BaseException:
                stream.close()
                destination.unlink()
                raise
    return destination
