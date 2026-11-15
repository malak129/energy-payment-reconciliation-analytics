"""Phase 6 full-data UI demonstration; financial changes occur only on a new backup."""

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import openpyxl
from streamlit.testing.v1 import AppTest

from energy_reconciliation.dashboard import analytics, queries
from energy_reconciliation.dashboard.components import euros
from energy_reconciliation.dashboard.pages import PAGES
from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.reporting.data import read_report
from energy_reconciliation.reporting.demo import inspect_workbook


@contextmanager
def environment(path, exports, read_only):
    values = dict(
        ENERGY_RECONCILIATION_DB=str(path),
        ENERGY_RECONCILIATION_EXPORTS=str(exports),
        ENERGY_RECONCILIATION_READ_ONLY="1" if read_only else "0",
    )
    original = {k: os.environ.get(k) for k in values}
    original_argv = sys.argv
    # AppTest runs in this interpreter. Its app must not inherit this demo's CLI flags.
    sys.argv = [str(Path(__file__).with_name("app.py"))]
    os.environ.update(values)
    try:
        yield
    finally:
        sys.argv = original_argv
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def widget(app, kind, label):
    return next(w for w in app.get(kind) if w.label == label)


def valid(app):
    ensure(not app.exception, str([e.message for e in app.exception]))
    ensure(not app.error, str([e.value for e in app.error]))


def require_database(app, expected):
    actual = widget(app, "text_input", "Local SQLite database").value
    ensure(
        Path(actual).resolve() == Path(expected).resolve(),
        "UI database differs from intended demonstration target; aborting",
    )


def demonstrate(path, output, reference=None):
    ensure(not output.exists(), "Demonstration requires a new output directory")
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    queries.invalidate()
    t = perf_counter()
    original = queries.snapshot(path)
    cold = perf_counter() - t
    t = perf_counter()
    queries.snapshot(path)
    warm = perf_counter() - t
    t = perf_counter()
    _, audit_count = queries.audit_page(path, original.metadata["dataset_id"])
    audit_seconds = perf_counter() - t
    script = str(Path(__file__).with_name("app.py"))
    page_results = {}
    with environment(path, output / "primary-exports", True):
        t = perf_counter()
        app = AppTest.from_file(script, default_timeout=120).run()
        require_database(app, path)
        initial_seconds = perf_counter() - t
        valid(app)
        metrics = {m.label: m.value for m in app.metric}
        for label, key in [
            ("Adjusted receivables", "adjusted_receivables_cents"),
            ("Gross incoming payments", "gross_incoming_cents"),
            ("Net cash", "net_cash_cents"),
            ("Net allocated cash", "net_allocated_cents"),
            ("Unapplied cash", "unapplied_cents"),
            ("Outstanding receivables", "outstanding_cents"),
        ]:
            ensure(metrics[label] == euros(original.controls[key]), "UI KPI differs from SQLite")
        ensure(
            int(metrics["Unresolved review cases"]) == analytics.kpis(original)["unresolved_cases"],
            "Queue mismatch",
        )
        for page in PAGES:
            t = perf_counter()
            app.sidebar.radio[0].set_value(page).run()
            valid(app)
            page_results[page] = dict(passed=True, seconds=round(perf_counter() - t, 4))
    reference_identical = None
    if reference:
        wb = openpyxl.load_workbook(reference, read_only=True, data_only=True)
        try:
            reference_identical = all(
                wb["Executive Summary"].cell(i, 2).value == original.controls[key] / 100
                for i, key in [
                    (7, "adjusted_receivables_cents"),
                    (8, "gross_incoming_cents"),
                    (11, "net_cash_cents"),
                    (12, "net_allocated_cents"),
                    (13, "unapplied_cents"),
                    (14, "outstanding_cents"),
                ]
            )
            ensure(reference_identical, "Phase 5 Excel reference differs")
        finally:
            wb.close()
    clone = output / "review-demo.sqlite3"
    db = Database(path, read_only=True)
    try:
        db.backup(clone)
    finally:
        db.close()
    case = candidate = None
    for row in original.tables["Exception Queue"]:
        if row["unresolved"] and row["reason_code"] == "missing_reference":
            view = queries.case_view(clone, row["case_id"])
            eligible = next(
                (
                    i
                    for i in view["candidate_balances"]
                    if i["outstanding_cents"] >= row["amount_cents"]
                ),
                None,
            )
            if eligible:
                case, candidate = row, eligible
                break
    ensure(case is not None, "No eligible explicit demo case")
    with environment(clone, output / "ui-exports", False):
        app = AppTest.from_file(script, default_timeout=120).run()
        require_database(app, clone)
        app.sidebar.radio[0].set_value("Manual Review Workspace").run()
        widget(app, "text_input", "Search case, payment or reason").set_value(case["case_id"]).run()
        widget(app, "selectbox", "Review case").select(case["case_id"]).run()
        ensure(
            widget(app, "selectbox", "Choose invoice explicitly").value is None,
            "Implicit invoice selection",
        )
        widget(app, "selectbox", "Choose invoice explicitly").select(candidate["invoice_id"])
        widget(app, "text_input", "Allocation amount (integer EUR cents)").set_value(
            str(case["amount_cents"])
        )
        widget(app, "text_input", "Required allocation reason").set_value(
            "Explicit full-data dashboard demonstration on a safe database copy"
        )
        widget(app, "button", "Prepare allocation").click().run()
        valid(app)
        ensure(queries.snapshot(clone).controls == original.controls, "Prepare changed money")
        widget(app, "checkbox", "I confirm this exact financial change").check()
        widget(app, "button", "Confirm and apply").click().run()
        valid(app)
        resolved = queries.snapshot(clone)
        decision = next(
            o
            for o in resolved.tables["Manual Decisions"]
            if o["action"] == "allocate" and o["reason"].startswith("Explicit full-data dashboard")
        )
        ensure(
            analytics.kpis(resolved)["unresolved_cases"]
            == analytics.kpis(original)["unresolved_cases"] - 1,
            "Resolution count differs",
        )
        widget(app, "selectbox", "Earlier allocation decision").select(decision["decision_id"])
        widget(app, "text_input", "Required reversal reason").set_value(
            "Undo full-data dashboard demonstration"
        )
        widget(app, "button", "Prepare reversal").click().run()
        widget(app, "checkbox", "I confirm this exact financial change").check()
        widget(app, "button", "Confirm and apply").click().run()
        valid(app)
        final = queries.snapshot(clone)
        ensure(final.controls == original.controls, "Undo did not restore every control")
        app.sidebar.radio[0].set_value("Reports and Exports").run()
        widget(app, "button", "Generate Excel workbook").click().run()
        valid(app)
        ensure(len(app.get("download_button")) >= 1, "Missing Excel download control")
        workbook = next((output / "ui-exports").rglob("*.xlsx"))
        inspection = inspect_workbook(workbook, read_report(clone))
        widget(app, "button", "Generate filtered exception CSV").click().run()
        valid(app)
        ensure(len(app.get("download_button")) == 2, "Missing CSV download control")
    unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
    ensure(unchanged, "Primary database changed")
    evidence = dict(
        synthetic=True,
        primary_database_sha256=original_hash,
        primary_unchanged=unchanged,
        initial_controls=original.controls,
        final_controls=final.controls,
        pages=page_results,
        primary_metrics=metrics,
        phase5_excel_reference_matches=reference_identical,
        cold_snapshot_seconds=round(cold, 4),
        warm_snapshot_seconds=round(warm, 4),
        audit_page_seconds=round(audit_seconds, 4),
        audit_events=audit_count,
        initial_apptest_seconds=round(initial_seconds, 4),
        case_id=case["case_id"],
        invoice_id=candidate["invoice_id"],
        allocated_cents=case["amount_cents"],
        allocation_decision_id=decision["decision_id"],
        explicit_demo_selection=True,
        queue_counts=[analytics.kpis(r)["unresolved_cases"] for r in (original, resolved, final)],
        workbook=str(workbook.resolve()),
        workbook_inspection=inspection,
        download_controls_verified=True,
        browser_download_verified_separately=False,
    )
    (output / "verification.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/phase4-demo.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/phase6-demo"))
    parser.add_argument("--reference-workbook", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(demonstrate(args.database, args.output_dir, args.reference_workbook), indent=2)
    )


if __name__ == "__main__":
    main()
