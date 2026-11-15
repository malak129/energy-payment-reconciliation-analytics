"""Typed snapshot projections; original financial entities remain unchanged."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from energy_reconciliation.models.records import (
    Allocation,
    AllocationRelease,
    Identifier,
    ReconciliationRun,
    Record,
)

RULES_VERSION = "reconciliation-1.0.0"


class RunOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    evaluation_date: date
    known_at: datetime

    def aware(self) -> None:
        if self.known_at.tzinfo is None or self.known_at.utcoffset() is None:
            raise ValueError("known_at requires an explicit UTC offset")


class MatchEvidence(Record):
    allocation_id: Identifier
    rule_id: Literal["REF-SINGLE-1", "REF-COMBINED-1", "MANUAL-1"]
    reason_code: str
    payment_reference: str | None
    invoice_reference: str
    normalized_invoice_reference: str
    account_evidence: Literal[
        "matching_account_claim", "unique_reference_account", "explicit_manual_decision"
    ]
    explanation: str


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    invoice_id: Identifier
    reference: str
    account_id: Identifier
    outstanding_cents: int = Field(strict=True, ge=0)


class ExceptionItem(Record):
    subject_type: Literal["payment", "invoice", "reversal"]
    subject_id: Identifier
    reason_code: str
    amount_cents: int = Field(strict=True, ge=0)
    requires_manual_review: bool
    explanation: str
    candidates: tuple[Candidate, ...] = ()


class PaymentOutcome(Record):
    payment_id: Identifier
    received_cents: StrictInt
    reversed_cents: StrictInt
    allocated_cents: StrictInt
    unapplied_cents: StrictInt
    validated_account_id: Identifier | None = None
    allocation_status: Literal["unapplied", "partial", "allocated", "reversed"]
    classification: Literal[
        "matched",
        "partial_payment",
        "overpaid",
        "unmatched",
        "ambiguous",
        "manual_review",
        "reversed",
        "adjusted",
        "manually_matched",
    ]
    late: bool | None
    cross_month: bool | None


class InvoiceOutcome(Record):
    invoice_id: Identifier
    original_cents: StrictInt
    correction_cents: StrictInt
    adjusted_face_cents: StrictInt
    allocated_cents: StrictInt
    outstanding_cents: StrictInt
    status: Literal["open", "partial", "settled", "cancelled"]
    adjusted: bool
    overdue: bool


class AdjustmentEffect(Record):
    source_record_id: Identifier
    kind: Literal["refund", "chargeback", "correction"]
    signed_cash_cents: StrictInt
    signed_receivable_cents: StrictInt
    released_cents: StrictInt
    reason: str


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    synthetic: Literal[True] = True
    rules_version: str = RULES_VERSION
    run: ReconciliationRun
    source_manifest_sha256: str
    source_hashes: dict[str, str]
    allocations: tuple[Allocation, ...]
    releases: tuple[AllocationRelease, ...]
    evidence: tuple[MatchEvidence, ...]
    adjustments: tuple[AdjustmentEffect, ...]
    payments: tuple[PaymentOutcome, ...]
    invoices: tuple[InvoiceOutcome, ...]
    exceptions: tuple[ExceptionItem, ...]
    review_queue: tuple[ExceptionItem, ...]
    controls: dict[str, StrictInt]
    exception_counts_by_reason: dict[str, StrictInt]
    source_counts: dict[str, StrictInt]
