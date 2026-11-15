import importlib
import json
import logging
import pkgutil
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

import energy_reconciliation
from energy_reconciliation.cli import main
from energy_reconciliation.config import Settings, load_settings
from energy_reconciliation.models.records import (
    Account,
    Allocation,
    AllocationRelease,
    Correction,
    ImportRow,
    Invoice,
    InvoiceLine,
    Payment,
    ReconciliationRun,
    ReviewCase,
)
from energy_reconciliation.utilities.logging import JsonFormatter
from energy_reconciliation.utilities.money import MAX_CENTS, euros_to_cents, round_euros


def common():
    return {"id": "syn_record_001", "synthetic": True}


def imported():
    return {**common(), "dataset_id": "syn_dataset_001", "source_record_id": "source-1"}


def payment():
    return {
        **imported(),
        "source_system": "synthetic-bank",
        "bank_event_id": "event-1",
        "booked_on": "2026-01-15",
        "value_on": "2026-01-15",
        "amount_cents": 10001,
    }


def test_all_modules_import():
    modules = list(
        pkgutil.walk_packages(energy_reconciliation.__path__, energy_reconciliation.__name__ + ".")
    )
    assert len(modules) >= 14
    for module in modules:
        importlib.import_module(module.name)


def test_configuration_defaults_and_example():
    settings = load_settings(Path("config.example.toml"))
    assert settings.seed == 42
    assert settings.discrepancy_rate == Decimal("0.15")
    assert settings.database_path == Path("data/reconciliation.sqlite3").resolve()
    assert load_settings().currency == "EUR"


def test_config_relative_to_file_without_creating_outputs(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('data_dir = "inputs"\n', encoding="utf-8")
    assert load_settings(path).data_dir == tmp_path / "inputs"
    assert not (tmp_path / "inputs").exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"end_date": date(2025, 1, 1)},
        {"record_count": 0},
        {"seed": True},
        {"discrepancy_rate": 0.1},
        {"discrepancy_rate": "1.01"},
        {"discrepancy_rate": "NaN"},
        {"currency": "USD"},
        {"unknown": 1},
    ],
)
def test_invalid_configuration(updates):
    with pytest.raises(ValidationError):
        Settings(**updates)


def test_payment_valid_and_immutable():
    record = Payment.model_validate(payment())
    assert record.amount_cents == 10001
    assert record.booked_on == date(2026, 1, 15)
    assert record.reference is None
    with pytest.raises(ValidationError):
        record.amount_cents = 1


@pytest.mark.parametrize("value", [0, -1, 1.0, True, "100", MAX_CENTS + 1])
def test_money_field_rejects_invalid_cents(value):
    with pytest.raises(ValidationError):
        Payment.model_validate({**payment(), "amount_cents": value})


@pytest.mark.parametrize(
    "updates",
    [
        {"synthetic": False},
        {"synthetic": None},
        {"synthetic": 1},
        {"id": "real-1"},
        {"currency": "USD"},
        {"booked_on": "31.02.2026"},
        {"extra": "ignored?"},
    ],
)
def test_invalid_payment(updates):
    with pytest.raises(ValidationError):
        Payment.model_validate({**payment(), **updates})


def test_synthetic_flag_required():
    row = payment()
    del row["synthetic"]
    with pytest.raises(ValidationError):
        Payment.model_validate(row)


def test_invoice_date_validation():
    row = {
        **imported(),
        "account_id": "syn_account_001",
        "reference": "SYN-INV-1",
        "issued_on": "2026-01-01",
        "due_on": "2026-01-31",
        "service_start": "2025-12-01",
        "service_end": "2025-12-31",
        "amount_cents": 11900,
    }
    assert Invoice.model_validate(row).amount_cents == 11900
    with pytest.raises(ValidationError):
        Invoice.model_validate({**row, "due_on": "2025-12-31"})
    with pytest.raises(ValidationError):
        Invoice.model_validate({**row, "service_end": "2025-11-30"})


def test_invoice_line_total():
    row = {
        **imported(),
        "invoice_id": "syn_invoice_001",
        "line_number": 1,
        "description": "Synthetic electricity",
        "net_cents": 10000,
        "tax_cents": 1900,
        "gross_cents": 11900,
    }
    assert InvoiceLine.model_validate(row).gross_cents == 11900
    with pytest.raises(ValidationError):
        InvoiceLine.model_validate({**row, "gross_cents": 11901})


def test_synthetic_iban_and_account_dates():
    row = {
        **imported(),
        "customer_id": "syn_customer_001",
        "contract_reference": "SYN-1",
        "opened_on": "2026-01-01",
        "synthetic_iban": "DE00" + "0" * 18,
    }
    assert Account.model_validate(row).synthetic_iban.startswith("DE00")
    with pytest.raises(ValidationError):
        Account.model_validate({**row, "synthetic_iban": "DE89" + "0" * 18})
    with pytest.raises(ValidationError):
        Account.model_validate({**row, "closed_on": "2025-12-31"})


def test_correction_and_release_validation():
    row = {
        **common(),
        "invoice_id": "syn_invoice_001",
        "decision_id": "syn_decision_001",
        "amount_cents": -1,
        "effective_on": "2026-01-01",
        "created_at": "2026-01-01T00:00:00Z",
        "reason": "Synthetic correction",
    }
    assert Correction.model_validate(row).amount_cents == -1
    with pytest.raises(ValidationError):
        Correction.model_validate({**row, "amount_cents": 0})
    release = {
        **common(),
        "allocation_id": "syn_allocation_001",
        "amount_cents": 1,
        "effective_on": "2026-01-01",
        "created_at": "2026-01-01T00:00:00Z",
        "reason": "Synthetic release",
    }
    with pytest.raises(ValidationError):
        AllocationRelease.model_validate(release)
    assert (
        AllocationRelease.model_validate(
            {
                **release,
                "reversal_id": "syn_reversal_001",
            }
        ).amount_cents
        == 1
    )
    with pytest.raises(ValidationError):
        AllocationRelease.model_validate(
            {
                **release,
                "reversal_id": "syn_reversal_001",
                "decision_id": "syn_decision_001",
            }
        )


def test_run_timestamps():
    row = {
        **common(),
        "dataset_id": "syn_dataset_001",
        "input_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "rules_version": "1",
        "as_of": "2026-01-31",
        "started_at": "2026-02-01T00:00:00Z",
        "status": "running",
        "known_at": "2026-02-01T00:00:00Z",
    }
    assert ReconciliationRun.model_validate(row).completed_at is None
    for updates in (
        {"started_at": "2026-02-01T00:00:00"},
        {"status": "completed"},
        {"status": "completed", "completed_at": "2026-01-31T00:00:00Z"},
        {"known_at": "2026-02-02T00:00:00Z"},
    ):
        with pytest.raises(ValidationError):
            ReconciliationRun.model_validate({**row, **updates})
    assert (
        ReconciliationRun.model_validate(
            {
                **row,
                "status": "completed",
                "completed_at": "2026-02-01T01:00:00Z",
                "result_sha256": "c" * 64,
            }
        ).status
        == "completed"
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0.01", 1),
        ("-0.01", -1),
        ("100.10", 10010),
        (Decimal("0.00"), 0),
        ("90000000000000.00", MAX_CENTS),
    ],
)
def test_exact_money(value, expected):
    assert euros_to_cents(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        1.1,
        True,
        "0.001",
        "NaN",
        "Infinity",
        "90000000000000.01",
        "invalid",
        "1.000000000000000000000000000000001",
        "1e-1000000",
    ],
)
def test_invalid_money(value):
    with pytest.raises(ValueError):
        euros_to_cents(value)


def test_explicit_rounding():
    assert round_euros(Decimal("1.005")) == Decimal("1.01")
    assert round_euros(Decimal("-1.005")) == Decimal("-1.01")


def test_money_is_independent_of_callers_precision():
    with localcontext() as context:
        context.prec = 3
        assert euros_to_cents("10000.01") == 1000001
        assert round_euros(Decimal("10000.005")) == Decimal("10000.01")


def test_maximum_cents_and_json_validation():
    record = Payment.model_validate({**payment(), "amount_cents": MAX_CENTS})
    assert Payment.model_validate_json(record.model_dump_json()) == record


def test_manual_allocation_authority():
    row = {
        **common(),
        "payment_id": "syn_payment_001",
        "invoice_id": "syn_invoice_001",
        "run_id": "syn_run_001",
        "amount_cents": 1,
        "effective_on": "2026-01-01",
        "created_at": "2026-01-01T01:00:00+01:00",
        "reason_code": "exact_reference",
        "confidence": "exact",
    }
    assert Allocation.model_validate(row).created_at.isoformat() == "2026-01-01T00:00:00+00:00"
    for updates in (
        {"reason_code": "manual_approved"},
        {"confidence": "manual"},
        {"decision_id": "syn_decision_001"},
    ):
        with pytest.raises(ValidationError):
            Allocation.model_validate({**row, **updates})
    assert (
        Allocation.model_validate(
            {
                **row,
                "reason_code": "manual_approved",
                "confidence": "manual",
                "decision_id": "syn_decision_001",
            }
        ).decision_id
        == "syn_decision_001"
    )


def test_invoice_correction_review_does_not_require_payment():
    row = {
        **common(),
        "invoice_id": "syn_invoice_001",
        "run_id": "syn_run_001",
        "reason_code": "invoice_correction",
        "reason": "Synthetic correction request",
        "created_at": "2026-01-01T00:00:00Z",
    }
    assert ReviewCase.model_validate(row).payment_id is None
    with pytest.raises(ValidationError):
        ReviewCase.model_validate({**row, "payment_id": "syn_payment_001"})
    with pytest.raises(ValidationError):
        ReviewCase.model_validate({**row, "reason_code": "ambiguous"})


def test_import_row_provenance():
    row = {
        **common(),
        "import_id": "syn_import_001",
        "row_number": 1,
        "payload_sha256": "a" * 64,
        "outcome": "accepted",
        "reason": "Validated",
    }
    with pytest.raises(ValidationError):
        ImportRow.model_validate(row)
    assert ImportRow.model_validate({**row, "record_id": "syn_payment_001"}).row_number == 1


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "doctor" in capsys.readouterr().out


def test_doctor(capsys):
    assert main(["doctor", "--config", "config.example.toml"]) == 0
    assert "PASS Phase 1" in capsys.readouterr().out


def test_check_bad_config(tmp_path, capsys):
    path = tmp_path / "bad.toml"
    path.write_text("currency = 'USD'", encoding="utf-8")
    assert main(["check", "--config", str(path)]) == 1
    assert "FAIL configuration" in capsys.readouterr().err


def test_doctor_missing_dependency(monkeypatch, capsys):
    monkeypatch.setattr("energy_reconciliation.cli.DEPENDENCIES", ("missing_synthetic_module",))
    assert main(["doctor"]) == 1
    assert "FAIL missing_synthetic_module" in capsys.readouterr().err


def test_doctor_missing_config(tmp_path, capsys):
    assert main(["doctor", "--config", str(tmp_path / "missing.toml")]) == 1
    assert "FAIL configuration" in capsys.readouterr().err


def test_json_logging():
    record = logging.LogRecord("energy_reconciliation", logging.INFO, "", 0, "event", (), None)
    output = json.loads(JsonFormatter().format(record))
    assert output["message"] == "event"
    assert output["timestamp"].endswith("+00:00")
