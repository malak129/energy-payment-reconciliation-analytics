"""Portable release smoke check: new temporary synthetic data and databases only."""

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from energy_reconciliation.dashboard.demo import environment, require_database, valid
from energy_reconciliation.dashboard.pages import PAGES
from energy_reconciliation.data_generation.expectations import GroundTruth
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.evaluation import evaluate
from energy_reconciliation.ingestion.csv_dataset import load_dataset
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reconciliation.engine import default_options, reconcile
from energy_reconciliation.reporting.demo import demonstration

ACTOR = "SYNTHETIC_DEMO:release-check"


def check(customers, periods, rate):
    with tempfile.TemporaryDirectory(prefix="energy-release-") as temporary:
        root = Path(temporary)
        source = root / "source"
        settings = GenerationSettings(
            customer_count=customers, billing_periods=periods, discrepancy_rate=rate, seed=42
        )
        export_dataset(generate_dataset(settings), source)
        data = load_dataset(source)
        options = default_options(settings.evaluation_date)
        automatic = reconcile(data, options)
        if reconcile(data, options) != automatic:
            raise AssertionError("Reconciliation is not deterministic")
        # Separate expected arithmetic from raw source, not stored KPI functions.
        incoming = sum(p.amount_cents for p in data.rows("payments"))
        outflows = sum(r.amount_cents for r in data.rows("refunds_chargebacks"))
        face = sum(i.amount_cents for i in data.rows("invoices"))
        correction = sum(c.amount_cents for c in data.rows("corrections"))
        allocated = sum(a.amount_cents for a in automatic.allocations) - sum(
            r.amount_cents for r in automatic.releases
        )
        if incoming - outflows != allocated + sum(p.unapplied_cents for p in automatic.payments):
            raise AssertionError("Independent cash equation failed")
        if face + correction != allocated + sum(i.outstanding_cents for i in automatic.invoices):
            raise AssertionError("Independent receivables equation failed")
        truth = GroundTruth.model_validate_json(
            (source / "evaluation/ground_truth.json").read_bytes()
        )
        metrics = evaluate(automatic, truth)  # Evaluation only, after runtime reconciliation.
        if any(
            metrics[k]
            for k in (
                "incorrect_automatic_allocations",
                "missing_expected_allocations",
                "incorrect_releases",
                "outstanding_differences",
                "unapplied_differences",
            )
        ):
            raise AssertionError("Independent synthetic oracle differs")
        db = Database(root / "baseline.sqlite3", clock=lambda: datetime(2026, 11, 15, tzinfo=UTC))
        try:
            store = Store(db)
            store.import_directory(source, ACTOR, "Fresh temporary release input")
            persisted = store.persist_reconciliation(ACTOR, "Release baseline", options=options)
            if persisted != automatic:
                raise AssertionError("SQLite differs from deterministic engine")
            counts = store.counts()
            store.import_directory(source, ACTOR, "Verify duplicate import")
            store.persist_reconciliation(ACTOR, "Verify idempotent rerun", options=options)
            if (
                store.counts()["bank_events"] != counts["bank_events"]
                or store.current() != persisted
            ):
                raise AssertionError("Duplicate import or rerun changed money")
            # Existing safe-copy workflow checks every Excel monetary detail cell,
            # controls, manual allocation/undo and unchanged baseline bytes.
            evidence = demonstration(db.path, root / "reports")
            before_ui = hashlib.sha256(db.path.read_bytes()).hexdigest()
            app_path = (
                Path(__file__).resolve().parents[1] / "src/energy_reconciliation/dashboard/app.py"
            )
            with environment(db.path, root / "ui-exports", True):
                app = AppTest.from_file(str(app_path), default_timeout=120).run()
                require_database(app, db.path)
                valid(app)
                for page in PAGES:
                    app.sidebar.radio[0].set_value(page).run(timeout=120)
                    require_database(app, db.path)
                    valid(app)
            if hashlib.sha256(db.path.read_bytes()).hexdigest() != before_ui:
                raise AssertionError("Read-only pages mutated baseline")
            with db.engine.connect() as connection:
                if connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
                    raise AssertionError("SQLite integrity failure")
                if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
                    raise AssertionError("SQLite foreign-key failure")
            return {
                "synthetic": True,
                "customers": customers,
                "billing_periods": periods,
                "controls": automatic.controls,
                "oracle": metrics,
                "passed_report_controls": evidence["inspection"]["passed_controls"],
                "worksheets": len(evidence["inspection"]["worksheets"]),
                "manual_reversal_restored_controls": evidence["final_controls_restored"],
                "baseline_unchanged": evidence["original_database_unchanged"],
                "dashboard_pages": list(PAGES),
                "status": "PASS",
            }
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--billing-periods", type=int, default=12)
    parser.add_argument("--discrepancy-rate", default="0.15")
    parser.add_argument("--evidence", type=Path, help="Optional new local JSON file")
    args = parser.parse_args()
    if args.evidence and args.evidence.exists():
        parser.error("Evidence file exists; choose a new name")
    result = check(args.customers, args.billing_periods, args.discrepancy_rate)
    text = json.dumps(result, indent=2)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        with args.evidence.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
