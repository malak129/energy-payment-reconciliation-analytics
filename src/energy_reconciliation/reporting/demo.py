"""Real Phase 4 database export, then explicit resolution/undo on a NEW backup copy."""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import openpyxl

from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reporting.data import read_report
from energy_reconciliation.reporting.excel import EMPTY_COLUMNS, SHEETS, export

ACTOR = "SYNTHETIC_DEMO:report-demonstration"


def inspect_workbook(path, report):
    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        ensure(wb.sheetnames == SHEETS, "Workbook sheet inventory differs")
        ensure(len(wb["Executive Summary"]._charts) == 3, "Expected three genuine Excel charts")
        tables = {}
        for name, columns in EMPTY_COLUMNS.items():
            ws = wb[name]
            table = next(iter(ws.tables.values()))
            # Empty Excel tables reserve row 6 in their range but can have no
            # materialized cells there. Both shapes are valid after read-back.
            records = len(report.tables[name])
            ensure(ws.max_row in {5 + records, max(6, 5 + records)}, "Incorrect row count")
            ensure(len(columns) == ws.max_column, "Incorrect register column count")
            tables[name] = dict(records=len(report.tables[name]), table_range=table.ref)
            for index, record in enumerate(report.tables[name], 6):
                for col, key in enumerate(columns, 1):
                    if key.endswith("_cents"):
                        actual = Decimal(str(ws.cell(index, col).value)) * 100
                        ensure(actual == record[key], f"Exported cents differ: {name}.{key}")
        formulas = sum(
            cell.data_type == "f"
            for name in ("Executive Summary", "Control Checks")
            for row in wb[name]
            for cell in row
        )
        ensure(formulas > 20, "Missing analytical formulas")
        ensure(all(c["status"] == "PASS" for c in report.checks), "Financial discrepancy")
    finally:
        wb.close()
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        unresolved = sum(r["unresolved"] for r in report.tables["Exception Queue"])
        ensure(wb["Executive Summary"]["B18"].value == unresolved, "Wrong unresolved summary")
        for row in wb["Control Checks"].iter_rows(min_row=6):
            ensure(
                row[3].value == 0 and row[5].value == row[6].value == "PASS",
                "Failed exported control",
            )
    finally:
        wb.close()
    return dict(
        worksheets=SHEETS,
        tables=tables,
        chart_count=3,
        formula_count=formulas,
        passed_controls=len(report.checks),
        unresolved=unresolved,
    )


def demonstration(database_path, output_dir):
    output_dir = Path(output_dir)
    ensure(not output_dir.exists(), "Demo requires a new output directory; choose another name")
    original_hash = hashlib.sha256(Path(database_path).read_bytes()).hexdigest()
    initial = read_report(database_path)
    workbook = export(initial, output_dir)
    csv_path = export(initial, output_dir, kind="exceptions")
    inspection = inspect_workbook(workbook, initial)
    clone = output_dir / "review-demo.sqlite3"
    db = Database(database_path)
    try:
        db.backup(clone)
    finally:
        db.close()
    safe_db = Database(clone)
    store = Store(safe_db)
    try:
        selected = None
        for case in store.list_cases(reason="missing_reference"):
            view = store.inspect_case(case["id"])
            candidate = next(
                (
                    c
                    for c in view["candidate_balances"]
                    if c["outstanding_cents"] >= case["amount_cents"]
                ),
                None,
            )
            if candidate:
                selected = case, candidate
                break
        ensure(selected is not None, "No eligible demonstration case")
        case, candidate = selected
        allocation = store.allocate_case(
            case["id"],
            [{"invoice_id": candidate["invoice_id"], "amount_cents": case["amount_cents"]}],
            ACTOR,
            "Explicit synthetic interview demonstration selection, not an automatic rule",
            case["version"],
            case["ledger_revision"],
            note="Safe copied database only",
        )
        resolved = read_report(clone)
        resolved_path = export(resolved, output_dir / "after-allocation")
        resolved_inspection = inspect_workbook(resolved_path, resolved)
        view = store.inspect_case(case["id"])
        undo = store.reverse_decision(
            allocation["decision_id"],
            ACTOR,
            "Demonstrate explicit linked undo",
            store.ledger_info()["revision"],
            view["case"]["version"],
        )
        final = read_report(clone)
        final_path = export(final, output_dir / "after-reversal")
        final_inspection = inspect_workbook(final_path, final)
        ensure(final.controls == initial.controls, "Undo did not restore all financial totals")
        ensure(
            resolved_inspection["unresolved"] == inspection["unresolved"] - 1,
            "Resolution queue mismatch",
        )
        ensure(final_inspection["unresolved"] == inspection["unresolved"], "Undo queue mismatch")
        ensure(
            read_report(clone, run_id=resolved.metadata["run_id"]).controls == resolved.controls,
            "Historical resolved snapshot changed",
        )
    finally:
        safe_db.close()
    unchanged = original_hash == hashlib.sha256(Path(database_path).read_bytes()).hexdigest()
    ensure(unchanged, "Original database changed during report demonstration")
    evidence = dict(
        synthetic=True,
        original_database_unchanged=unchanged,
        primary_workbook=str(workbook.resolve()),
        exception_csv=str(csv_path.resolve()),
        source_database_sha256=original_hash,
        run_id=initial.metadata["run_id"],
        controls=initial.controls,
        inspection=inspection,
        explicit_demo_selection_not_automatic=True,
        selected_case_id=case["id"],
        selected_invoice_id=candidate["invoice_id"],
        amount_cents=case["amount_cents"],
        allocation=allocation,
        reversal=undo,
        after_allocation=resolved_inspection,
        after_reversal=final_inspection,
        final_controls_restored=final.controls == initial.controls,
        visual_native_application_verified=False,
    )
    (output_dir / "verification.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/phase4-demo.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/phase5"))
    args = parser.parse_args()
    print(json.dumps(demonstration(args.database, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
