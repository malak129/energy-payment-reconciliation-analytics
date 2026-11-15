import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from energy_reconciliation.cli import main
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.ingestion.csv_dataset import load_dataset
from energy_reconciliation.persistence import schema as s
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import StaleUpdate, Store
from energy_reconciliation.reconciliation.engine import reconcile
from energy_reconciliation.reconciliation.results import RunOptions

ACTOR = "SYNTHETIC_DEMO:pytest"
NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def source_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("db-source") / "dataset"
    export_dataset(
        generate_dataset(
            GenerationSettings(customer_count=12, billing_periods=2, discrepancy_rate="1")
        ),
        root,
    )
    return root


@pytest.fixture
def store(tmp_path, source_root):
    database = Database(tmp_path / "test.sqlite3", clock=lambda: NOW)
    value = Store(database)
    value.import_directory(source_root, ACTOR, "Test input")
    value.persist_reconciliation(ACTOR, "Test baseline")
    yield value
    database.close()


def selection(store):
    case = store.list_cases(reason="missing_reference")[0]
    view = store.inspect_case(case["id"])
    assert view["source_provenance"] and view["source_known_at"]
    target = next(
        c for c in view["candidate_balances"] if c["outstanding_cents"] >= case["amount_cents"]
    )
    return case, [{"invoice_id": target["invoice_id"], "amount_cents": case["amount_cents"]}]


def allocate(store, request_id=None):
    case, targets = selection(store)
    return (
        case,
        targets,
        store.allocate_case(
            case["id"],
            targets,
            ACTOR,
            "Explicit reviewed targets",
            case["version"],
            case["ledger_revision"],
            request_id=request_id,
        ),
    )


def test_foreign_keys_checks_and_immutable_tables(store):
    with store.db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert c.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    store.db.engine.dispose()
    with store.db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(
            s.accounts.insert().values(
                id="syn_orphan",
                dataset_id="syn_missing",
                customer_id="syn_missing",
                contract_reference="SYN",
                currency="EUR",
            )
        )
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(
            s.bank_events.insert().values(
                id="syn_missing",
                dataset_id="syn_missing",
                source_system="SYN",
                bank_event_id="SYN",
                kind="payment",
                booked_on="2025-01-01",
                currency="EUR",
                amount_cents=-1,
            )
        )
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(s.invoices.update().values(amount_cents=1))
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(s.audit_events.delete())
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(s.runs.update().values(status="failed"))


def test_versioned_initialization_and_unknown_version_rejected(tmp_path):
    database = Database(tmp_path / "version.sqlite3", clock=lambda: NOW)
    database.initialize()
    database.initialize()
    with database.transaction() as c:
        assert c.execute(select(func.count()).select_from(s.schema_versions)).scalar_one() == 1
        c.exec_driver_sql('DROP TRIGGER "immutable_schema_versions_UPDATE"')
        c.execute(s.schema_versions.update().values(version=999))
    with pytest.raises(ValueError, match="Unsupported schema"):
        database.initialize()
    database.close()


def test_idempotent_import_reconciliation_and_database_reconstruction(store, source_root):
    original = store.current()
    counts = store.counts()
    repeat = store.import_directory(source_root, ACTOR, "Repeated same files")
    assert repeat["outcome"] == "DUPLICATE"
    assert store.counts()["bank_events"] == counts["bank_events"] == 30
    assert store.counts()["source_versions"] == 1
    assert store.persist_reconciliation(ACTOR, "Repeat reconciliation") == original
    assert store.counts()["allocations"] == counts["allocations"]
    assert store.counts()["review_cases"] == 7
    assert store.ledger_info()["revision"] == 1
    with store.db.engine.connect() as c:
        version = c.execute(select(s.source_heads.c.version_id)).scalar_one()
        restored_input = store.load_input(c, version)
        assert len(restored_input.provenance) > 0
    pure = reconcile(
        load_dataset(source_root),
        RunOptions(evaluation_date=original.run.as_of, known_at=original.run.known_at),
    )
    assert pure == original
    assert (
        reconcile(
            restored_input,
            RunOptions(evaluation_date=original.run.as_of, known_at=original.run.known_at),
        )
        == original
    )


def test_overlap_statement_copy_adds_provenance_not_cash(store, source_root, tmp_path):
    root = tmp_path / "overlap"
    shutil.copytree(source_root, root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = manifest["statement_receipts"][0]
    path = "statement_fixtures/extra-overlap.csv"
    (root / path).write_bytes((root / receipt["path"]).read_bytes())
    manifest["statement_receipts"].append({**receipt, "path": path})
    manifest["file_sha256"][path] = receipt["file_sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = store.current().controls
    store.import_directory(root, ACTOR, "Overlap source representation")
    result = store.persist_reconciliation(ACTOR, "Accept overlap revision")
    assert result.controls == before
    assert store.counts()["bank_events"] == 30
    assert store.counts()["source_versions"] == 2
    assert result.source_counts["duplicate_file_receipts"] == 2


def test_conflicting_source_and_partial_import_roll_back(source_root, tmp_path, monkeypatch):
    database = Database(tmp_path / "rollback.sqlite3", clock=lambda: NOW)
    value = Store(database)
    original = value._import_typed

    def broken(c, data):
        original(c, data)
        raise RuntimeError("Injected failure after financial row insertion")

    monkeypatch.setattr(value, "_import_typed", broken)
    with pytest.raises(RuntimeError, match="Injected"):
        value.import_directory(source_root, ACTOR, "Rollback injection")
    assert (
        value.counts()["datasets"]
        == value.counts()["bank_events"]
        == value.counts()["import_batches"]
        == 0
    )
    assert value.audit_history()[-1]["action"] == "IMPORT_REJECTED"
    monkeypatch.setattr(value, "_import_typed", original)
    value.import_directory(source_root, ACTOR, "Successful import")
    data = load_dataset(source_root)
    changed = data.rows("payments")[0].model_copy(
        update={"amount_cents": data.rows("payments")[0].amount_cents + 1}
    )
    bad = replace(data, tables={**data.tables, "payments": (changed, *data.rows("payments")[1:])})
    counts = value.counts()
    with pytest.raises(ValueError, match="Conflicting immutable"):
        value.import_input(bad, ACTOR, "Conflicting immutable amount")
    assert value.counts() == counts
    database.close()


def test_source_revision_cannot_erase_existing_cash(store, source_root):
    data = load_dataset(source_root)
    removed = next(p for p in data.rows("payments") if p.reference is None)
    reduced = replace(
        data,
        tables={
            **data.tables,
            "payments": tuple(p for p in data.rows("payments") if p.id != removed.id),
        },
    )
    with pytest.raises(ValueError, match="cannot omit"):
        store.import_input(reduced, ACTOR, "Incomplete revision")
    assert store.counts()["bank_events"] == 30


def test_database_bank_identity_unique_constraint(store):
    with store.db.engine.connect() as c:
        event = (
            c.execute(select(s.bank_events).where(s.bank_events.c.kind == "payment"))
            .mappings()
            .first()
        )
    with pytest.raises(IntegrityError), store.db.transaction() as c:
        c.execute(
            s.source_records.insert().values(
                id="syn_duplicate_event",
                dataset_id=event["dataset_id"],
                table_name="payments",
                payload_sha256="0" * 64,
                payload_json="{}",
                synthetic=1,
            )
        )
        c.execute(s.bank_events.insert().values(**{**event, "id": "syn_duplicate_event"}))
    assert store.counts()["bank_events"] == 30


@pytest.mark.parametrize("amount", [0, -1, 1.5])
def test_sql_monetary_checks_with_valid_foreign_keys(store, amount):
    dataset = store.current().run.dataset_id
    with (
        pytest.raises(IntegrityError, match="CHECK constraint failed"),
        store.db.transaction() as c,
    ):
        c.execute(
            s.source_records.insert().values(
                id="syn_invalid_cash",
                dataset_id=dataset,
                table_name="payments",
                payload_sha256="0" * 64,
                payload_json="{}",
                synthetic=1,
            )
        )
        c.execute(
            s.bank_events.insert().values(
                id="syn_invalid_cash",
                dataset_id=dataset,
                source_system="SYN_TEST",
                bank_event_id="BAD-MONEY",
                kind="payment",
                booked_on="2025-01-01",
                currency="EUR",
                amount_cents=amount,
            )
        )


def test_manual_resolution_reversal_history_and_persistent_decision(store):
    before = store.current()
    case, targets, created = allocate(store, "allocation-request")
    active = store.current()
    amount = targets[0]["amount_cents"]
    assert active.controls["net_allocated_cents"] == before.controls["net_allocated_cents"] + amount
    assert active.controls["unapplied_cents"] == before.controls["unapplied_cents"] - amount
    assert active.controls["outstanding_cents"] == before.controls["outstanding_cents"] - amount
    assert store.inspect_case(case["id"])["case"]["status"] == "RESOLVED"
    assert store.persist_reconciliation(ACTOR, "Preserve manual decision") == active
    assert store.current(run_id=before.run.id) == before
    repeated = store.allocate_case(
        case["id"],
        targets,
        ACTOR,
        "Explicit reviewed targets",
        1,
        1,
        request_id="allocation-request",
    )
    assert repeated["reused"] and repeated["decision_id"] == created["decision_id"]
    view = store.inspect_case(case["id"])
    undo = store.reverse_decision(
        created["decision_id"],
        ACTOR,
        "Reverse demonstrative allocation",
        store.ledger_info()["revision"],
        view["case"]["version"],
        request_id="undo-request",
    )
    assert undo["decision_id"] != created["decision_id"]
    assert store.current().controls == before.controls
    assert store.inspect_case(case["id"])["case"]["status"] == "REOPENED"
    assert any(r.decision_id == undo["decision_id"] for r in store.current().releases)
    assert store.current(run_id=active.run.id) == active
    assert len(store.inspect_case(case["id"])["decisions"]) == 2


def test_multiple_invoice_manual_split_and_defer(store):
    case, targets = selection(store)
    view = store.inspect_case(case["id"])
    candidates = view["candidate_balances"]
    assert len(candidates) == 2
    amount = case["amount_cents"]
    split = [
        {"invoice_id": candidates[0]["invoice_id"], "amount_cents": amount // 2},
        {"invoice_id": candidates[1]["invoice_id"], "amount_cents": amount - amount // 2},
    ]
    decision = store.allocate_case(case["id"], split, ACTOR, "Explicit two-invoice split", 1, 1)
    assert (
        len([a for a in store.current().allocations if a.decision_id == decision["decision_id"]])
        == 2
    )
    other = store.list_cases()[0]
    before = store.current().controls
    store.defer_case(
        other["id"],
        ACTOR,
        "Need more invoice evidence",
        other["version"],
        other["ledger_revision"],
        "Leave unresolved",
    )
    assert store.current().controls == before
    assert store.inspect_case(other["id"])["case"]["status"] != "RESOLVED"


@pytest.mark.parametrize(
    "fault",
    [
        "too_much_cash",
        "too_much_invoice",
        "unknown_invoice",
        "float",
        "empty_actor",
        "empty_reason",
    ],
)
def test_rejected_financial_actions_leave_money_unchanged(store, fault):
    case, targets = selection(store)
    before = store.current()
    actor, reason = ACTOR, "Deliberately invalid"
    if fault == "too_much_cash":
        targets[0]["amount_cents"] = case["amount_cents"] + 1
    elif fault == "too_much_invoice":
        targets[0]["invoice_id"] = next(
            i.invoice_id for i in before.invoices if i.outstanding_cents == 0
        )
    elif fault == "unknown_invoice":
        targets[0]["invoice_id"] = "syn_unknown_invoice"
    elif fault == "float":
        targets[0]["amount_cents"] = 1.0
    elif fault == "empty_actor":
        actor = ""
    else:
        reason = ""
    with pytest.raises(ValueError):
        store.allocate_case(
            case["id"], targets, actor, reason, case["version"], case["ledger_revision"]
        )
    assert store.current() == before
    assert store.counts()["manual_decisions"] == 0
    assert store.audit_history()[-1]["action"] == "FINANCIAL_ACTION_REJECTED"


def test_stale_versions_and_concurrent_operator_updates(store):
    case, targets = selection(store)

    def attempt(_):
        try:
            return store.allocate_case(
                case["id"],
                targets,
                ACTOR,
                "Concurrent action",
                case["version"],
                case["ledger_revision"],
            )
        except StaleUpdate:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result == "stale" for result in results) == 1
    assert store.counts()["manual_decisions"] == 1
    assert store.current().controls["cash_control_difference_cents"] == 0


def test_invalid_status_transitions_and_review_versions(store):
    case, _ = selection(store)
    store.change_case(case["id"], "IN_REVIEW", ACTOR, "Claim review", 1)
    with pytest.raises(StaleUpdate):
        store.change_case(case["id"], "OPEN", ACTOR, "Stale status", 1)
    with pytest.raises(ValueError, match="RESOLVED/REOPENED"):
        store.change_case(case["id"], "RESOLVED", ACTOR, "No financial resolution", 2)
    with pytest.raises(ValueError, match="Invalid review transition"):
        store.change_case(case["id"], "IN_REVIEW", ACTOR, "Already in review", 2)


def test_manual_transaction_failure_rolls_back_every_effect(store, monkeypatch):
    case, targets = selection(store)
    before = store.current()
    counts = store.counts()
    original = store._effects

    def fail(c, result, actor, reason):
        original(c, result, actor, reason)
        raise RuntimeError("Injected failure after result effects")

    monkeypatch.setattr(store, "_effects", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        store.allocate_case(case["id"], targets, ACTOR, "Atomic failure test", 1, 1)
    assert store.current() == before
    after = store.counts()
    assert all(after[name] == count for name, count in counts.items() if name != "audit_events")
    assert after["audit_events"] == counts["audit_events"] + 1


def test_correction_and_undo_change_receivables_not_cash(store):
    before = store.current()
    invoice = next(i for i in before.invoices if i.outstanding_cents >= 100)
    decision = store.correct_invoice(invoice.invoice_id, -100, ACTOR, "Approved AR reduction", 1)
    after = store.current()
    assert after.controls["net_cash_cents"] == before.controls["net_cash_cents"]
    assert after.controls["outstanding_cents"] == before.controls["outstanding_cents"] - 100
    store.reverse_decision(
        decision["decision_id"], ACTOR, "Undo AR reduction", store.ledger_info()["revision"]
    )
    assert store.current().controls == before.controls
    assert store.counts()["adjustments"] == 2


@pytest.mark.parametrize("kind", ["refund", "chargeback"])
def test_local_cash_outflows_and_releases(store, kind):
    before = store.current()
    p = next(p for p in before.payments if p.unapplied_cents > 0 and p.validated_account_id)
    amount = p.unapplied_cents + 1
    created = store.cash_outflow(
        p.payment_id, kind, amount, "SYN-OUTFLOW-1", ACTOR, "Explicit bank outflow", 1
    )
    after = store.current()
    assert after.controls["net_cash_cents"] == before.controls["net_cash_cents"] - amount
    assert after.controls["net_allocated_cents"] == before.controls["net_allocated_cents"] - 1
    assert after.controls["outstanding_cents"] == before.controls["outstanding_cents"] + 1
    assert after.controls["cash_control_difference_cents"] == 0
    assert store.persist_reconciliation(ACTOR, "Repeat with outflow") == after
    with pytest.raises(ValueError, match="cannot be reversed"):
        store.reverse_decision(created["decision_id"], ACTOR, "Cannot erase bank cash", 2)


def test_explicit_release_plan_is_required_and_durable_for_partial_combined_outflow(store):
    before = store.current()
    groups = {}
    for allocation in before.allocations:
        groups.setdefault(allocation.payment_id, []).append(allocation)
    pair = next(rows for rows in groups.values() if len(rows) == 2)
    with pytest.raises(ValueError, match="explicit release plan"):
        store.cash_outflow(
            pair[0].payment_id, "chargeback", 1, "SYN-PLAN", ACTOR, "Ambiguous release", 1
        )
    decision = store.cash_outflow(
        pair[0].payment_id,
        "chargeback",
        1,
        "SYN-PLAN",
        ACTOR,
        "Explicit release",
        1,
        releases=[{"allocation_id": pair[0].id, "amount_cents": 1}],
        request_id="explicit-plan",
    )
    after = store.current()
    assert after.controls["outstanding_cents"] == before.controls["outstanding_cents"] + 1
    assert store.persist_reconciliation(ACTOR, "Repeat explicit plan") == after
    assert decision["decision_id"]


def test_conflicting_later_automatic_match_does_not_override_manual_decision(store, source_root):
    from energy_reconciliation.models.records import Payment

    case, targets, created = allocate(store)
    accepted = store.current()
    data = load_dataset(source_root)
    invoice = next(i for i in data.rows("invoices") if i.id == targets[0]["invoice_id"])
    extra = Payment(
        id="syn_extra_receipt",
        synthetic=True,
        dataset_id=data.dataset.id,
        source_record_id="SYN-EXTRA",
        source_system="SYN_TEST",
        bank_event_id="EXTRA-PAYMENT",
        booked_on=accepted.run.as_of,
        value_on=accepted.run.as_of,
        amount_cents=invoice.amount_cents,
        account_id=invoice.account_id,
        reference=invoice.reference,
    )
    changed = replace(
        data,
        tables={**data.tables, "payments": (*data.rows("payments"), extra)},
        bank_known_at={
            **data.bank_known_at,
            extra.id: datetime.combine(extra.booked_on, datetime.min.time(), UTC),
        },
    )
    store.import_input(changed, ACTOR, "New normalized receipt revision")
    runs = store.counts()["reconciliation_runs"]
    with pytest.raises(ValueError, match="over-allocation"):
        store.persist_reconciliation(ACTOR, "Reject automatic conflict")
    assert store.current() == accepted
    assert store.counts()["reconciliation_runs"] == runs
    assert store.counts()["manual_decisions"] == 1
    # An explicit undo on the last accepted source permits recovery, not a silent replacement.
    view = store.inspect_case(case["id"])
    store.reverse_decision(
        created["decision_id"],
        ACTOR,
        "Release conflicting manual decision",
        store.ledger_info()["revision"],
        view["case"]["version"],
    )
    fresh = store.persist_reconciliation(ACTOR, "Accept new receipt after explicit undo")
    assert (
        fresh.controls["gross_incoming_cents"]
        == accepted.controls["gross_incoming_cents"] + extra.amount_cents
    )


def test_request_id_conflict_and_double_undo_are_rejected(store):
    case, targets, created = allocate(store, "same-request")
    with pytest.raises(ValueError, match="different intent"):
        store.allocate_case(
            case["id"], targets, ACTOR, "Changed intent", 1, 1, request_id="same-request"
        )
    view = store.inspect_case(case["id"])
    store.reverse_decision(created["decision_id"], ACTOR, "Undo once", 2, view["case"]["version"])
    view = store.inspect_case(case["id"])
    with pytest.raises(ValueError, match="already reversed"):
        store.reverse_decision(
            created["decision_id"], ACTOR, "Unsafe repeated undo", 3, view["case"]["version"]
        )


def test_reversal_dependency_protects_released_manual_allocation(store):
    case, targets, created = allocate(store)
    store.cash_outflow(
        case["payment_id"],
        "chargeback",
        1,
        "SYN-DEPENDENCY",
        ACTOR,
        "Release one manually applied cent",
        store.ledger_info()["revision"],
    )
    view = store.inspect_case(case["id"])
    with pytest.raises(ValueError, match="later releases"):
        store.reverse_decision(
            created["decision_id"],
            ACTOR,
            "Unsafe undo",
            store.ledger_info()["revision"],
            view["case"]["version"],
        )


def test_historical_snapshot_does_not_erase_manual_decision(store):
    baseline = store.current()
    _, _, _ = allocate(store)
    active = store.current()
    options = RunOptions(evaluation_date=baseline.run.as_of, known_at=NOW - timedelta(seconds=1))
    older = store.persist_reconciliation(
        ACTOR, "Historical knowledge", options=options, historical=True
    )
    assert older.controls == baseline.controls
    assert store.current() == active
    with pytest.raises(ValueError, match="historical=True"):
        store.persist_reconciliation(ACTOR, "Unsafe old activation", options=options)
    assert store.current() == active


def test_audit_completeness_and_entity_filters(store):
    before = store.current()
    actions = {row["action"] for row in store.audit_history()}
    assert {
        "IMPORT_IMPORTED",
        "ALLOCATION_CREATED",
        "ALLOCATION_RELEASED",
        "CORRECTION_HANDLED",
        "REFUND_HANDLED",
        "CHARGEBACK_HANDLED",
        "RECONCILIATION_COMPLETED",
    } <= actions
    case, targets, decision = allocate(store)
    payment_history = store.audit_history(payment_id=case["payment_id"])
    assert any(row["entity_id"] == decision["decision_id"] for row in payment_history)
    invoice_history = store.audit_history(invoice_id=targets[0]["invoice_id"])
    assert any(
        row["details"].get("decision_id") == decision["decision_id"] for row in invoice_history
    )
    with store.db.engine.connect() as c:
        account_id = c.execute(
            select(s.invoices.c.account_id).where(s.invoices.c.id == targets[0]["invoice_id"])
        ).scalar_one()
    assert store.audit_history(account_id=account_id)
    assert store.audit_history(run_id=before.run.id)
    events = store.audit_history()
    assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events)
    assert all(e["actor"].startswith("SYNTHETIC_DEMO:") and e["reason"] for e in events)


def test_backup_restore_and_confirmed_reset(store, tmp_path):
    original = store.current()
    backup = store.db.backup(tmp_path / "backup.sqlite3")
    restored = Database.restore(backup, tmp_path / "restored.sqlite3")
    other = Store(restored)
    assert other.current() == original
    assert other.counts() == store.counts()
    restored.close()
    with pytest.raises(ValueError, match="must not exist"):
        Database.restore(backup, store.db.path)
    with pytest.raises(ValueError, match="requires --confirm"):
        store.db.reset("NO", tmp_path / "unsafe.sqlite3")
    assert store.current() == original
    reset_backup = tmp_path / "before-reset.sqlite3"
    store.db.reset("RESET-SYNTHETIC-DEMO", reset_backup)
    assert store.counts()["datasets"] == store.counts()["bank_events"] == 0
    retained = Database.restore(reset_backup, tmp_path / "reset-restored.sqlite3")
    assert Store(retained).current() == original
    retained.close()


def test_cli_database_commands_help_and_confirmation(tmp_path, source_root, capsys):
    path = tmp_path / "cli.sqlite3"
    prefix = ["db", "--database", str(path)]
    assert main([*prefix, "init"]) == 0
    assert (
        main(
            [
                *prefix,
                "import",
                "--input-dir",
                str(source_root),
                "--actor",
                ACTOR,
                "--reason",
                "CLI source",
            ]
        )
        == 0
    )
    assert main([*prefix, "reconcile", "--actor", ACTOR, "--reason", "CLI run"]) == 0
    assert main([*prefix, "controls"]) == 0
    assert main([*prefix, "review-list"]) == 0
    with pytest.raises(SystemExit):
        main([*prefix, "reset", "--actor", ACTOR, "--reason", "Missing confirmation"])
    assert "--confirm" in capsys.readouterr().err
    with pytest.raises(SystemExit) as info:
        main([*prefix, "review-allocate", "--help"])
    assert info.value.code == 0


def test_end_to_end_demonstration_uses_a_new_database(store, source_root, tmp_path):
    from energy_reconciliation.persistence.demo import demonstration

    reference = tmp_path / "phase3-reference.json"
    reference.write_text(store.current().model_dump_json(), encoding="utf-8")
    report = demonstration(
        source_root,
        tmp_path / "demo.sqlite3",
        tmp_path / "report.json",
        tmp_path / "backup.sqlite3",
        tmp_path / "restored.sqlite3",
        reference,
    )
    assert report["phase3_reference_identical"]
    assert report["financial_balances_restored"] and report["backup_restore_identical"]
    assert report["initial_review_count"] == report["final_review_count"] == 7
    assert report["resolved_review_count"] == 6
    with pytest.raises(ValueError, match="refusing to overwrite"):
        demonstration(
            source_root,
            tmp_path / "demo.sqlite3",
            tmp_path / "unused.json",
            tmp_path / "unused-backup.sqlite3",
            tmp_path / "unused-restored.sqlite3",
        )
