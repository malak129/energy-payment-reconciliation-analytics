"""Independent Phase 7 probes. Every mutating test uses a temporary database."""

import hashlib
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier

import pytest
from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st
from sqlalchemy.exc import NoResultFound
from test_reconciliation import OPTIONS, invoice, payment, unit_data

from energy_reconciliation.dashboard import queries, services
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.overlay import Operation, replay
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reconciliation.engine import reconcile

ACTOR = "SYNTHETIC_DEMO:phase7"


@seed(20261118)
@settings(
    max_examples=12,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(divisor=st.integers(1, 20))
def test_random_transaction_replay_and_rollback(qa_source, tmp_path, divisor):
    from uuid import uuid4

    db = Database(
        tmp_path / (uuid4().hex + ".sqlite3"), clock=lambda: datetime(2026, 11, 15, 12, tzinfo=UTC)
    )
    store = Store(db)
    try:
        store.import_directory(qa_source, ACTOR, "Property source")
        store.persist_reconciliation(ACTOR, "Property baseline")
        before = store.current()
        case = store.list_cases(reason="missing_reference")[0]
        view = store.inspect_case(case["id"])
        target = next(
            i for i in view["candidate_balances"] if i["outstanding_cents"] >= case["amount_cents"]
        )
        amount = max(1, case["amount_cents"] // divisor)
        targets = [{"invoice_id": target["invoice_id"], "amount_cents": amount}]
        request = "phase7-" + uuid4().hex
        decision = store.allocate_case(
            case["id"],
            targets,
            ACTOR,
            "Property choice",
            case["version"],
            case["ledger_revision"],
            request_id=request,
        )
        assert (
            store.allocate_case(
                case["id"],
                targets,
                ACTOR,
                "Property choice",
                case["version"],
                case["ledger_revision"],
                request_id=request,
            )["decision_id"]
            == decision["decision_id"]
        )
        accepted = store.current()
        assert accepted.controls["net_allocated_cents"] == (
            before.controls["net_allocated_cents"] + amount
        )
        with pytest.raises(ValueError):
            store.correct_invoice(
                target["invoice_id"],
                -(10**12),
                ACTOR,
                "Invalid correction",
                store.inspect_case(case["id"])["ledger_revision"],
            )
        assert store.current() == accepted
        current = store.inspect_case(case["id"])
        store.reverse_decision(
            decision["decision_id"],
            ACTOR,
            "Property undo",
            current["ledger_revision"],
            expected_version=current["case"]["version"],
        )
        assert store.current().controls == before.controls
        restored = store.current()
        store.import_directory(qa_source, ACTOR, "Duplicate property import")
        store.persist_reconciliation(ACTOR, "Property replay")
        assert store.current() == restored
    finally:
        db.close()


def test_selected_dataset_confirmation_rejects_without_mutation(qa_store):
    action = qa_action(qa_store)
    before = qa_store.current()
    with pytest.raises(ValueError, match="dataset"):
        services.confirm(
            qa_store.db.path, action, confirmed=True, expected_dataset_id="syn_dataset_wrong"
        )
    assert qa_store.current() == before


def test_streamlit_defaults_to_loopback():
    import tomllib

    root = Path(__file__).parents[1]
    config = tomllib.loads((root / ".streamlit/config.toml").read_text())
    assert config["server"]["address"] == "127.0.0.1"
    assert config["browser"]["gatherUsageStats"] is False


@pytest.mark.parametrize("malicious", [" \n=1+1", "\n@SUM(1,2)", "  +1+1"])
def test_csv_formula_prefix_after_whitespace_is_escaped(qa_store, tmp_path, malicious):
    import csv

    from energy_reconciliation.reporting.data import read_report
    from energy_reconciliation.reporting.excel import export

    report = read_report(qa_store.db.path)
    report.tables["Exception Queue"][0]["reason"] = malicious
    path = export(report, tmp_path / "csv", kind="exceptions", status="all")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.DictReader(stream))["reason"] == "'" + malicious


def test_sql_metacharacters_are_literal_case_ids(qa_store):
    before = qa_store.current()
    with pytest.raises(NoResultFound):
        qa_store.inspect_case("' OR 1=1; DROP TABLE payments;--")
    assert qa_store.current() == before


@pytest.fixture(scope="module")
def qa_source(tmp_path_factory):
    path = tmp_path_factory.mktemp("qa-source") / "source"
    export_dataset(
        generate_dataset(
            GenerationSettings(customer_count=12, billing_periods=2, discrepancy_rate="1")
        ),
        path,
    )
    return path


@pytest.fixture
def qa_store(tmp_path, qa_source):
    db = Database(
        tmp_path / "isolated.sqlite3", clock=lambda: datetime(2026, 11, 15, 12, tzinfo=UTC)
    )
    store = Store(db)
    store.import_directory(qa_source, ACTOR, "Isolated QA fixture")
    store.persist_reconciliation(ACTOR, "QA baseline")
    queries.invalidate()
    yield store
    db.close()
    queries.invalidate()


def qa_action(store):
    report = queries.snapshot(store.db.path)
    case = store.list_cases(reason="missing_reference")[0]
    view = queries.case_view(store.db.path, case["id"])
    target = next(
        i for i in view["candidate_balances"] if i["outstanding_cents"] >= case["amount_cents"]
    )
    return services.prepare_allocation(
        store.db.path,
        report,
        case["id"],
        target["invoice_id"],
        case["amount_cents"],
        ACTOR,
        "Deliberate QA target",
    )


def test_readonly_reset_cannot_delete_database(qa_store, tmp_path):
    path = qa_store.db.path
    before = path.read_bytes()
    db = Database(path, read_only=True)
    try:
        try:
            db.reset("RESET-SYNTHETIC-DEMO", tmp_path / "backup.sqlite3")
        except Exception:
            pass
    finally:
        db.close()
    assert path.exists(), "Read-only reset deleted the database"
    assert path.read_bytes() == before
    assert not (tmp_path / "backup.sqlite3").exists()


def test_restore_empty_source_does_not_initialize_it(tmp_path):
    source = tmp_path / "empty-input.sqlite3"
    source.touch()
    try:
        restored = Database.restore(source, tmp_path / "restored.sqlite3")
    except ValueError:
        pass
    else:
        restored.close()
    assert source.read_bytes() == b"", "Restore modified its purported backup input"
    assert not (tmp_path / "restored.sqlite3").exists()


def test_backup_concurrent_same_destination_no_overwrite(tmp_path, monkeypatch):
    source_paths = [tmp_path / f"source-{n}.sqlite3" for n in range(2)]
    for index, path in enumerate(source_paths):
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE sample(value INTEGER)")
            c.execute("INSERT INTO sample VALUES (?)", (index,))
    target = (tmp_path / "shared-backup.sqlite3").resolve()
    original_exists = Path.exists
    barrier = Barrier(2)

    def synchronized_exists(path):
        result = original_exists(path)
        if path == target:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(Path, "exists", synchronized_exists)

    def backup(path):
        db = Database(path)
        try:
            db.backup(target)
            return "created"
        except (ValueError, FileExistsError):
            return "refused"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(backup, source_paths))
    assert sorted(outcomes) == ["created", "refused"], "Both writers replaced one backup"


@pytest.mark.parametrize("tamper", ["trigger", "index"])
def test_live_schema_drift_is_rejected(qa_store, tamper):
    with qa_store.db.transaction() as c:
        if tamper == "trigger":
            c.exec_driver_sql('DROP TRIGGER "immutable_payments_UPDATE"')
        else:
            name = c.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL LIMIT 1"
            ).scalar_one()
            c.exec_driver_sql('DROP INDEX "' + name + '"')
    with pytest.raises(ValueError, match="Live schema"):
        qa_store.db.initialize()


def test_prepared_action_cannot_follow_database_replacement(qa_store, tmp_path):
    action = qa_action(qa_store)
    path = qa_store.db.path
    replacement = tmp_path / "replacement.sqlite3"
    qa_store.db.backup(replacement)
    qa_store.db.close()
    path.rename(tmp_path / "original-retained.sqlite3")
    shutil.copyfile(replacement, path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="replaced"):
        services.confirm(path, action, confirmed=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_cross_date_neutralization_cannot_create_negative_month_end():
    original = unit_data(invoices=[invoice(amount=10000)], payments=[payment(reference=None)])
    revised = unit_data(
        invoices=[invoice(amount=10000)],
        payments=[
            payment(reference=None),
            payment(key="extra", reference="INV-001", booked=date(2025, 1, 10)),
        ],
    )
    allocate = Operation(
        id="syn_decision_original",
        dataset_id=original.dataset.id,
        sequence=1,
        action="allocate",
        effective_on=date(2025, 1, 31),
        created_at=datetime(2025, 1, 31, 12, tzinfo=UTC),
        actor=ACTOR,
        reason="Previously accepted choice",
        payload={
            "payment_id": "syn_payment_001",
            "targets": [{"invoice_id": "syn_invoice_001", "amount_cents": 10000}],
        },
    )
    undo = Operation(
        id="syn_decision_undo",
        dataset_id=original.dataset.id,
        sequence=2,
        action="reverse",
        effective_on=date(2025, 2, 28),
        created_at=datetime(2025, 2, 28, 12, tzinfo=UTC),
        actor=ACTOR,
        reason="Later explicit undo",
        payload={},
        reverses_decision_id=allocate.id,
    )
    assert (
        replay(reconcile(original, OPTIONS), original, [allocate, undo]).controls[
            "outstanding_cents"
        ]
        == 10000
    )
    with pytest.raises(ValueError, match="effective dates"):
        replay(reconcile(revised, OPTIONS), revised, [allocate, undo])
