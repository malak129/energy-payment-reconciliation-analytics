"""Reproducible end-to-end demonstration on a NEW local database, never a silent reset."""

import argparse
import json
from pathlib import Path

from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reconciliation.results import ReconciliationResult

ACTOR = "SYNTHETIC_DEMO:portfolio-operator"


def demonstration(
    input_dir, database_path, report_path, backup_path, restore_path, phase3_reference=None
):
    for path in (database_path, report_path, backup_path, restore_path):
        if path.exists():
            raise ValueError(f"Demo requires new paths; refusing to overwrite {path}")
    database = Database(database_path)
    store = Store(database)
    try:
        imported = store.import_directory(input_dir, ACTOR, "Load synthetic portfolio data")
        initial = store.persist_reconciliation(ACTOR, "Establish immutable baseline")
        reference_matches = None
        if phase3_reference is not None:
            reference = ReconciliationResult.model_validate_json(phase3_reference.read_bytes())
            reference_matches = reference == initial
            if not reference_matches:
                raise ValueError("Database-backed baseline differs from Phase 3 reference")
        before_counts = store.counts()
        duplicate = store.import_directory(input_dir, ACTOR, "Repeat identical source import")
        repeated = store.persist_reconciliation(ACTOR, "Repeat baseline reconciliation")
        after_counts = store.counts()
        assert repeated == initial
        assert all(
            before_counts[name] == after_counts[name]
            for name in (
                "bank_events",
                "source_records",
                "source_versions",
                "allocations",
                "allocation_releases",
                "review_cases",
                "reconciliation_runs",
            )
        )
        candidates = store.list_cases(reason="missing_reference")
        selected = None
        for case in candidates:
            view = store.inspect_case(case["id"])
            originals = {i["id"]: i for i in view["candidate_invoices"]}
            eligible = [
                i
                for i in view["candidate_balances"]
                if i["outstanding_cents"] >= case["amount_cents"]
            ]
            if eligible:
                eligible.sort(
                    key=lambda i: (
                        originals[i["invoice_id"]]["issued_on"][:7]
                        != view["payment"]["booked_on"][:7],
                        i["invoice_id"],
                    )
                )
                selected = (case, eligible[0])
                break
        if selected is None:
            raise ValueError("Demo dataset has no suitable missing-reference case")
        case, invoice = selected
        target = {"invoice_id": invoice["invoice_id"], "amount_cents": case["amount_cents"]}
        print(f"SYNTHETIC explicit demo selection: {case['payment_id']} -> {target}", flush=True)
        decision = store.allocate_case(
            case["id"],
            [target],
            ACTOR,
            "Demonstration operator explicitly selects listed open invoice",
            case["version"],
            case["ledger_revision"],
            note="Reversible synthetic illustration; not an automatic reference match",
            request_id="phase4-demo-allocation",
        )
        resolved = store.current()
        assert (
            resolved.controls["net_allocated_cents"]
            == initial.controls["net_allocated_cents"] + target["amount_cents"]
        )
        assert (
            store.persist_reconciliation(ACTOR, "Prove manual decision survives rerun") == resolved
        )
        view = store.inspect_case(case["id"])
        undo = store.reverse_decision(
            decision["decision_id"],
            ACTOR,
            "Undo demonstration decision explicitly",
            store.ledger_info()["revision"],
            view["case"]["version"],
            request_id="phase4-demo-reversal",
        )
        final = store.current()
        assert final.controls == initial.controls
        assert store.current(run_id=initial.run.id) == initial
        assert store.inspect_case(case["id"])["case"]["status"] == "REOPENED"
        assert store.persist_reconciliation(ACTOR, "Repeat final snapshot") == final
        audit = store.audit_history(payment_id=case["payment_id"])
        assert any(e["entity_id"] == decision["decision_id"] for e in audit)
        assert any(e["entity_id"] == undo["decision_id"] for e in audit)
        database.backup(backup_path)
        restored = Database.restore(backup_path, restore_path)
        try:
            assert Store(restored).current() == final
        finally:
            restored.close()
        report = {
            "synthetic": True,
            "actor": ACTOR,
            "import": imported,
            "repeat_import": duplicate,
            "phase3_reference_identical": reference_matches,
            "initial_run_id": initial.run.id,
            "initial_result_sha256": initial.run.result_sha256,
            "initial_controls": initial.controls,
            "initial_review_count": len(initial.review_queue),
            "selected_case_id": case["id"],
            "selected_target": target,
            "decision": decision,
            "resolved_controls": resolved.controls,
            "resolved_review_count": len(resolved.review_queue),
            "reversal": undo,
            "final_run_id": final.run.id,
            "final_result_sha256": final.run.result_sha256,
            "final_controls": final.controls,
            "final_review_count": len(final.review_queue),
            "final_case_status": "REOPENED",
            "financial_balances_restored": True,
            "counts": store.counts(),
            "case_payment_audit_actions": [e["action"] for e in audit],
            "backup_restore_identical": True,
            "manual_selection_is_not_an_automatic_match": True,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        return report
    finally:
        database.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Explicit synthetic end-to-end demo; requires NEW database/output files"
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--database", type=Path, default=Path("data/phase4-demo.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("outputs/phase4-demo.json"))
    parser.add_argument("--backup", type=Path, default=Path("outputs/phase4-demo-backup.sqlite3"))
    parser.add_argument("--restore", type=Path, default=Path("outputs/phase4-restored.sqlite3"))
    parser.add_argument("--phase3-reference", type=Path)
    args = parser.parse_args(argv)
    demonstration(
        args.input_dir, args.database, args.report, args.backup, args.restore, args.phase3_reference
    )


if __name__ == "__main__":
    main()
