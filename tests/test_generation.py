import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime
from decimal import localcontext

import pytest
from pydantic import ValidationError

from energy_reconciliation.cli import main
from energy_reconciliation.data_generation.expectations import (
    EXCEPTION_SCENARIOS,
    NORMAL_SCENARIOS,
    GroundTruth,
)
from energy_reconciliation.data_generation.export import TABLE_MODELS, build_export, export_dataset
from energy_reconciliation.data_generation.generator import digest, generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.data_generation.validation import validate_dataset
from energy_reconciliation.models.records import Payment, Reversal


@pytest.fixture(scope="module")
def data():
    return generate_dataset(
        GenerationSettings(customer_count=30, billing_periods=4, discrepancy_rate="0.5")
    )


def test_deterministic_and_path_independent(data, tmp_path):
    other = generate_dataset(
        GenerationSettings(
            customer_count=30,
            billing_periods=4,
            discrepancy_rate="0.500",
            output_dir=tmp_path / "other",
        )
    )
    assert build_export(data)[0] == build_export(other)[0]
    assert data.manifest_record == other.manifest_record
    changed = generate_dataset(
        GenerationSettings(customer_count=30, billing_periods=4, discrepancy_rate="0.5", seed=43)
    )
    assert changed.manifest_record.id != data.manifest_record.id
    assert changed.invoices[0].amount_cents != data.invoices[0].amount_cents


def test_computer_clock_is_not_used(monkeypatch, data):
    class OtherClock(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("Generation must not use wall-clock time")

    monkeypatch.setattr("energy_reconciliation.data_generation.generator.datetime", OtherClock)
    assert generate_dataset(data.settings).manifest_record == data.manifest_record


def test_generation_independent_of_callers_decimal_precision(data):
    with localcontext() as context:
        context.prec = 3
        assert generate_dataset(data.settings).manifest_record == data.manifest_record


def test_relationships_identifiers_and_schema_compatibility(data):
    summary = validate_dataset(data)
    assert len(data.customers) == 30
    assert len(data.accounts) == 36
    assert len(data.invoices) == 144
    assert len(data.invoice_items) == 288
    assert {c.customer_type for c in data.customers} == {"private", "small_business"}
    assert {a.energy_type for a in data.accounts} == {"electricity", "gas"}
    assert sum(summary["scenario_counts"].values()) == 72
    for rows in data.business_tables().values():
        for row in rows:
            assert row.id.startswith("syn_") and len(row.id.rsplit("_", 1)[1]) == 32
            assert type(row).model_validate_json(row.model_dump_json()) == row


def test_distribution_and_zero_rate(data):
    counts = Counter(c.scenario for c in data.ground_truth.cases)
    assert set(counts) == set(EXCEPTION_SCENARIOS + NORMAL_SCENARIOS)
    assert sum(counts[s] for s in EXCEPTION_SCENARIOS) == 36
    assert all(counts[s] == 9 for s in NORMAL_SCENARIOS)
    assert (
        max(counts[s] for s in EXCEPTION_SCENARIOS) - min(counts[s] for s in EXCEPTION_SCENARIOS)
        <= 1
    )
    normal = generate_dataset(
        GenerationSettings(customer_count=8, billing_periods=2, discrepancy_rate="0")
    )
    assert not normal.reversals and not normal.corrections
    assert {c.scenario for c in normal.ground_truth.cases} == set(NORMAL_SCENARIOS)


@pytest.mark.parametrize("scenario", EXCEPTION_SCENARIOS + NORMAL_SCENARIOS)
def test_every_scenario_has_expected_financial_behavior(data, scenario):
    case = next(c for c in data.ground_truth.cases if c.scenario == scenario)
    invoices = {i.id: i for i in data.invoices}
    payments = {p.id: p for p in data.payments}
    balances = {b.invoice_id: b for b in data.ground_truth.invoice_balances}
    applications = [
        a for a in data.ground_truth.expected_applications if a.payment_id in case.payment_ids
    ]
    bills = [invoices[key] for key in case.invoice_ids]
    paid = [payments[key] for key in case.payment_ids]
    if scenario == "unpaid":
        assert paid == []
        assert all(balances[i.id].outstanding_cents == i.amount_cents for i in bills)
    elif scenario in ("missing_reference", "incorrect_reference", "ambiguous"):
        assert applications == []
        assert all(
            a.reason_code == "intent_only"
            for a in data.ground_truth.intended_relationships
            if a.payment_id in case.payment_ids
        )
        assert all(p.id in data.ground_truth.expected_manual_review_payment_ids for p in paid)
        assert all(balances[i.id].outstanding_cents == i.amount_cents for i in bills)
        if scenario == "missing_reference":
            assert all(p.reference is None for p in paid)
        elif scenario == "incorrect_reference":
            assert all(p.reference not in {i.reference for i in data.invoices} for p in paid)
        else:
            assert len(paid) == 1 and bills[0].amount_cents == bills[1].amount_cents
    elif scenario == "partial":
        for invoice in bills:
            assert (
                balances[invoice.id].outstanding_cents
                == invoice.amount_cents - invoice.amount_cents * 3 // 5
            )
    elif scenario == "chargeback":
        reversals = [r for r in data.reversals if r.payment_id in case.payment_ids]
        assert len(reversals) == len(paid)
        assert all(
            r.kind == "chargeback" and r.amount_cents == payments[r.payment_id].amount_cents
            for r in reversals
        )
        assert all(balances[i.id].outstanding_cents == i.amount_cents for i in bills)
        assert len(
            [
                r
                for r in data.ground_truth.expected_releases
                if r.reversal_id in {event.id for event in reversals}
            ]
        ) == len(paid)
    else:
        assert all(balances[i.id].outstanding_cents == 0 for i in bills)
    if scenario == "combined":
        assert len(paid) == 1 and len(applications) == 2
        assert paid[0].amount_cents == sum(i.amount_cents for i in bills)
        assert paid[0].reference == " | ".join(i.reference for i in bills)
    elif scenario == "multiple_payments":
        assert len(paid) == 4
        assert sum(p.amount_cents for p in paid) == sum(i.amount_cents for i in bills)
    elif scenario in ("overpayment", "refund"):
        assert sum(p.amount_cents for p in paid) > sum(i.amount_cents for i in bills)
        pbalances = {b.payment_id: b for b in data.ground_truth.payment_balances}
        assert all(
            (pbalances[p.id].unapplied_cents > 0) == (scenario == "overpayment") for p in paid
        )
    elif scenario == "correction":
        for invoice in bills:
            correction = next(c for c in data.corrections if c.invoice_id == invoice.id)
            assert correction.amount_cents == -(invoice.amount_cents // 10)
            assert (
                balances[invoice.id].adjusted_face_cents
                == invoice.amount_cents + correction.amount_cents
            )
    elif scenario in NORMAL_SCENARIOS:
        for invoice, payment in zip(bills, paid, strict=True):
            if scenario == "correct":
                assert payment.booked_on == invoice.due_on
            elif scenario == "early":
                assert invoice.issued_on <= payment.booked_on < invoice.due_on
            elif scenario == "late":
                assert payment.booked_on > invoice.due_on
            else:
                assert payment.booked_on.strftime("%Y-%m") != invoice.issued_on.strftime("%Y-%m")


def test_item_tax_rounding_and_exact_integers(data):
    gross = defaultdict(int)
    for item in data.invoice_items:
        # Independent integer half-up check for positive cents * 19%.
        assert item.tax_cents == (item.net_cents * 19 + 50) // 100
        assert item.gross_cents == item.net_cents + item.tax_cents
        gross[item.invoice_id] += item.gross_cents
    assert all(gross[i.id] == i.amount_cents for i in data.invoices)
    assert all(type(p.amount_cents) is int for p in data.payments)


@pytest.mark.parametrize("cutoff", ["2025-01-01", "2025-01-15", "2025-02-01", "2025-05-01"])
def test_evaluation_date_projects_without_future_cash(cutoff):
    sample = generate_dataset(
        GenerationSettings(
            customer_count=20, billing_periods=2, discrepancy_rate="1", evaluation_date=cutoff
        )
    )
    validate_dataset(sample)
    received = sum(b.received_cents for b in sample.ground_truth.payment_balances)
    assert received == sum(
        p.amount_cents for p in sample.payments if p.booked_on <= date.fromisoformat(cutoff)
    )
    assert all(b.outstanding_cents >= 0 for b in sample.ground_truth.invoice_balances)


def test_refund_and_chargeback_snapshot_boundaries(data):
    for kind in ("refund", "chargeback"):
        event = next(r for r in data.reversals if r.kind == kind)
        # Use the already authored timeline to evaluate each side of the cash outflow.
        payment = next(p for p in data.payments if p.id == event.payment_id)
        app = next(a for a in data.ground_truth.expected_applications if a.payment_id == payment.id)
        if kind == "refund":
            assert payment.amount_cents - app.amount_cents == event.amount_cents
            assert not any(r.reversal_id == event.id for r in data.ground_truth.expected_releases)
        else:
            release = next(
                r for r in data.ground_truth.expected_releases if r.reversal_id == event.id
            )
            assert (
                release.effective_on == event.booked_on and release.amount_cents == app.amount_cents
            )
        assert event.booked_on > payment.booked_on


def test_export_checksums_duplicate_receipts_and_round_trip(data):
    files, manifest = build_export(data)
    assert not any("ground_truth" in name for name in manifest["input_files"])
    assert manifest["evaluation_files"] == ["evaluation/ground_truth.json"]
    assert (
        GroundTruth.model_validate_json(files["evaluation/ground_truth.json"]) == data.ground_truth
    )
    for path, checksum in manifest["file_sha256"].items():
        assert hashlib.sha256(files[path]).hexdigest() == checksum
    accepted = {
        r["import_id"]: r
        for r in manifest["statement_receipts"]
        if r["expected_outcome"] == "accepted"
    }
    duplicate = [r for r in manifest["statement_receipts"] if r["expected_outcome"] == "duplicate"]
    assert duplicate
    for receipt in duplicate:
        assert files[receipt["path"]] == files[accepted[receipt["import_id"]]["path"]]
    canonical_events = {r.id: r for r in (*data.payments, *data.reversals)}
    observed = []
    for receipt in accepted.values():
        for row in csv.DictReader(io.StringIO(files[receipt["path"]].decode("utf-8"))):
            model = Payment if row["event_kind"] == "payment" else Reversal
            record = model.model_validate_json(row["record_json"])
            assert canonical_events[record.id] == record
            observed.append(record.id)
    assert len(observed) == len(set(observed)) == len(canonical_events)
    for name, records in data.business_tables().items():
        rows = list(csv.DictReader(io.StringIO(files[f"inputs/{name}.csv"].decode("utf-8"))))
        reconstructed = []
        for row in rows:
            for key, value in row.items():
                if value == "":
                    row[key] = None
                elif key == "synthetic" or key == "candidate_invoice_ids":
                    row[key] = json.loads(value)
                elif key.endswith("_cents") or key in ("row_count", "line_number", "row_number"):
                    row[key] = int(value)
            reconstructed.append(TABLE_MODELS[name].model_validate(row))
        assert tuple(reconstructed) == records


def test_export_safe_reruns_and_refusal(data, tmp_path):
    target = tmp_path / "dataset"
    manifest = export_dataset(data, target)
    before = {
        p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    assert export_dataset(data, target) == manifest
    assert before == {
        p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    (target / "keep.txt").write_text("user work", encoding="utf-8")
    with pytest.raises(ValueError, match="choose a new output"):
        export_dataset(data, target)
    assert (target / "keep.txt").read_text() == "user work"


def test_integrity_validation_detects_tampering(data):
    with pytest.raises(ValueError, match="fingerprint"):
        validate_dataset(replace(data, payments=(data.payments[0], *data.payments)))
    bad_truth = data.ground_truth.model_copy(update={"expected_unmatched_payment_ids": ()})
    with pytest.raises(ValueError, match="unmatched"):
        validate_dataset(replace(data, ground_truth=bad_truth))


def rehashed(data):
    content = {
        name: [r.model_dump(mode="json") for r in rows]
        for name, rows in data.business_tables().items()
    }
    return replace(
        data,
        manifest_record=data.manifest_record.model_copy(update={"content_sha256": digest(content)}),
    )


@pytest.mark.parametrize(
    "fault, message",
    [
        ("duplicate_id", "duplicate business ID"),
        ("orphan_account", "orphan account"),
        ("orphan_reversal", "orphan reversal"),
        ("line_total", "line total"),
        ("cash_bound", "payment allocation bound"),
    ],
)
def test_cross_record_checks_reject_invalid_relationships(data, fault, message):
    if fault == "duplicate_id":
        broken = replace(data, customers=(data.customers[0], *data.customers))
    elif fault == "orphan_account":
        account = data.accounts[0].model_copy(update={"customer_id": "syn_missing_customer"})
        broken = replace(data, accounts=(account, *data.accounts[1:]))
    elif fault == "orphan_reversal":
        reversal = data.reversals[0].model_copy(update={"payment_id": "syn_missing_payment"})
        broken = replace(data, reversals=(reversal, *data.reversals[1:]))
    elif fault == "line_total":
        invoice = data.invoices[0].model_copy(
            update={"amount_cents": data.invoices[0].amount_cents + 1}
        )
        broken = replace(data, invoices=(invoice, *data.invoices[1:]))
    else:
        case = next(c for c in data.ground_truth.cases if c.scenario == "correct")
        broken = replace(
            data,
            payments=tuple(
                p.model_copy(update={"amount_cents": 1}) if p.id == case.payment_ids[0] else p
                for p in data.payments
            ),
        )
    with pytest.raises(ValueError, match=message):
        validate_dataset(rehashed(broken))


def test_small_golden_example():
    sample = generate_dataset(
        GenerationSettings(customer_count=1, billing_periods=1, discrepancy_rate="0")
    )
    assert [(i.net_cents, i.tax_cents, i.gross_cents) for i in sample.invoice_items] == [
        (1225, 233, 1458),
        (7099, 1349, 8448),
    ]
    assert sample.invoices[0].amount_cents == sample.payments[0].amount_cents == 9906
    assert sample.invoices[0].reference == "SYN-RE-202501-000001"
    assert sample.ground_truth.invoice_balances[0].outstanding_cents == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"customer_count": 0},
        {"billing_periods": 0},
        {"seed": True},
        {"discrepancy_rate": 0.1},
        {"discrepancy_rate": "NaN"},
        {"discrepancy_rate": "1.1"},
        {"start_date": "2025-01-01", "end_date": "2025-02-28"},
        {"evaluation_date": "2024-12-31"},
        {"start_date": "9999-01-01"},
    ],
)
def test_invalid_generation_configuration(updates):
    with pytest.raises(ValidationError):
        GenerationSettings(**updates)


def test_single_period_leap_year_and_clipped_boundaries():
    sample = generate_dataset(
        GenerationSettings(
            customer_count=3,
            billing_periods=1,
            start_date="2024-02-10",
            end_date="2024-02-29",
            discrepancy_rate="1",
        )
    )
    validate_dataset(sample)
    assert all(
        i.service_start == date(2024, 2, 10) and i.service_end == date(2024, 2, 29)
        for i in sample.invoices
    )
    assert build_export(sample)[1]["unavailable_scenarios"] == ["combined", "ambiguous"]


def test_cli_errors_and_help(tmp_path, capsys):
    assert main(["generate", "--customers", "0", "--output-dir", str(tmp_path / "unused")]) == 1
    assert "FAIL generation" in capsys.readouterr().err
    assert not (tmp_path / "unused").exists()
    with pytest.raises(SystemExit) as exit_info:
        main(["generate", "--help"])
    assert exit_info.value.code == 0
    assert "--evaluation-date" in capsys.readouterr().out


def test_cli_across_process_hash_seeds(tmp_path):
    directories = [tmp_path / "first", tmp_path / "second"]
    for hash_seed, directory in zip(("1", "999"), directories, strict=True):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "energy_reconciliation",
                "generate",
                "--customers",
                "12",
                "--billing-periods",
                "2",
                "--seed",
                "7",
                "--exception-rate",
                "1",
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-02-29",
                "--evaluation-date",
                "2024-04-30",
                "--output-dir",
                str(directory),
            ],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
        )
        assert "SYNTHETIC" in result.stdout
    first = {
        p.relative_to(directories[0]).as_posix(): p.read_bytes()
        for p in directories[0].rglob("*")
        if p.is_file()
    }
    second = {
        p.relative_to(directories[1]).as_posix(): p.read_bytes()
        for p in directories[1].rglob("*")
        if p.is_file()
    }
    assert first == second


def test_default_dataset_size_and_control_equations():
    sample = generate_dataset()
    summary = validate_dataset(sample)
    assert (len(sample.customers), len(sample.accounts), len(sample.invoices)) == (500, 600, 7200)
    assert len(sample.payments) > 5000
    assert sum(summary["scenario_counts"][s] for s in EXCEPTION_SCENARIOS) == 540
    totals = summary["totals"]
    assert (
        totals["adjusted_face_cents_as_of"] - totals["net_cash_cents_as_of"]
        == totals["outstanding_cents_as_of"] - totals["unapplied_cents_as_of"]
    )
    assert sample.manifest_record.content_sha256 == digest(
        {
            name: [r.model_dump(mode="json") for r in rows]
            for name, rows in sample.business_tables().items()
        }
    )
