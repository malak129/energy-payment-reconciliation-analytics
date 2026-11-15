import csv
import hashlib
import importlib
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from streamlit.testing.v1 import AppTest

from energy_reconciliation.dashboard import analytics, exports, queries, services
from energy_reconciliation.dashboard.components import euros
from energy_reconciliation.dashboard.pages import PAGES
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.persistence import schema as s
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import StaleUpdate, Store
from energy_reconciliation.reconciliation.results import RunOptions
from energy_reconciliation.reporting.data import read_report

ACTOR = "SYNTHETIC_DEMO:dashboard-test"
APP = str(Path(__file__).parents[1] / "src/energy_reconciliation/dashboard/app.py")


@pytest.fixture(scope="module")
def dashboard_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("dashboard-source") / "source"
    export_dataset(
        generate_dataset(
            GenerationSettings(customer_count=12, billing_periods=2, discrepancy_rate="1")
        ),
        root,
    )
    return root


@pytest.fixture
def store(tmp_path, dashboard_source):
    db = Database(
        tmp_path / "dashboard.sqlite3", clock=lambda: datetime.now(UTC) - timedelta(seconds=1)
    )
    value = Store(db)
    value.import_directory(dashboard_source, ACTOR, "Dashboard test input")
    value.persist_reconciliation(ACTOR, "Dashboard test baseline")
    queries.invalidate()
    yield value
    db.close()
    queries.invalidate()


def action_for(store):
    report = queries.snapshot(store.db.path)
    case = store.list_cases(reason="missing_reference")[0]
    view = queries.case_view(store.db.path, case["id"])
    invoice = next(
        i for i in view["candidate_balances"] if i["outstanding_cents"] >= case["amount_cents"]
    )
    return report, services.prepare_allocation(
        store.db.path,
        report,
        case["id"],
        invoice["invoice_id"],
        case["amount_cents"],
        ACTOR,
        "Explicit test choice",
    )


def app_for(store, monkeypatch, tmp_path):
    monkeypatch.setenv("ENERGY_RECONCILIATION_DB", str(store.db.path))
    monkeypatch.setenv("ENERGY_RECONCILIATION_EXPORTS", str(tmp_path / "exports"))
    monkeypatch.setenv("ENERGY_RECONCILIATION_READ_ONLY", "0")
    return AppTest.from_file(APP, default_timeout=45).run()


def widget(app, kind, label):
    return next(w for w in app.get(kind) if w.label == label)


def test_imports_kpis_excel_consistency(store, tmp_path):
    for name in ("app", "pages", "components", "queries", "analytics", "services", "exports"):
        importlib.import_module("energy_reconciliation.dashboard." + name)
    report = queries.snapshot(store.db.path)
    assert report.controls == store.current().controls
    full = read_report(store.db.path)
    assert {k: v for k, v in report.tables.items() if k != "Audit Trail"} == {
        k: v for k, v in full.tables.items() if k != "Audit Trail"
    }
    values = analytics.kpis(report)
    assert values["unresolved_cases"] == len(store.current().review_queue)
    assert values["failed_controls"] == 0
    path, payload, failures = exports.generate(
        store.db.path, report.metadata["dataset_id"], report.metadata["run_id"], tmp_path / "export"
    )
    assert payload == path.read_bytes() and not failures
    wb = openpyxl.load_workbook(path, data_only=True)
    assert wb["Executive Summary"]["B7"].value == values["adjusted_receivables_cents"] / 100
    assert wb["Executive Summary"]["B18"].value == values["unresolved_cases"]
    wb.close()
    assert euros(123456) == "1.234,56 €"


def test_readonly_and_no_mutation(store):
    before = hashlib.sha256(store.db.path.read_bytes()).hexdigest()
    with queries.reader(store.db.path) as reader, reader.db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert c.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        with pytest.raises(OperationalError):
            c.execute(s.ledger_heads.update().values(revision=100))
    report = queries.snapshot(store.db.path)
    queries.audit_page(store.db.path, report.metadata["dataset_id"])
    queries.catalog(store.db.path)
    assert hashlib.sha256(store.db.path.read_bytes()).hexdigest() == before


def test_filters_dates_search_rules_and_pagination(store):
    report = queries.snapshot(store.db.path)
    rows = analytics.payment_records(report)
    p = next(p for p in rows if p["allocated_cents"] > 0)
    found = analytics.filter_payments(
        rows,
        search=p["bank_event_id"],
        start=p["booked_on"],
        end=p["booked_on"],
        statuses=[p["status"]],
        minimum=p["received_cents"],
        maximum=p["received_cents"],
        account=p["customer_id"],
        rules=p["rules"],
    )
    assert [r["payment_id"] for r in found] == [p["payment_id"]]
    assert analytics.filter_payments(rows, search="NO-SUCH-EVENT") == []
    p = next(p for p in rows if p["exception_categories"])
    assert p in analytics.filter_payments(rows, categories=p["exception_categories"])
    page, total = analytics.paginate(rows, 2, 5)
    assert page == rows[5:10] and total == len(rows)
    with pytest.raises(ValueError):
        analytics.paginate(rows, 0, 5)
    with pytest.raises(ValueError):
        analytics.filter_payments(rows, minimum=2, maximum=1)


def test_payment_invoice_customer_drilldown(store):
    report = queries.snapshot(store.db.path)
    p = next(p for p in report.tables["Payment Register"] if p["allocated_cents"] > 0)
    detail = analytics.payment_detail(report, p["payment_id"])
    assert sum(a["net_allocated_cents"] for a in detail["allocations"]) == p["allocated_cents"]
    assert {i["invoice_id"] for i in detail["invoices"]} == {
        a["invoice_id"] for a in detail["allocations"]
    }
    account = analytics.account_detail(report, p["validated_account_id"])
    assert (
        sum(i["outstanding_cents"] for i in account["invoices"])
        == account["account"]["outstanding_cents"]
    )
    assert len({p["payment_id"] for p in account["payments"]}) == len(account["payments"])


def test_analytics_filters_global_controls(store):
    report = queries.snapshot(store.db.path)
    before = dict(report.controls)
    start = min(p["booked_on"] for p in report.tables["Payment Register"]) + timedelta(days=10)
    end = report.metadata["as_of"]
    data = analytics.chart_data(report, start, end, "electricity")
    ids = {
        a["account_id"]
        for a in report.tables["Customer Balances"]
        if a["energy_type"] == "electricity"
    }
    expected = sum(
        p["received_cents"]
        for p in report.tables["Payment Register"]
        if p["validated_account_id"] in ids and start <= p["booked_on"] <= end
    )
    assert sum(r["incoming_cents"] for r in data["monthly"]) == expected
    for row in data["monthly"]:
        assert (
            row["closing_outstanding_cents"]
            == row["opening_outstanding_cents"]
            + row["adjusted_activity_cents"]
            - row["net_allocation_activity_cents"]
        )
    assert report.controls == before


def test_confirmation_idempotency_reversal_and_audit(store):
    original, action = action_for(store)
    before = store.counts()
    with pytest.raises(ValueError, match="confirmation"):
        services.confirm(store.db.path, action, confirmed=False)
    assert store.counts() == before
    accepted = services.confirm(store.db.path, action, confirmed=True)
    repeated = services.confirm(store.db.path, action, confirmed=True)
    assert repeated["reused"] and repeated["decision_id"] == accepted["decision_id"]
    changed = queries.snapshot(store.db.path)
    assert (
        analytics.kpis(changed)["unresolved_cases"]
        == analytics.kpis(original)["unresolved_cases"] - 1
    )
    undo = services.prepare_reversal(
        store.db.path, changed, accepted["decision_id"], ACTOR, "Undo selection"
    )
    services.confirm(store.db.path, undo, confirmed=True)
    assert queries.snapshot(store.db.path).controls == original.controls
    assert queries.audit_page(
        store.db.path, original.metadata["dataset_id"], search=accepted["decision_id"]
    )[1]


def test_stale_invalid_cross_database_actions(store, tmp_path):
    original, action = action_for(store)
    with pytest.raises(ValueError, match="another database"):
        services.confirm(tmp_path / "another.sqlite3", action, confirmed=True)
    view = store.inspect_case(action.case_id)
    store.change_case(
        action.case_id, "IN_REVIEW", ACTOR, "Another operator", view["case"]["version"]
    )
    with pytest.raises(StaleUpdate):
        services.confirm(store.db.path, action, confirmed=True)
    with pytest.raises(ValueError, match="Choose an invoice"):
        services.prepare_allocation(
            store.db.path, original, action.case_id, None, 1, ACTOR, "No implicit match"
        )
    with pytest.raises(ValueError, match="reason"):
        services.prepare_allocation(
            store.db.path, original, action.case_id, action.payload["invoice_id"], 1, ACTOR, ""
        )
    excessive = services.prepare_allocation(
        store.db.path,
        original,
        action.case_id,
        action.payload["invoice_id"],
        10**9,
        ACTOR,
        "Invalid excess",
    )
    with pytest.raises(ValueError):
        services.confirm(store.db.path, excessive, confirmed=True)
    assert store.current().controls == original.controls


def test_cache_invalidation(store, monkeypatch):
    calls = []
    actual = queries.read_report

    def tracked(*args, **kwargs):
        calls.append(1)
        return actual(*args, **kwargs)

    monkeypatch.setattr(queries, "read_report", tracked)
    queries.snapshot(store.db.path)
    queries.snapshot(store.db.path)
    assert len(calls) == 1
    token = queries.identity(store.db.path)
    _, action = action_for(store)
    services.confirm(store.db.path, action, confirmed=True)
    assert queries.identity(store.db.path) != token
    queries.snapshot(store.db.path)
    assert len(calls) == 2


def test_audit_filter_date_pagination(store):
    report = queries.snapshot(store.db.path)
    rows, total = queries.audit_page(store.db.path, report.metadata["dataset_id"], size=5)
    next_rows, total2 = queries.audit_page(
        store.db.path, report.metadata["dataset_id"], page=2, size=5
    )
    assert total == total2 > 10 and len(rows) == len(next_rows) == 5
    assert not {r["id"] for r in rows}.intersection(r["id"] for r in next_rows)
    assert queries.audit_page(
        store.db.path, report.metadata["dataset_id"], search=rows[0]["entity_id"]
    )[1]
    assert (
        queries.audit_page(
            store.db.path,
            report.metadata["dataset_id"],
            start=date(2000, 1, 1),
            end=date(2000, 1, 2),
        )[1]
        == 0
    )


def test_filtered_csv_safe_export(store, tmp_path):
    report = queries.snapshot(store.db.path)
    case = report.tables["Exception Queue"][0]
    args = (
        store.db.path,
        report.metadata["dataset_id"],
        report.metadata["run_id"],
        tmp_path / "exports",
    )
    first, payload, _ = exports.generate(
        *args, kind="exceptions", statuses=[case["status"]], search=case["case_id"]
    )
    rows = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["case_id"] == case["case_id"]
    second, payload, _ = exports.generate(*args, kind="exceptions", statuses=[])
    assert second != first and first.exists()
    assert list(csv.DictReader(StringIO(payload.decode("utf-8-sig")))) == []


@pytest.mark.parametrize("page", PAGES)
def test_streamlit_pages(store, monkeypatch, tmp_path, page):
    app = app_for(store, monkeypatch, tmp_path)
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception and not app.error
    assert app.title[0].value == page
    assert any("SYNTHETIC DATA" in v.value for v in app.info)


def test_streamlit_manual_workflow(store, monkeypatch, tmp_path):
    report, action = action_for(store)
    app = app_for(store, monkeypatch, tmp_path)
    app.sidebar.radio[0].set_value("Manual Review Workspace").run()
    widget(app, "text_input", "Search case, payment or reason").set_value(action.case_id).run()
    widget(app, "selectbox", "Review case").select(action.case_id).run()
    assert widget(app, "selectbox", "Choose invoice explicitly").value is None
    widget(app, "selectbox", "Choose invoice explicitly").select(action.payload["invoice_id"])
    widget(app, "text_input", "Allocation amount (integer EUR cents)").set_value(
        str(action.payload["amount_cents"])
    )
    widget(app, "text_input", "Required allocation reason").set_value("Explicit UI test selection")
    widget(app, "button", "Prepare allocation").click().run()
    assert store.current().controls == report.controls
    widget(app, "button", "Confirm and apply").click().run()
    assert store.current().controls == report.controls
    widget(app, "checkbox", "I confirm this exact financial change").check()
    widget(app, "button", "Confirm and apply").click().run()
    assert not app.exception
    with store.db.engine.connect() as c:
        new_id = c.execute(
            select(s.decisions.c.id).where(s.decisions.c.action == "allocate")
        ).scalar_one()
    assert (
        store.current().controls["net_allocated_cents"]
        == report.controls["net_allocated_cents"] + action.payload["amount_cents"]
    )
    widget(app, "selectbox", "Earlier allocation decision").select(new_id)
    widget(app, "text_input", "Required reversal reason").set_value("Explicit UI undo")
    widget(app, "button", "Prepare reversal").click().run()
    widget(app, "checkbox", "I confirm this exact financial change").check()
    widget(app, "button", "Confirm and apply").click().run()
    assert not app.exception and store.current().controls == report.controls


def test_missing_empty_invalid_database_empty_snapshot(tmp_path, monkeypatch, store):
    monkeypatch.setenv("ENERGY_RECONCILIATION_DB", str(tmp_path / "absent.sqlite3"))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert app.error and not app.exception and not (tmp_path / "absent.sqlite3").exists()
    empty = Database(tmp_path / "empty.sqlite3")
    empty.initialize()
    empty.close()
    monkeypatch.setenv("ENERGY_RECONCILIATION_DB", str(empty.path))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert app.warning and not app.exception
    bad = tmp_path / "invalid.sqlite3"
    bad.write_text("not a SQLite database")
    monkeypatch.setenv("ENERGY_RECONCILIATION_DB", str(bad))
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert app.error and not app.exception
    options = RunOptions(
        evaluation_date=date(2024, 12, 1), known_at=datetime(2024, 12, 1, tzinfo=UTC)
    )
    result = store.persist_reconciliation(
        ACTOR, "Empty historical snapshot", options=options, historical=True
    )
    report = queries.snapshot(store.db.path, run_id=result.run.id)
    assert analytics.kpis(report)["settlement_ratio"] is None
    assert analytics.payment_records(report) == []


def test_demo_isolates_inherited_cli_arguments_and_checks_target(store, tmp_path, monkeypatch):
    import sys

    from energy_reconciliation.dashboard.demo import environment, require_database

    clone = tmp_path / "safe-copy.sqlite3"
    store.db.backup(clone)
    monkeypatch.setattr(sys, "argv", ["demo.py", "--database", str(store.db.path)])
    with environment(clone, tmp_path / "exports", False):
        app = AppTest.from_file(APP, default_timeout=30).run()
        require_database(app, clone)
        with pytest.raises(ValueError, match="differs"):
            require_database(app, store.db.path)
    assert sys.argv[-1] == str(store.db.path)
