"""CLI export is read-only with respect to the financial database."""

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from energy_reconciliation.reporting.data import read_report
from energy_reconciliation.reporting.excel import export


def configure(commands):
    parser = commands.add_parser("report", help="Export persisted SYNTHETIC financial reports")
    parser.add_argument("kind", choices=["excel", "exceptions"])
    parser.add_argument("--database", type=Path, default=Path("data/phase4-demo.sqlite3"))
    parser.add_argument("--dataset-id")
    parser.add_argument("--run-id", help="Immutable persisted run; default current head")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, help="Exact persisted business date, YYYY-MM-DD"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/phase5"))
    parser.add_argument(
        "--status",
        choices=["unresolved", "all", "OPEN", "IN_REVIEW", "RESOLVED", "REOPENED"],
        default="unresolved",
        help="CSV only; Excel always retains all selected-run cases",
    )


def run(args):
    try:
        if args.kind == "excel" and args.status != "unresolved":
            raise ValueError("--status applies to CSV exception exports only")
        report = read_report(
            args.database, dataset_id=args.dataset_id, run_id=args.run_id, as_of=args.as_of
        )
        output = export(report, args.output_dir, kind=args.kind, status=args.status)
        failures = [c["check"] for c in report.checks if c["status"] == "FAIL"]
        print(
            json.dumps(
                {
                    "output": str(output.resolve()),
                    "run_id": report.metadata["run_id"],
                    "as_of": str(report.metadata["as_of"]),
                    "failed_controls": failures,
                },
                indent=2,
            )
        )
        return 1 if failures else 0
    except (OSError, ValueError, SQLAlchemyError) as exc:
        print(f"FAIL reporting: {exc}", file=sys.stderr)
        return 1
