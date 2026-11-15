"""Local diagnostics, synthetic generation and deterministic reconciliation CLI."""

import argparse
import importlib
import json
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

from energy_reconciliation import __version__
from energy_reconciliation.config import load_settings
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.ingestion.csv_dataset import load_dataset
from energy_reconciliation.persistence.cli import configure as configure_database_cli
from energy_reconciliation.persistence.cli import run as run_database_cli
from energy_reconciliation.reconciliation.engine import default_options, reconcile
from energy_reconciliation.reconciliation.export import export_result, summary
from energy_reconciliation.reconciliation.results import RunOptions
from energy_reconciliation.reporting.cli import configure as configure_reporting_cli
from energy_reconciliation.reporting.cli import run as run_reporting_cli
from energy_reconciliation.utilities.logging import configure_logging

DEPENDENCIES = (
    "pydantic",
    "sqlalchemy",
    "pandas",
    "numpy",
    "openpyxl",
    "xlsxwriter",
    "streamlit",
    "plotly",
)
MODULES = (
    "config",
    "models.records",
    "data_generation",
    "ingestion",
    "reconciliation",
    "persistence",
    "reporting",
    "dashboard",
    "utilities.money",
)


def doctor(config: Path | None) -> int:
    failures: list[str] = []
    try:
        settings = load_settings(config)
        configure_logging(settings.log_level)
        print(f"OK configuration (synthetic only): {settings.currency}, {settings.timezone}")
    except (OSError, ValueError) as exc:
        failures.append(f"configuration: {exc}")
    # Python's installer enforces requires-python before this module can run.
    print(f"OK Python {sys.version.split()[0]}")
    for name in (*DEPENDENCIES, *(f"energy_reconciliation.{part}" for part in MODULES)):
        try:
            importlib.import_module(name)
        except Exception as exc:  # Diagnostics must report a broken dependency clearly.
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                failures.append("SQLite foreign key support unavailable")
        print(f"OK SQLite {sqlite3.sqlite_version}, foreign keys available")
    except sqlite3.Error as exc:
        failures.append(f"SQLite: {exc}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    logging.getLogger("energy_reconciliation").info("doctor_completed")
    print("OK all runtime dependencies and package modules import")
    print(
        f"PASS Phase 1 environment, version {__version__}. "
        "Reconciliation, persistence, Excel reporting and local dashboard available."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic energy payment reconciliation simulation"
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", aliases=["check"], help="Validate local environment")
    check.add_argument("--config", type=Path, help="Path to local TOML configuration")
    generate = commands.add_parser(
        "generate", help="Generate SYNTHETIC data and evaluation fixtures"
    )
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument(
        "--customers", "--customer-count", dest="customer_count", type=int, default=500
    )
    generate.add_argument("--billing-periods", type=int, default=12)
    generate.add_argument("--start-date", default="2025-01-01", help="ISO date, not today's date")
    generate.add_argument("--end-date", help="ISO date in final billing month; default month end")
    generate.add_argument("--evaluation-date", help="ISO date; default end date + 60 days")
    generate.add_argument("--discrepancy-rate", "--exception-rate", default="0.15")
    generate.add_argument("--output-dir", type=Path, default=Path("data/synthetic"))
    reconcile_command = commands.add_parser(
        "reconcile", help="Reconcile SYNTHETIC Phase 2 source files"
    )
    reconcile_command.add_argument("--input-dir", type=Path, default=Path("data/synthetic"))
    reconcile_command.add_argument(
        "--output-dir", type=Path, default=Path("outputs/reconciliation")
    )
    reconcile_command.add_argument(
        "--evaluation-date", help="ISO date; default dataset effective date"
    )
    reconcile_command.add_argument(
        "--known-at", help="ISO timestamp with UTC offset; default evaluation day end"
    )
    configure_database_cli(commands)
    configure_reporting_cli(commands)
    args = parser.parse_args(argv)
    if args.command == "report":
        return run_reporting_cli(args)
    if args.command == "db":
        return run_database_cli(args)
    if args.command == "reconcile":
        try:
            data = load_dataset(args.input_dir)
            evaluation_date = args.evaluation_date or data.dataset.effective_at.date().isoformat()
            options = (
                default_options(date.fromisoformat(evaluation_date))
                if args.known_at is None
                else RunOptions(evaluation_date=evaluation_date, known_at=args.known_at)
            )
            result = reconcile(data, options)
            export_result(result, data, args.output_dir)
        except (OSError, ValueError) as exc:
            print(f"FAIL reconciliation: {exc}", file=sys.stderr)
            return 1
        print(summary(result))
        print(f"Output: {args.output_dir.resolve()}")
        return 0
    if args.command == "generate":
        values = vars(args).copy()
        values.pop("command")
        try:
            settings = GenerationSettings.model_validate(values)
            manifest = export_dataset(generate_dataset(settings))
        except (OSError, ValueError) as exc:
            print(f"FAIL generation: {exc}", file=sys.stderr)
            return 1
        print("SYNTHETIC dataset generated and validated; no reconciliation engine executed.")
        print(f"Output: {settings.output_dir.resolve()}")
        print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
        return 0
    return doctor(args.config)
