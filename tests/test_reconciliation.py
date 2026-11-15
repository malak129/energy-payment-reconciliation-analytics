import ast
import csv
import hashlib
import inspect
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from energy_reconciliation.cli import main
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.evaluation import evaluate
from energy_reconciliation.ingestion.csv_dataset import InputDataset, load_dataset, midnight
from energy_reconciliation.models import records as m
from energy_reconciliation.reconciliation import engine
from energy_reconciliation.reconciliation.engine import default_options, reconcile
from energy_reconciliation.reconciliation.export import export_result
from energy_reconciliation.reconciliation.results import RunOptions
from energy_reconciliation.utilities.serialization import fingerprint

DAY = date(2025, 1, 15)
OPTIONS = default_options(date(2025, 2, 28))


def fields(kind, key, imported=False):
    values = {"id": f"syn_{kind}_{key}", "synthetic": True}
    if imported:
        values |= {"dataset_id": "syn_dataset_test", "source_record_id": f"SYN-{kind}-{key}"}
    return values


def invoice(
    key="001", amount=10000, account="syn_account_001", issued="2025-01-01", reference=None
):
    return m.Invoice(
        **fields("invoice", key, True),
        account_id=account,
        reference=reference or f"INV-{key}",
        issued_on=issued,
        due_on=date.fromisoformat(issued) + timedelta(days=14),
        service_start="2025-01-01",
        service_end="2025-01-31",
        amount_cents=amount,
    )


def payment(key="001", amount=10000, reference="INV-001", booked=DAY, account="syn_account_001"):
    return m.Payment(
        **fields("payment", key, True),
        source_system="SYN_TEST_BANK",
        bank_event_id=f"EVENT-P-{key}",
        booked_on=booked,
        value_on=booked,
        amount_cents=amount,
        account_id=account,
        reference=reference,
    )


def reversal(
    key="001", amount=10000, parent="syn_payment_001", kind="chargeback", booked="2025-01-22"
):
    return m.Reversal(
        **fields("reversal", key, True),
        source_system="SYN_TEST_BANK",
        bank_event_id=f"EVENT-R-{key}",
        payment_id=parent,
        kind=kind,
        amount_cents=amount,
        booked_on=booked,
        value_on=booked,
        reason="Synthetic linked cash outflow",
    )


def unit_data(invoices=None, payments=None, reversals=(), correction_specs=()):
    invoices = (invoice(),) if invoices is None else tuple(invoices)
    payments = (payment(),) if payments is None else tuple(payments)
    customer = m.Customer(**fields("customer", "001", True), display_name="Synthetic Customer Test")
    accounts = tuple(
        m.Account(
            **fields("account", key, True),
            customer_id=customer.id,
            contract_reference=f"SYN-CONTRACT-{key}",
            opened_on="2025-01-01",
            synthetic_iban="DE00" + key.zfill(18),
        )
        for key in ("001", "002")
    )
    items = tuple(
        m.InvoiceLine(
            **fields("item", str(index), True),
            invoice_id=i.id,
            line_number=1,
            description="Synthetic fixture",
            net_cents=i.amount_cents,
            tax_cents=0,
            gross_cents=i.amount_cents,
        )
        for index, i in enumerate(invoices)
    )
    cases, decisions, corrections = [], [], []
    for number, spec in enumerate(correction_specs):
        created = spec.get("created", "2025-01-02T12:00:00Z")
        key = str(number)
        cases.append(
            m.ReviewCase(
                **fields("case", key),
                invoice_id=spec.get("invoice_id", invoices[0].id),
                run_id="syn_run_approval",
                reason_code="invoice_correction",
                reason="Synthetic correction",
                created_at=created,
            )
        )
        decisions.append(
            m.ManualDecision(
                **fields("decision", key),
                case_id=cases[-1].id,
                action="correct_invoice",
                actor="SYN_OPERATOR",
                reason="Synthetic approval",
                created_at=created,
            )
        )
        corrections.append(
            m.Correction(
                **fields("correction", key),
                invoice_id=cases[-1].invoice_id,
                decision_id=decisions[-1].id,
                amount_cents=spec["amount"],
                effective_on=spec.get("effective", "2025-01-02"),
                created_at=created,
                reason="Synthetic receivable adjustment",
                reverses_correction_id=spec.get("undo"),
            )
        )
    run = m.ReconciliationRun(
        **fields("run", "approval"),
        dataset_id="syn_dataset_test",
        input_sha256="0" * 64,
        result_sha256="1" * 64,
        config_sha256="2" * 64,
        rules_version="unit-approval",
        as_of="2025-02-28",
        known_at="2025-01-01T00:00:00Z",
        started_at="2025-01-01T00:00:00Z",
        completed_at="2025-02-28T00:00:00Z",
        status="completed",
    )
    dataset = m.Dataset(
        **fields("dataset", "test"),
        generator_version="test",
        seed=1,
        config_sha256="0" * 64,
        content_sha256="1" * 64,
        effective_at=OPTIONS.known_at,
    )
    tables = {
        "customers": (customer,),
        "accounts": accounts,
        "invoices": invoices,
        "invoice_items": items,
        "payments": payments,
        "refunds_chargebacks": tuple(reversals),
        "corrections": tuple(corrections),
        "review_cases": tuple(cases),
        "manual_decisions": tuple(decisions),
        "authoring_runs": (run,) if cases else (),
    }
    known = {e.id: midnight(e.booked_on) for e in (*payments, *reversals)}
    return InputDataset(dataset, tables, known, "3" * 64, {})


@pytest.mark.parametrize("reference", ["INV-001", "inv-001", "  Inv-001  "])
def test_exact_reference_normalization_and_evidence(reference):
    result = reconcile(unit_data(payments=[payment(reference=reference)]), OPTIONS)
    assert len(result.allocations) == len(result.evidence) == 1
    assert result.allocations[0].amount_cents == 10000
    assert result.evidence[0].rule_id == "REF-SINGLE-1"
    assert result.evidence[0].normalized_invoice_reference == "INV-001"
    assert result.invoices[0].outstanding_cents == 0
    assert result.payments[0].allocation_status == "allocated"


def test_unique_reference_can_infer_missing_account():
    result = reconcile(unit_data(payments=[payment(account=None)]), OPTIONS)
    assert result.payments[0].validated_account_id == "syn_account_001"
    assert result.evidence[0].account_evidence == "unique_reference_account"


def test_account_mismatch_even_for_same_customer_never_allocates():
    result = reconcile(unit_data(payments=[payment(account="syn_account_002")]), OPTIONS)
    assert not result.allocations
    assert result.review_queue[0].reason_code == "account_mismatch"
    assert result.controls["suspense_cents"] == 10000


@pytest.mark.parametrize(
    "reference, reason",
    [
        (None, "missing_reference"),
        ("WRONG", "unknown_reference"),
        ("I NV-001", "unknown_reference"),
    ],
)
def test_no_matching_by_amount_name_or_fuzzy_reference(reference, reason):
    result = reconcile(unit_data(payments=[payment(reference=reference)]), OPTIONS)
    assert not result.allocations
    assert result.review_queue[0].reason_code == reason
    assert len(result.review_queue[0].candidates) == 1
    assert result.controls["unmatched_event_count"] == 1


def test_ambiguous_amount_candidates_are_only_review_evidence():
    result = reconcile(
        unit_data(
            invoices=[invoice(), invoice("002")],
            payments=[payment(reference="Unstructured transfer")],
        ),
        OPTIONS,
    )
    assert not result.allocations
    assert result.review_queue[0].reason_code == "ambiguous"
    assert len(result.review_queue[0].candidates) == 2
    assert result.payments[0].classification == "ambiguous"


def test_partial_and_multiple_receipts_distinguish_invoice_from_payment():
    partial = reconcile(unit_data(payments=[payment(amount=3000)]), OPTIONS)
    assert partial.payments[0].allocation_status == "allocated"
    assert partial.payments[0].classification == "partial_payment"
    assert partial.invoices[0].status == "partial"
    assert partial.invoices[0].outstanding_cents == 7000
    data = unit_data(
        payments=[payment(amount=3000), payment("002", 7000, booked=date(2025, 1, 16))]
    )
    complete = reconcile(data, OPTIONS)
    assert len(complete.allocations) == 2
    assert complete.invoices[0].status == "settled"
    assert not any(e.reason_code == "amount_mismatch" for e in complete.exceptions)


def test_combined_requires_exact_explicit_same_account_open_sum():
    data = unit_data(
        invoices=[invoice(), invoice("002", 5000)],
        payments=[payment(amount=15000, reference="INV-001 | inv-002")],
    )
    result = reconcile(data, OPTIONS)
    assert sorted(a.amount_cents for a in result.allocations) == [5000, 10000]
    assert all(e.rule_id == "REF-COMBINED-1" for e in result.evidence)
    assert result.controls["outstanding_cents"] == 0


@pytest.mark.parametrize(
    "reference, amount",
    [
        ("INV-001 | INV-002", 14000),
        ("INV-001 | INV-001", 20000),
        ("INV-001 |", 10000),
        ("INV-001 | UNKNOWN", 15000),
    ],
)
def test_combined_ambiguity_never_creates_partial_split(reference, amount):
    result = reconcile(
        unit_data(
            invoices=[invoice(), invoice("002", 5000)],
            payments=[payment(amount=amount, reference=reference)],
        ),
        OPTIONS,
    )
    assert not result.allocations
    assert len(result.review_queue) == 1


def test_overpayment_and_already_settled_reference_become_account_credit():
    result = reconcile(unit_data(payments=[payment(amount=10001)]), OPTIONS)
    assert result.controls["identified_credit_cents"] == 1
    assert result.review_queue[0].amount_cents == 1
    assert result.payments[0].classification == "overpaid"
    more = reconcile(unit_data(payments=[payment(), payment("002", 50)]), OPTIONS)
    assert more.controls["net_allocated_cents"] == 10000
    assert more.controls["unapplied_cents"] == 50


def test_unpaid_late_cross_month_and_future_invoice():
    unpaid = reconcile(unit_data(payments=[]), OPTIONS)
    assert unpaid.invoices[0].status == "open" and unpaid.invoices[0].overdue
    late = reconcile(unit_data(payments=[payment(booked=date(2025, 2, 3))]), OPTIONS)
    assert late.payments[0].late and late.payments[0].cross_month
    future = invoice(issued="2025-01-20").model_copy(update={"due_on": date(2025, 2, 3)})
    result = reconcile(unit_data(invoices=[future]), OPTIONS)
    assert not result.allocations and result.review_queue[0].reason_code == "invoice_not_open"


@pytest.mark.parametrize(
    "kind, received, outgoing, allocated, outstanding, release_count",
    [
        ("refund", 12000, 2000, 10000, 0, 0),
        ("refund", 12000, 3000, 9000, 1000, 1),
        ("chargeback", 10000, 4000, 6000, 4000, 1),
        ("chargeback", 10000, 10000, 0, 10000, 1),
    ],
)
def test_outflows_consume_credit_then_release_exact_amount(
    kind, received, outgoing, allocated, outstanding, release_count
):
    result = reconcile(
        unit_data(
            payments=[payment(amount=received)], reversals=[reversal(amount=outgoing, kind=kind)]
        ),
        OPTIONS,
    )
    assert result.controls["net_cash_cents"] == received - outgoing
    assert result.controls["net_allocated_cents"] == allocated
    assert result.controls["outstanding_cents"] == outstanding
    assert len(result.releases) == release_count
    assert result.adjustments[0].signed_cash_cents == -outgoing
    assert result.invoices[0].original_cents == 10000


def test_repeated_reversals_never_release_more_than_original():
    result = reconcile(
        unit_data(reversals=[reversal(amount=4000), reversal("002", 6000, booked="2025-01-23")]),
        OPTIONS,
    )
    assert sum(r.amount_cents for r in result.releases) == 10000
    assert result.payments[0].allocation_status == "reversed"
    assert result.controls["net_cash_cents"] == 0


def test_combined_full_reversal_has_unique_release_vector():
    data = unit_data(
        invoices=[invoice(), invoice("002", 5000)],
        payments=[payment(amount=15000, reference="INV-001 | INV-002")],
        reversals=[reversal(amount=15000)],
    )
    result = reconcile(data, OPTIONS)
    assert len(result.releases) == 2 and not result.review_queue
    assert result.controls["outstanding_cents"] == 15000


def test_ambiguous_partial_release_holds_payment_without_choosing_invoice():
    data = unit_data(
        invoices=[invoice(), invoice("002", 5000)],
        payments=[payment(amount=15000, reference="INV-001 | INV-002")],
        reversals=[reversal(amount=3000)],
    )
    result = reconcile(data, OPTIONS)
    assert not result.allocations and not result.releases
    assert result.controls["net_cash_cents"] == result.controls["unapplied_cents"] == 12000
    assert result.controls["outstanding_cents"] == 15000
    assert result.review_queue[0].reason_code == "reversal_conflict"
    assert len(result.review_queue[0].candidates) == 2
    assert result.source_counts["reversal_hold_payment_count"] == 1
    assert reconcile(data, OPTIONS) == result


@pytest.mark.parametrize(
    "amount, receipt, expected_face", [(-2000, 8000, 8000), (2000, 12000, 12000)]
)
def test_approved_corrections_change_debt_not_cash(amount, receipt, expected_face):
    data = unit_data(payments=[payment(amount=receipt)], correction_specs=[{"amount": amount}])
    result = reconcile(data, OPTIONS)
    assert result.invoices[0].original_cents == 10000
    assert result.invoices[0].adjusted_face_cents == expected_face
    assert result.invoices[0].adjusted and result.invoices[0].status == "settled"
    assert result.adjustments[0].signed_cash_cents == 0
    assert result.controls["signed_correction_cents"] == amount


def test_correction_undo_and_below_allocation_reduction():
    data = unit_data(
        payments=[payment(amount=8000)],
        correction_specs=[
            {"amount": -2000},
            {
                "amount": 2000,
                "effective": "2025-01-20",
                "created": "2025-01-20T12:00:00Z",
                "undo": "syn_correction_0",
            },
        ],
    )
    result = reconcile(data, OPTIONS)
    assert result.controls["signed_correction_cents"] == 0
    assert result.controls["outstanding_cents"] == 2000
    invalid = unit_data(correction_specs=[{"amount": -2000, "effective": "2025-01-20"}])
    with pytest.raises(ValueError, match="explicit allocation releases"):
        reconcile(invalid, OPTIONS)


def test_evaluation_and_historical_known_at_are_independent_cutoffs():
    data = unit_data()
    data = replace(data, bank_known_at={"syn_payment_001": datetime(2025, 1, 31, 12, tzinfo=UTC)})
    before_receipt = RunOptions(evaluation_date="2025-02-28", known_at="2025-01-30T23:59:59Z")
    result = reconcile(data, before_receipt)
    assert not result.payments and result.controls["outstanding_cents"] == 10000
    after_receipt = RunOptions(evaluation_date="2025-01-15", known_at="2025-01-31T12:00:00Z")
    assert reconcile(data, after_receipt).controls["outstanding_cents"] == 0
    before_booking = RunOptions(evaluation_date="2025-01-14", known_at="2025-02-28T00:00:00Z")
    assert not reconcile(data, before_booking).payments
    with pytest.raises(ValueError, match="UTC offset"):
        reconcile(data, RunOptions(evaluation_date="2025-01-15", known_at="2025-01-31T12:00:00"))


def test_late_known_backdated_correction_restates_without_changing_originals():
    data = unit_data(
        payments=[payment(amount=8000)],
        correction_specs=[{"amount": -2000, "created": "2025-02-01T12:00:00Z"}],
    )
    early = reconcile(
        data, RunOptions(evaluation_date="2025-01-31", known_at="2025-01-31T23:59:59Z")
    )
    late = reconcile(
        data, RunOptions(evaluation_date="2025-01-31", known_at="2025-02-02T00:00:00Z")
    )
    assert early.controls["outstanding_cents"] == 2000
    assert late.controls["outstanding_cents"] == 0
    assert data.rows("invoices")[0].amount_cents == 10000


@pytest.mark.parametrize(
    "fault, message",
    [
        ("orphan", "Orphan reversal"),
        ("excess", "exceed original cash"),
        ("duplicate", "Duplicate record ID"),
        ("reference", "Duplicate normalized"),
        ("approval", "Orphan correction"),
    ],
)
def test_critical_invalid_input_fails_before_results(fault, message):
    if fault == "orphan":
        data = unit_data(reversals=[reversal(parent="syn_missing_payment")])
    elif fault == "excess":
        data = unit_data(reversals=[reversal(amount=10001)])
    elif fault == "duplicate":
        data = unit_data(payments=[payment(), payment()])
    elif fault == "reference":
        data = unit_data(invoices=[invoice(), invoice("002", reference="inv-001")])
    else:
        data = unit_data(correction_specs=[{"amount": -1000}])
        data = replace(data, tables={**data.tables, "manual_decisions": ()})
    with pytest.raises(ValueError, match=message):
        reconcile(data, OPTIONS)


def test_deterministic_ids_order_conservation_and_result_hash():
    data = unit_data(
        invoices=[invoice(), invoice("002", 5000)],
        payments=[payment(), payment("002", 5000, "INV-002")],
    )
    before = fingerprint(
        {name: [r.model_dump(mode="json") for r in rows] for name, rows in data.tables.items()}
    )
    result = reconcile(data, OPTIONS)
    reordered = replace(
        data, tables={name: tuple(reversed(rows)) for name, rows in data.tables.items()}
    )
    assert reconcile(reordered, OPTIONS) == result == reconcile(data, OPTIONS)
    offset = RunOptions(evaluation_date="2025-02-28", known_at="2025-03-01T00:59:59.999999+01:00")
    assert reconcile(data, offset) == result
    assert result.run.result_sha256 == fingerprint(result.model_dump(mode="json", exclude={"run"}))
    assert len({a.id for a in result.allocations}) == len(result.allocations)
    assert len({e.allocation_id for e in result.evidence}) == len(result.allocations)
    assert (
        result.controls["cash_control_difference_cents"]
        == result.controls["receivable_control_difference_cents"]
        == 0
    )
    assert before == fingerprint(
        {name: [r.model_dump(mode="json") for r in rows] for name, rows in data.tables.items()}
    )


def test_large_control_totals_remain_exact_python_integers():
    from energy_reconciliation.utilities.money import MAX_CENTS

    data = unit_data(
        invoices=[invoice(amount=MAX_CENTS), invoice("002", MAX_CENTS)],
        payments=[payment(amount=MAX_CENTS - 1), payment("002", MAX_CENTS, "INV-002")],
    )
    result = reconcile(data, OPTIONS)
    assert result.controls["net_allocated_cents"] == 2 * MAX_CENTS - 1
    assert result.controls["unapplied_cents"] == 0
    assert result.controls["outstanding_cents"] == 1


def test_empty_known_snapshot_has_zero_controls():
    result = reconcile(
        unit_data(), RunOptions(evaluation_date="2025-02-28", known_at="2024-12-31T23:59:59Z")
    )
    assert not result.payments and not result.invoices
    assert all(amount == 0 for amount in result.controls.values())


def test_correction_approval_reuse_and_invalid_chronology_fail():
    data = unit_data(correction_specs=[{"amount": -1000}, {"amount": -1000}])
    corrections = data.rows("corrections")
    reused = corrections[1].model_copy(update={"decision_id": corrections[0].decision_id})
    broken = replace(data, tables={**data.tables, "corrections": (corrections[0], reused)})
    with pytest.raises(ValueError, match="approval decision reused"):
        reconcile(broken, OPTIONS)
    decisions = data.rows("manual_decisions")
    old_decision = decisions[0].model_copy(update={"created_at": datetime(2025, 1, 1, tzinfo=UTC)})
    broken = replace(data, tables={**data.tables, "manual_decisions": (old_decision, decisions[1])})
    with pytest.raises(ValueError, match="approval date"):
        reconcile(broken, OPTIONS)


@pytest.fixture(scope="module")
def csv_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase3-input") / "dataset"
    export_dataset(
        generate_dataset(
            GenerationSettings(customer_count=30, billing_periods=4, discrepancy_rate="0.5")
        ),
        root,
    )
    return root


def test_csv_ingestion_deduplicates_and_preserves_raw_values(csv_root):
    data = load_dataset(csv_root)
    result = reconcile(data, default_options(data.dataset.effective_at.date()))
    assert data.duplicate_file_receipts > 0
    assert data.duplicate_event_representations > len(data.rows("payments"))
    assert any(p.duplicate_bank_event for p in data.provenance)
    assert all(p.synthetic is True for p in data.provenance)
    assert (
        dict(next(p for p in data.provenance if p.path.endswith("payments.csv")).original_values)[
            "synthetic"
        ]
        == "true"
    )
    assert result.controls["gross_incoming_cents"] == sum(
        p.amount_cents for p in data.rows("payments")
    )


def test_normal_reconciliation_never_opens_oracle_or_uses_generator(csv_root, monkeypatch):
    original = Path.read_bytes

    def guarded(path):
        assert "evaluation" not in path.parts, "Normal reconciliation tried reading oracle"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    data = load_dataset(csv_root)
    result = reconcile(data, default_options(data.dataset.effective_at.date()))
    assert result.allocations
    tree = ast.parse(inspect.getsource(engine))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("generation" in name or "evaluation" in name for name in imports)


def rewrite_csv(root, name, transform):
    path = root / f"inputs/{name}.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        headers, rows = reader.fieldnames, list(reader)
    transform(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["file_sha256"][f"inputs/{name}.csv"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("fault", ["float", "conflict", "checksum", "malformed_manifest"])
def test_malformed_critical_csv_and_manifest_fail(csv_root, tmp_path, fault):
    import shutil

    target = tmp_path / "bad"
    shutil.copytree(csv_root, target)
    if fault == "float":
        rewrite_csv(target, "payments", lambda rows: rows[0].update(amount_cents="1.0"))
    elif fault == "conflict":

        def conflict(rows):
            rows.append({**rows[0], "amount_cents": str(int(rows[0]["amount_cents"]) + 1)})

        rewrite_csv(target, "payments", conflict)
    elif fault == "checksum":
        (target / "inputs/payments.csv").write_text("corrupted", encoding="utf-8")
    else:
        (target / "manifest.json").write_text('{"synthetic":true}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(target)


def test_identical_duplicate_csv_event_is_not_cash(csv_root, tmp_path):
    import shutil

    target = tmp_path / "duplicate"
    shutil.copytree(csv_root, target)
    original = load_dataset(csv_root)
    rewrite_csv(target, "payments", lambda rows: rows.append(rows[0].copy()))
    duplicate = load_dataset(target)
    assert duplicate.rows("payments") == original.rows("payments")
    assert duplicate.duplicate_event_representations == original.duplicate_event_representations + 1


def test_source_manifest_cannot_traverse_into_evaluation(csv_root, tmp_path, monkeypatch):
    import shutil

    root = tmp_path / "traversal"
    shutil.copytree(csv_root, root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["statement_receipts"][0]["path"] = "inputs/../evaluation/ground_truth.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original = Path.read_bytes

    def guarded(path):
        assert "evaluation" not in path.parts, "Must reject traversal before opening oracle"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(ValueError, match="canonical"):
        load_dataset(root)


def test_cli_help_errors_and_safe_export(csv_root, tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["reconcile", "--help"])
    assert exit_info.value.code == 0 and "--known-at" in capsys.readouterr().out
    target = tmp_path / "result"
    assert main(["reconcile", "--input-dir", str(csv_root), "--output-dir", str(target)]) == 0
    assert "financial controls" in capsys.readouterr().out
    data = load_dataset(csv_root)
    result = reconcile(data, default_options(data.dataset.effective_at.date()))
    export_result(result, data, target)
    (target / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="choose a new output"):
        export_result(result, data, target)
    assert (
        main(
            [
                "reconcile",
                "--input-dir",
                str(csv_root),
                "--known-at",
                "2025-01-01T00:00:00",
                "--output-dir",
                str(tmp_path / "unused"),
            ]
        )
        == 1
    )
    assert "FAIL reconciliation" in capsys.readouterr().err


def test_cross_process_reconciliation_is_byte_identical(csv_root, tmp_path):
    outputs = [tmp_path / "one", tmp_path / "two"]
    for seed, target in zip(("7", "991"), outputs, strict=True):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "energy_reconciliation",
                "reconcile",
                "--input-dir",
                str(csv_root),
                "--output-dir",
                str(target),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
    assert {p.name: p.read_bytes() for p in outputs[0].iterdir()} == {
        p.name: p.read_bytes() for p in outputs[1].iterdir()
    }


def test_full_default_ground_truth_evaluation_is_separate(tmp_path):
    root = tmp_path / "full-default"
    generated = generate_dataset()
    export_dataset(generated, root)
    data = load_dataset(root)
    result = reconcile(data, default_options(data.dataset.effective_at.date()))
    metrics = evaluate(result, generated.ground_truth)
    assert metrics["correct_automatic_allocations"] == 6904
    assert metrics["incorrect_automatic_allocations"] == 0
    assert metrics["correct_releases"] == 98 and metrics["incorrect_releases"] == 0
    assert metrics["outstanding_differences"] == metrics["unapplied_differences"] == []
    assert (
        metrics["matching_precision_percent"]
        == metrics["expected_allocation_coverage_percent"]
        == "100.0000"
    )
    assert result.controls["outstanding_cents"] == 17363528
    assert result.controls["unapplied_cents"] == 8889316
    assert data.duplicate_file_receipts == 5 and data.duplicate_event_representations == 9721
    assert result.controls["unmatched_event_count"] == 245
    assert len(result.review_queue) == 343
    assert (
        result.controls["cash_control_difference_cents"]
        == result.controls["receivable_control_difference_cents"]
        == 0
    )


def test_evaluation_reports_false_allocation_instead_of_hiding_it(csv_root):
    data = load_dataset(csv_root)
    result = reconcile(data, default_options(data.dataset.effective_at.date()))
    from energy_reconciliation.data_generation.expectations import GroundTruth

    truth = GroundTruth.model_validate_json(
        (csv_root / "evaluation/ground_truth.json").read_bytes()
    )
    wrong = result.allocations[0].model_copy(
        update={"amount_cents": result.allocations[0].amount_cents + 1}
    )
    changed = result.model_copy(update={"allocations": (wrong, *result.allocations[1:])})
    metrics = evaluate(changed, truth)
    assert (
        metrics["incorrect_automatic_allocations"] == 1
        and metrics["missing_expected_allocations"] == 1
    )
