"""Explicit evaluation-only command. Never imported by normal reconciliation logic."""

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

from energy_reconciliation.data_generation.expectations import GroundTruth
from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.reconciliation.export import write_files
from energy_reconciliation.reconciliation.results import ReconciliationResult
from energy_reconciliation.utilities.serialization import canonical, fingerprint


def _percent(numerator: int, denominator: int) -> str | None:
    if not denominator:
        return None
    with localcontext() as context:
        context.prec = 32
        return format(Decimal(numerator) * 100 / Decimal(denominator), ".4f")


def evaluate(result: ReconciliationResult, truth: GroundTruth) -> dict:
    ensure(
        not any(a.decision_id is not None for a in result.allocations),
        "The Phase 2 oracle evaluates automatic baselines only; select a stored ENGINE run",
    )
    ensure(
        result.run.dataset_id == truth.dataset_id and result.run.as_of == truth.evaluation_date,
        "Evaluation requires matching dataset ID and business evaluation date",
    )
    expected = Counter(
        (a.payment_id, a.invoice_id, a.amount_cents, a.effective_on)
        for a in truth.expected_applications
        if a.effective_on <= result.run.as_of
    )
    actual = Counter(
        (a.payment_id, a.invoice_id, a.amount_cents, a.effective_on) for a in result.allocations
    )
    correct = sum((actual & expected).values())
    incorrect = sum((actual - expected).values())
    missing = sum((expected - actual).values())
    invoice_actual = {i.invoice_id: i.outstanding_cents for i in result.invoices}
    invoice_expected = {i.invoice_id: i.outstanding_cents for i in truth.invoice_balances}
    cash_actual = {p.payment_id: p.unapplied_cents for p in result.payments}
    cash_expected = {p.payment_id: p.unapplied_cents for p in truth.payment_balances}

    def differences(expected_values: dict, actual_values: dict) -> list[dict]:
        return [
            {
                "id": key,
                "expected_cents": expected_values.get(key, 0),
                "actual_cents": actual_values.get(key, 0),
                "difference_cents": actual_values.get(key, 0) - expected_values.get(key, 0),
            }
            for key in sorted(expected_values.keys() | actual_values.keys())
            if expected_values.get(key, 0) != actual_values.get(key, 0)
        ]

    debt_differences = differences(invoice_expected, invoice_actual)
    cash_differences = differences(cash_expected, cash_actual)
    actual_apps = {a.id: a for a in result.allocations}
    expected_apps = {a.id: a for a in truth.expected_applications}
    release_actual = Counter(
        (
            actual_apps[r.allocation_id].payment_id,
            actual_apps[r.allocation_id].invoice_id,
            r.reversal_id,
            r.amount_cents,
            r.effective_on,
        )
        for r in result.releases
    )
    release_expected = Counter(
        (
            expected_apps[r.application_id].payment_id,
            expected_apps[r.application_id].invoice_id,
            r.reversal_id,
            r.amount_cents,
            r.effective_on,
        )
        for r in truth.expected_releases
        if r.effective_on <= result.run.as_of
    )
    actual_reasons = {e.subject_id: e.reason_code for e in result.review_queue}
    review_comparison = Counter(
        (e.category, actual_reasons.get(e.subject_id, "no_review_item"))
        for e in truth.expected_exceptions
        if e.subject_id in set(truth.expected_manual_review_payment_ids)
    )
    return {
        "synthetic": True,
        "purpose": "evaluation_only",
        "run_id": result.run.id,
        "correct_automatic_allocations": correct,
        "incorrect_automatic_allocations": incorrect,
        "missing_expected_allocations": missing,
        "matching_precision_percent": _percent(correct, sum(actual.values())),
        "expected_allocation_coverage_percent": _percent(correct, sum(expected.values())),
        "active_matched_payment_coverage_percent": _percent(
            result.controls["matched_event_count"], len(result.payments)
        ),
        "active_matched_payment_count": result.controls["matched_event_count"],
        "ever_automatically_matched_payment_count": len({a.payment_id for a in result.allocations}),
        "ever_matched_payment_coverage_percent": _percent(
            len({a.payment_id for a in result.allocations}), len(result.payments)
        ),
        "input_payment_count_at_cutoff": len(result.payments),
        "unresolved_positive_cash_payment_count": result.controls["unmatched_event_count"],
        "payments_with_any_unapplied_cash": sum(p.unapplied_cents > 0 for p in result.payments),
        "manual_review_item_count": len(result.review_queue),
        "correct_releases": sum((release_actual & release_expected).values()),
        "incorrect_releases": sum((release_actual - release_expected).values()),
        "outstanding_difference_cents": sum(invoice_actual.values())
        - sum(invoice_expected.values()),
        "unapplied_difference_cents": sum(cash_actual.values()) - sum(cash_expected.values()),
        "outstanding_differences": debt_differences,
        "unapplied_differences": cash_differences,
        "manual_review_reason_comparison": [
            {"expected": expected_reason, "actual": actual_reason, "payment_count": count}
            for (expected_reason, actual_reason), count in sorted(review_comparison.items())
        ],
        "caveat": "Oracle assumes full knowledge; historical known_at runs may differ.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit evaluation only; never part of reconciliation"
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/evaluation"))
    args = parser.parse_args(argv)
    try:
        result = ReconciliationResult.model_validate_json(args.result.read_bytes())
        ensure(
            result.run.result_sha256
            == fingerprint(result.model_dump(mode="json", exclude={"run"})),
            "Result fingerprint mismatch",
        )
        truth = GroundTruth.model_validate_json(args.ground_truth.read_bytes())
        metrics = evaluate(result, truth)
        write_files({"evaluation.json": canonical(metrics)}, args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"FAIL evaluation: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
