"""Explicit local demo database commands; no authentication or external integrations."""

import json
from datetime import date
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store, actor_reason
from energy_reconciliation.reconciliation.engine import default_options
from energy_reconciliation.reconciliation.export import summary
from energy_reconciliation.reconciliation.results import RunOptions


def configure(commands):
    parser = commands.add_parser("db", help="SYNTHETIC SQLite storage and review workflow")
    parser.add_argument("--database", type=Path, default=Path("data/reconciliation.sqlite3"))
    parser.add_argument("--dataset-id")
    actions = parser.add_subparsers(dest="db_action", required=True)

    def command(name, write=False):
        sub = actions.add_parser(name)
        if write:
            sub.add_argument(
                "--actor", required=True, help="Explicit local label, e.g. SYNTHETIC_DEMO:student"
            )
            sub.add_argument("--reason", required=True)
        return sub

    command("init")
    command("migrate")
    sub = command("import", True)
    sub.add_argument("--input-dir", type=Path, default=Path("data/synthetic"))
    sub = command("reconcile", True)
    sub.add_argument("--evaluation-date")
    sub.add_argument("--known-at")
    sub.add_argument("--historical", action="store_true")
    sub.add_argument("--output", type=Path, help="Optional new JSON result file")
    sub = command("controls")
    sub.add_argument("--run-id")
    command("counts")
    sub = command("review-list")
    sub.add_argument("--reason-code")
    sub.add_argument("--status", choices=["OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"])
    sub.add_argument("--min-cents", type=int)
    sub.add_argument("--max-cents", type=int)
    sub.add_argument("--from-date")
    sub.add_argument("--to-date")
    sub = command("review-show")
    sub.add_argument("--case-id", required=True)
    for action in ("review-state", "review-allocate", "review-defer"):
        sub = command(action, True)
        sub.add_argument("--case-id", required=True)
        sub.add_argument("--case-version", type=int, required=True)
        sub.add_argument("--note", default="")
        if action == "review-state":
            sub.add_argument("--status", choices=["OPEN", "IN_REVIEW"], required=True)
        else:
            sub.add_argument("--ledger-revision", type=int, required=True)
        if action == "review-allocate":
            sub.add_argument(
                "--target",
                action="append",
                required=True,
                help="INVOICE_ID:INTEGER_CENTS; repeat for split",
            )
            sub.add_argument("--request-id")
    sub = command("decision-reverse", True)
    sub.add_argument("--decision-id", required=True)
    sub.add_argument("--case-version", type=int)
    sub.add_argument("--ledger-revision", type=int, required=True)
    sub.add_argument("--note", default="")
    sub.add_argument("--request-id")
    sub = command("correct-invoice", True)
    sub.add_argument("--invoice-id", required=True)
    sub.add_argument("--amount-cents", type=int, required=True)
    sub.add_argument("--ledger-revision", type=int, required=True)
    sub.add_argument("--note", default="")
    sub.add_argument("--request-id")
    sub = command("cash-outflow", True)
    sub.add_argument("--payment-id", required=True)
    sub.add_argument("--kind", choices=["refund", "chargeback"], required=True)
    sub.add_argument("--amount-cents", type=int, required=True)
    sub.add_argument("--bank-event-id", required=True)
    sub.add_argument(
        "--release",
        action="append",
        default=[],
        help="ALLOCATION_ID:INTEGER_CENTS, explicit release plan",
    )
    sub.add_argument("--ledger-revision", type=int, required=True)
    sub.add_argument("--note", default="")
    sub.add_argument("--request-id")
    sub = command("audit")
    for name in ("payment-id", "invoice-id", "account-id", "run-id"):
        sub.add_argument("--" + name)
    sub = command("backup", True)
    sub.add_argument("--target", type=Path, required=True)
    sub = command("restore")
    sub.add_argument("--backup", type=Path, required=True)
    sub = command("reset", True)
    sub.add_argument("--confirm", required=True, help="Must equal RESET-SYNTHETIC-DEMO")
    sub.add_argument("--backup", type=Path, required=True)


def pairs(values, key):
    output = []
    for value in values:
        identifier, separator, amount = value.rpartition(":")
        if not separator:
            raise ValueError("Use ID:INTEGER_CENTS")
        output.append({key: identifier, "amount_cents": int(amount)})
    return output


def run(args):
    database = None
    try:
        if args.db_action == "restore":
            database = Database.restore(args.backup, args.database)
            value = {"synthetic": True, "restored_to": str(database.path)}
        else:
            database = Database(args.database)
            database.initialize()
            store = Store(database)
            action = args.db_action
            if hasattr(args, "actor"):
                actor_reason(args.actor, args.reason)
            dataset = args.dataset_id
            if action in ("init", "migrate"):
                value = {"synthetic": True, "schema_version": 1, "database": str(database.path)}
            elif action == "import":
                value = store.import_directory(args.input_dir, args.actor, args.reason)
            elif action == "reconcile":
                if args.output and args.output.exists():
                    raise ValueError("Result output already exists; choose a new path")
                options = None
                if args.evaluation_date or args.known_at:
                    evaluation = (
                        date.fromisoformat(args.evaluation_date)
                        if args.evaluation_date
                        else store.current(dataset).run.as_of
                    )
                    options = (
                        RunOptions(evaluation_date=evaluation, known_at=args.known_at)
                        if args.known_at
                        else default_options(evaluation)
                    )
                result = store.persist_reconciliation(
                    args.actor, args.reason, dataset, options, args.historical
                )
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(result.model_dump_json(), encoding="utf-8")
                print(summary(result))
                value = {"run_id": result.run.id, "result_sha256": result.run.result_sha256}
            elif action == "controls":
                result = store.current(dataset, args.run_id)
                value = {
                    "run_id": result.run.id,
                    "controls": result.controls,
                    "ledger": store.ledger_info(dataset),
                }
            elif action == "counts":
                value = store.counts()
            elif action == "review-list":
                value = store.list_cases(
                    dataset,
                    args.reason_code,
                    args.status,
                    args.min_cents,
                    args.max_cents,
                    args.from_date,
                    args.to_date,
                )
            elif action == "review-show":
                value = store.inspect_case(args.case_id)
            elif action == "review-state":
                store.change_case(
                    args.case_id, args.status, args.actor, args.reason, args.case_version, args.note
                )
                value = store.inspect_case(args.case_id)
            elif action == "review-allocate":
                value = store.allocate_case(
                    args.case_id,
                    pairs(args.target, "invoice_id"),
                    args.actor,
                    args.reason,
                    args.case_version,
                    args.ledger_revision,
                    args.note,
                    args.request_id,
                )
            elif action == "review-defer":
                value = store.defer_case(
                    args.case_id,
                    args.actor,
                    args.reason,
                    args.case_version,
                    args.ledger_revision,
                    args.note,
                )
            elif action == "decision-reverse":
                value = store.reverse_decision(
                    args.decision_id,
                    args.actor,
                    args.reason,
                    args.ledger_revision,
                    args.case_version,
                    args.note,
                    args.request_id,
                )
            elif action == "correct-invoice":
                value = store.correct_invoice(
                    args.invoice_id,
                    args.amount_cents,
                    args.actor,
                    args.reason,
                    args.ledger_revision,
                    args.note,
                    args.request_id,
                )
            elif action == "cash-outflow":
                value = store.cash_outflow(
                    args.payment_id,
                    args.kind,
                    args.amount_cents,
                    args.bank_event_id,
                    args.actor,
                    args.reason,
                    args.ledger_revision,
                    pairs(args.release, "allocation_id"),
                    args.note,
                    args.request_id,
                )
            elif action == "audit":
                value = store.audit_history(
                    dataset, args.payment_id, args.invoice_id, args.account_id, args.run_id
                )
            elif action == "backup":
                target = database.backup(args.target)
                with database.transaction() as c:
                    store.audit(
                        c, args.actor, "BACKUP_CREATED", "database", str(target), args.reason
                    )
                value = {"synthetic": True, "backup": str(target)}
            elif action == "reset":
                database.reset(args.confirm, args.backup)
                with database.transaction() as c:
                    store.audit(
                        c,
                        args.actor,
                        "DEMO_RESET",
                        "database",
                        str(database.path),
                        args.reason,
                        {"backup": str(args.backup)},
                    )
                value = {"synthetic": True, "reset": str(database.path), "backup": str(args.backup)}
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, SQLAlchemyError) as exc:
        import sys

        print(f"FAIL database operation: {exc}", file=sys.stderr)
        return 1
    finally:
        if database:
            database.close()
