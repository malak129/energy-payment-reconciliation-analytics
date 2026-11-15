"""Explicit confirmation adapters. All money writes belong to Phase 4 services."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from energy_reconciliation.dashboard.queries import case_view, catalog, invalidate, reader
from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store, actor_reason


@dataclass(frozen=True)
class Action:
    database_path: str
    database_file: tuple[int, int]
    dataset_id: str
    kind: str
    case_id: str
    case_version: int
    ledger_revision: int
    payload: dict
    actor: str
    reason: str
    note: str
    request_id: str


def _current(path, report):
    head = catalog(path)["heads"].get(report.metadata["dataset_id"])
    ensure(
        head is not None and head["run_id"] == report.metadata["run_id"],
        "The selected snapshot is historical or stale. Refresh the current ledger before a change.",
    )
    return head


def prepare_allocation(path, report, case_id, invoice_id, amount_cents, actor, reason, note=""):
    _current(path, report)
    actor_reason(actor, reason)
    ensure(
        invoice_id is not None, "Choose an invoice explicitly; candidates never authorize a match"
    )
    ensure(type(amount_cents) is int and amount_cents > 0, "Enter positive integer EUR cents")
    view = case_view(path, case_id)
    ensure(view["case"]["dataset_id"] == report.metadata["dataset_id"], "Wrong dataset")
    return Action(
        str(Path(path).resolve()),
        (Path(path).stat().st_dev, Path(path).stat().st_ino),
        report.metadata["dataset_id"],
        "allocate",
        case_id,
        view["case"]["version"],
        view["ledger_revision"],
        {"invoice_id": invoice_id, "amount_cents": amount_cents},
        actor,
        reason,
        note,
        uuid4().hex,
    )


def prepare_reversal(path, report, decision_id, actor, reason, note=""):
    _current(path, report)
    actor_reason(actor, reason)
    with reader(path) as store:
        with store.db.engine.connect() as c:
            op = next(
                (
                    o
                    for o in store.operations(c, report.metadata["dataset_id"])
                    if o.id == decision_id
                ),
                None,
            )
    ensure(op is not None and op.action == "allocate", "Select an earlier manual allocation")
    view = case_view(path, op.case_id)
    return Action(
        str(Path(path).resolve()),
        (Path(path).stat().st_dev, Path(path).stat().st_ino),
        report.metadata["dataset_id"],
        "reverse",
        op.case_id,
        view["case"]["version"],
        view["ledger_revision"],
        {"decision_id": decision_id},
        actor,
        reason,
        note,
        uuid4().hex,
    )


def confirm(path, action: Action, *, confirmed: bool, expected_dataset_id=None):
    ensure(confirmed is True, "Explicit financial confirmation is required")
    ensure(
        str(Path(path).resolve()) == action.database_path,
        "Prepared action belongs to another database",
    )
    stamp = Path(path).stat()
    ensure(
        (stamp.st_dev, stamp.st_ino) == action.database_file,
        "Database file was replaced; prepare a new action",
    )
    ensure(
        expected_dataset_id is None or expected_dataset_id == action.dataset_id,
        "Prepared action belongs to another dataset",
    )
    db = Database(Path(path))
    try:
        store = Store(db)
        if action.kind == "allocate":
            return store.allocate_case(
                action.case_id,
                [action.payload],
                action.actor,
                action.reason,
                action.case_version,
                action.ledger_revision,
                note=action.note,
                request_id=action.request_id,
            )
        ensure(action.kind == "reverse", "Unknown action")
        return store.reverse_decision(
            action.payload["decision_id"],
            action.actor,
            action.reason,
            action.ledger_revision,
            action.case_version,
            note=action.note,
            request_id=action.request_id,
        )
    finally:
        db.close()
        # Failed attempts can append audit records too; force every view to refresh.
        invalidate()
