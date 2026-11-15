"""Evaluation-only authoring oracle. No reference matching is performed here."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from energy_reconciliation.models.records import Cents, Identifier, Record, Text

EXCEPTION_SCENARIOS = (
    "unpaid",
    "partial",
    "multiple_payments",
    "combined",
    "overpayment",
    "missing_reference",
    "incorrect_reference",
    "ambiguous",
    "refund",
    "chargeback",
    "correction",
)
NORMAL_SCENARIOS = ("correct", "early", "late", "cross_month")


class ScenarioCase(Record):
    scenario: Text
    invoice_ids: tuple[Identifier, ...]
    payment_ids: tuple[Identifier, ...]


class ExpectedApplication(Record):
    payment_id: Identifier
    invoice_id: Identifier
    amount_cents: Cents
    effective_on: date
    reason_code: Literal["exact_reference", "explicit_combined", "intent_only"] = "exact_reference"


class ExpectedRelease(Record):
    application_id: Identifier
    reversal_id: Identifier
    amount_cents: Cents
    effective_on: date


class ExpectedException(Record):
    subject_id: Identifier
    category: Text
    candidate_invoice_ids: tuple[Identifier, ...] = ()
    effective_on: date
    resolved_on: date | None = None


class InvoiceBalance(Record):
    invoice_id: Identifier
    adjusted_face_cents: int = Field(strict=True, ge=0)
    allocated_cents: int = Field(strict=True, ge=0)
    outstanding_cents: int = Field(strict=True, ge=0)


class PaymentBalance(Record):
    payment_id: Identifier
    received_cents: int = Field(strict=True, ge=0)
    reversed_cents: int = Field(strict=True, ge=0)
    allocated_cents: int = Field(strict=True, ge=0)
    unapplied_cents: int = Field(strict=True, ge=0)


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    synthetic: Literal[True] = True
    purpose: Literal["evaluation_only"] = "evaluation_only"
    dataset_id: Identifier
    evaluation_date: date
    cases: tuple[ScenarioCase, ...]
    intended_relationships: tuple[ExpectedApplication, ...]
    expected_applications: tuple[ExpectedApplication, ...]
    expected_releases: tuple[ExpectedRelease, ...]
    expected_exceptions: tuple[ExpectedException, ...]
    invoice_balances: tuple[InvoiceBalance, ...] = ()
    payment_balances: tuple[PaymentBalance, ...] = ()
    expected_unmatched_payment_ids: tuple[Identifier, ...] = ()
    expected_manual_review_payment_ids: tuple[Identifier, ...] = ()
