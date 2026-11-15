import csv
import hashlib
import re
from datetime import UTC, date, datetime

import openpyxl
import pytest
from openpyxl.utils.cell import range_boundaries

from energy_reconciliation.cli import main
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reconciliation.results import RunOptions
from energy_reconciliation.reporting.data import monthly_rollforward, read_report, validate_totals
from energy_reconciliation.reporting.excel import EMPTY_COLUMNS, SHEETS, export, label

ACTOR = "SYNTHETIC_DEMO:report-test"


def test_fresh_baseline_safe_copy_demonstration(store, tmp_path):
    from energy_reconciliation.reporting.demo import demonstration

    before = store.current()
    evidence = demonstration(store.db.path, tmp_path / "fresh-demo")
    assert evidence["original_database_unchanged"]
    assert evidence["final_controls_restored"]
    assert evidence["inspection"]["tables"]["Manual Decisions"]["records"] == 0
    assert evidence["after_reversal"]["tables"]["Manual Decisions"]["records"] == 2
    assert store.current() == before


@pytest.fixture(scope="module")
def report_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("report-source") / "source"
    export_dataset(
        generate_dataset(
            GenerationSettings(customer_count=12, billing_periods=2, discrepancy_rate="1")
        ),
        root,
    )
    return root


@pytest.fixture
def store(tmp_path, report_source):
    db = Database(tmp_path / "report.sqlite3", clock=lambda: datetime(2026, 11, 15, tzinfo=UTC))
    store = Store(db)
    store.import_directory(report_source, ACTOR, "Reporting fixture")
    store.persist_reconciliation(ACTOR, "Baseline")
    yield store
    db.close()


def resolve(store):
    case = store.list_cases(reason="missing_reference")[0]
    view = store.inspect_case(case["id"])
    target = next(
        c for c in view["candidate_balances"] if c["outstanding_cents"] >= case["amount_cents"]
    )
    decision = store.allocate_case(
        case["id"],
        [{"invoice_id": target["invoice_id"], "amount_cents": case["amount_cents"]}],
        ACTOR,
        "Explicit reviewed selection",
        case["version"],
        case["ledger_revision"],
    )
    return case, decision


def test_database_totals_no_historical_double_counting(store):
    report = read_report(store.db.path)
    assert report.controls == store.current().controls
    assert all(c["status"] == "PASS" and c["difference_cents"] == 0 for c in report.checks)
    for key in ("net_allocated_cents", "unapplied_cents", "outstanding_cents"):
        assert type(report.controls[key]) is int
    assert sum(report.aging.values()) == report.controls["outstanding_cents"]
    assert len(report.tables["Exception Queue"]) == len(store.current().review_queue)


def test_workbook_native_structure_and_readability(store, tmp_path):
    report = read_report(store.db.path)
    path = export(report, tmp_path / "export")
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == SHEETS
    assert len(wb["Executive Summary"]._charts) == 3
    for name, cols in EMPTY_COLUMNS.items():
        ws = wb[name]
        assert ws.freeze_panes == "C6"
        table = next(iter(ws.tables.values()))
        assert table.autoFilter is not None
        bounds = range_boundaries(table.ref)
        assert bounds == (1, 5, len(cols), max(6, 5 + len(report.tables[name])))
        assert [c.value for c in ws[5]] == [label(k) for k in cols]
        assert not ws.merged_cells.ranges
        assert not ws.sheet_view.showGridLines
    assert len(wb["Control Checks"].conditional_formatting) > 0
    assert len(wb["Executive Summary"].conditional_formatting) > 0
    wb.close()


def test_currency_dates_and_typed_values(store, tmp_path):
    path = export(read_report(store.db.path), tmp_path / "export")
    wb = openpyxl.load_workbook(path)
    ws = wb["Invoice Register"]
    assert ws["E6"].number_format == "dd.mm.yyyy"
    assert isinstance(ws["E6"].value, datetime)
    assert '"€"' in ws["G6"].number_format
    assert type(ws["G6"].value) in (int, float)
    wb.close()


def test_formula_references_and_verified_caches(store, tmp_path):
    report = read_report(store.db.path)
    path = export(report, tmp_path / "export")
    wb = openpyxl.load_workbook(path)
    values = openpyxl.load_workbook(path, data_only=True)
    formulas = []
    for ws in wb:
        for row in ws:
            for cell in row:
                if cell.data_type == "f":
                    formulas.append(cell.value)
                    assert "#REF!" not in cell.value
                    for sheet, address in re.findall(r"'([^']+)'!([A-Z]+[0-9]+)", cell.value):
                        assert sheet in wb.sheetnames
                        assert wb[sheet][address].coordinate == address
                    assert values[ws.title][cell.coordinate].value is not None
    assert len(formulas) > 20
    assert (
        values["Executive Summary"]["B7"].value
        == report.controls["adjusted_receivables_cents"] / 100
    )
    for r in range(6, 6 + len(report.checks)):
        assert values["Control Checks"].cell(r, 4).value == 0
        assert values["Control Checks"].cell(r, 7).value == "PASS"
    values.close()
    wb.close()


def test_monthly_dates_and_cross_month_attribution(store):
    report = read_report(store.db.path)
    rows = report.tables["Monthly Reconciliation"]
    payments = report.tables["Payment Register"]
    invoice_dates = {i["invoice_id"]: i["issued_on"] for i in report.tables["Invoice Register"]}
    payment_dates = {p["payment_id"]: p["booked_on"] for p in payments}
    assert any(
        payment_dates[a["payment_id"]].month != invoice_dates[a["invoice_id"]].month
        for a in report.tables["Allocation Details"]
    )
    for row in rows:
        first, end = row["month"], row["period_end"]
        assert row["incoming_cents"] == sum(
            p["received_cents"] for p in payments if first <= p["booked_on"] <= end
        )
        assert row["issued_cents"] == sum(
            i["original_cents"]
            for i in report.tables["Invoice Register"]
            if first <= i["issued_on"] <= end
        )
        assert (
            row["closing_outstanding_cents"]
            == row["opening_outstanding_cents"]
            + row["adjusted_activity_cents"]
            - row["net_allocation_activity_cents"]
        )
        assert (
            row["closing_unapplied_cents"]
            == row["opening_unapplied_cents"]
            + row["net_cash_activity_cents"]
            - row["net_allocation_activity_cents"]
        )
    assert rows[-1]["closing_outstanding_cents"] == report.controls["outstanding_cents"]


def test_monthly_partial_period_and_non_additive_stocks():
    from collections import Counter

    flows = {
        date(2025, 1, 1): Counter(
            issued_cents=10000, incoming_cents=3000, allocation_increases_cents=3000
        ),
        date(2025, 2, 1): Counter(incoming_cents=4000, allocation_increases_cents=4000),
    }
    rows = monthly_rollforward(flows, date(2025, 2, 12))
    assert rows[1]["period_end"] == date(2025, 2, 12)
    assert rows[1]["opening_outstanding_cents"] == 7000
    assert rows[1]["closing_outstanding_cents"] == 3000
    assert sum(r["net_cash_activity_cents"] for r in rows) == 7000


def test_customer_balances_group_each_invoice_once(store):
    report = read_report(store.db.path)
    balances = report.tables["Customer Balances"]
    assert len({r["account_id"] for r in balances}) == len(balances)
    for row in balances:
        own = [i for i in report.tables["Invoice Register"] if i["account_id"] == row["account_id"]]
        assert row["allocated_cents"] == sum(i["allocated_cents"] for i in own)
        assert row["outstanding_cents"] == sum(i["outstanding_cents"] for i in own)
    assert (
        sum(r["identified_credit_cents"] for r in balances)
        == report.controls["identified_credit_cents"]
    )


def test_manual_resolution_undo_and_historical_visibility(store, tmp_path):
    baseline = read_report(store.db.path)
    original_id = baseline.metadata["run_id"]
    case, decision = resolve(store)
    resolved = read_report(store.db.path)
    assert sum(r["unresolved"] for r in resolved.tables["Exception Queue"]) == len(
        store.current().review_queue
    )
    row = next(r for r in resolved.tables["Exception Queue"] if r["case_id"] == case["id"])
    assert row["status"] == "RESOLVED" and row["amount_cents"] == 0
    assert decision["decision_id"] in row["review_history"]
    assert any(
        r["decision_id"] == decision["decision_id"] for r in resolved.tables["Allocation Details"]
    )
    assert any(r["action"] == "allocate" for r in resolved.tables["Manual Decisions"])
    resolved_id = resolved.metadata["run_id"]
    store.reverse_decision(
        decision["decision_id"],
        ACTOR,
        "Undo test selection",
        store.ledger_info()["revision"],
        expected_version=store.inspect_case(case["id"])["case"]["version"],
    )
    final = read_report(store.db.path)
    assert final.controls == baseline.controls
    assert any(
        r["kind"] == "allocation_release" and r["decision_id"]
        for r in final.tables["Corrections and Reversals"]
    )
    assert (
        next(r for r in final.tables["Exception Queue"] if r["case_id"] == case["id"])["status"]
        == "REOPENED"
    )
    historical = read_report(store.db.path, run_id=resolved_id)
    assert (
        next(r for r in historical.tables["Exception Queue"] if r["case_id"] == case["id"])[
            "status"
        ]
        == "RESOLVED"
    )
    before = read_report(store.db.path, run_id=original_id)
    assert before.controls == baseline.controls
    assert before.tables["Manual Decisions"] == []
    for name, report in [("resolved", resolved), ("reversed", final)]:
        wb = openpyxl.load_workbook(export(report, tmp_path / name), data_only=True)
        assert wb["Executive Summary"]["B18"].value == sum(
            r["unresolved"] for r in report.tables["Exception Queue"]
        )
        wb.close()


@pytest.mark.parametrize(
    "status", ["unresolved", "all", "OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"]
)
def test_csv_status_filter(store, tmp_path, status):
    resolve(store)
    report = read_report(store.db.path)
    path = export(report, tmp_path / status, kind="exceptions", status=status)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = [
        r
        for r in report.tables["Exception Queue"]
        if status == "all" or status == "unresolved" and r["unresolved"] or r["status"] == status
    ]
    assert len(rows) == len(expected)
    assert {r["case_id"] for r in rows} == {r["case_id"] for r in expected}


def test_historical_as_of_and_empty_snapshot(store, tmp_path):
    options = RunOptions(
        evaluation_date=date(2024, 12, 1), known_at=datetime(2024, 12, 1, 23, tzinfo=UTC)
    )
    result = store.persist_reconciliation(
        ACTOR, "Before source activity", options=options, historical=True
    )
    report = read_report(store.db.path, as_of=options.evaluation_date)
    assert report.metadata["run_id"] == result.run.id
    assert report.controls["net_cash_cents"] == 0
    assert report.tables["Invoice Register"] == []
    assert all(c["status"] == "PASS" for c in report.checks)
    wb = openpyxl.load_workbook(export(report, tmp_path / "empty"), data_only=True)
    assert wb["Executive Summary"]["B16"].value == "n.a."
    assert next(iter(wb["Invoice Register"].tables.values())).ref == "A5:N6"
    wb.close()


def test_unknown_dates_runs_and_empty_database(store, tmp_path):
    with pytest.raises(ValueError, match="No persisted run"):
        read_report(store.db.path, as_of=date(2025, 1, 7))
    with pytest.raises(ValueError, match="Unknown persisted"):
        read_report(store.db.path, run_id="syn_run_missing")
    with pytest.raises(ValueError, match="differs"):
        read_report(store.db.path, run_id=store.current().run.id, as_of=date(2025, 1, 1))
    db = Database(tmp_path / "empty.sqlite3")
    db.initialize()
    db.close()
    with pytest.raises(ValueError, match="Specify one imported"):
        read_report(db.path)
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="existing"):
        read_report(missing)
    assert not missing.exists()


def test_repeatability_no_clobber_and_no_database_writes(store, tmp_path):
    before = hashlib.sha256(store.db.path.read_bytes()).hexdigest()
    report1 = read_report(store.db.path)
    report2 = read_report(store.db.path)
    assert report1 == report2
    one = export(report1, tmp_path / "one")
    two = export(report2, tmp_path / "two")
    assert one.read_bytes() == two.read_bytes()
    with pytest.raises(FileExistsError):
        export(report1, tmp_path / "one")
    assert hashlib.sha256(store.db.path.read_bytes()).hexdigest() == before


def test_discrepancies_remain_visible(store, tmp_path):
    report = read_report(store.db.path)
    report.tables["Invoice Register"][0]["outstanding_cents"] += 1
    report.checks = validate_totals(report.controls, report.tables)
    assert any(c["status"] == "FAIL" and abs(c["difference_cents"]) == 1 for c in report.checks)
    wb = openpyxl.load_workbook(export(report, tmp_path / "failed"), data_only=True)
    assert any(
        c[0] == "FAIL"
        for c in wb["Control Checks"].iter_rows(min_row=6, min_col=6, max_col=6, values_only=True)
    )
    wb.close()


def test_cli_commands(store, tmp_path, capsys):
    assert (
        main(
            [
                "report",
                "excel",
                "--database",
                str(store.db.path),
                "--output-dir",
                str(tmp_path / "cli"),
            ]
        )
        == 0
    )

    assert "failed_controls" in capsys.readouterr().out
    assert (
        main(
            [
                "report",
                "excel",
                "--database",
                str(store.db.path),
                "--output-dir",
                str(tmp_path / "cli"),
            ]
        )
        == 1
    )
    assert "already exists" in capsys.readouterr().err
    assert (
        main(
            [
                "report",
                "exceptions",
                "--database",
                str(store.db.path),
                "--status",
                "all",
                "--output-dir",
                str(tmp_path / "cli"),
            ]
        )
        == 0
    )


@pytest.mark.parametrize("kind", ["refund", "chargeback"])
def test_operator_cash_adjustments_export_once(store, kind):
    before = read_report(store.db.path)
    payment = next(
        p for p in store.current().payments if p.unapplied_cents > 0 and p.validated_account_id
    )
    amount = payment.unapplied_cents + 1
    store.cash_outflow(
        payment.payment_id,
        kind,
        amount,
        "SYN-REPORT-OUTFLOW",
        ACTOR,
        "Report explicit cash effect",
        store.ledger_info()["revision"],
    )
    after = read_report(store.db.path)
    assert after.controls["net_cash_cents"] == before.controls["net_cash_cents"] - amount
    assert all(c["status"] == "PASS" for c in after.checks)
    effects = [r for r in after.tables["Corrections and Reversals"] if r["kind"] == kind]
    assert -sum(r["signed_cash_cents"] for r in effects) == after.controls[kind + "_cents"]


def test_operator_correction_and_undo_export(store):
    before = read_report(store.db.path)
    invoice = next(i for i in store.current().invoices if i.outstanding_cents >= 100)
    decision = store.correct_invoice(invoice.invoice_id, -100, ACTOR, "Report correction", 1)
    changed = read_report(store.db.path)
    assert (
        changed.controls["signed_correction_cents"]
        == before.controls["signed_correction_cents"] - 100
    )
    assert changed.controls["net_cash_cents"] == before.controls["net_cash_cents"]
    assert all(c["status"] == "PASS" for c in changed.checks)
    store.reverse_decision(
        decision["decision_id"], ACTOR, "Report undo", store.ledger_info()["revision"]
    )
    final = read_report(store.db.path)
    assert final.controls == before.controls
    assert any(
        r["reverses_record_id"]
        for r in final.tables["Corrections and Reversals"]
        if r["kind"] == "correction"
    )
    assert all(c["status"] == "PASS" for c in final.checks)


def test_engine_snapshot_does_not_claim_operator_financial_effects(store):
    from sqlalchemy import select

    from energy_reconciliation.persistence import schema as s

    _, decision = resolve(store)
    with store.db.engine.connect() as c:
        base_id = c.execute(
            select(s.runs.c.base_run_id).where(s.runs.c.id == decision["run_id"])
        ).scalar_one()
    baseline = read_report(store.db.path, run_id=base_id)
    assert baseline.metadata["snapshot_kind"] == "ENGINE"
    assert baseline.tables["Manual Decisions"] == []
    assert all(r["decision_id"] is None for r in baseline.tables["Allocation Details"])


def test_current_defer_note_is_visible_without_moving_financial_head(store):
    case = store.list_cases()[0]
    before = store.current().run.id
    store.defer_case(
        case["id"],
        ACTOR,
        "Await customer evidence",
        case["version"],
        case["ledger_revision"],
        note="Keep this explanation in the report",
    )
    assert store.current().run.id == before
    report = read_report(store.db.path)
    row = next(r for r in report.tables["Exception Queue"] if r["case_id"] == case["id"])
    assert row["unresolved"]
    assert "Keep this explanation in the report" in row["review_history"]
