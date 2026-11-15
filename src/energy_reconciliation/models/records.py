"""Version 1 record contracts; these are not SQLAlchemy tables or import pipelines."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from energy_reconciliation.utilities.money import MAX_CENTS

Identifier = Annotated[str, StringConstraints(pattern=r"^syn_[a-z][a-z0-9_]{2,100}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Cents = Annotated[int, Field(strict=True, ge=1, le=MAX_CENTS)]
SignedCents = Annotated[int, Field(strict=True, ge=-MAX_CENTS, le=MAX_CENTS)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Identifier
    synthetic: Literal[True]  # Required on every record; never silently inferred.
    schema_version: Literal["1"] = "1"

    @field_validator("synthetic", mode="before")
    @classmethod
    def require_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("synthetic must be the boolean true")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def normalize_timestamp(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(UTC)
        return value


class ImportedRecord(Record):
    dataset_id: Identifier
    source_record_id: Text


class Dataset(Record):
    generator_version: Text
    seed: int = Field(strict=True, ge=0)
    config_sha256: Digest
    content_sha256: Digest
    effective_at: AwareDatetime


class Customer(ImportedRecord):
    display_name: Text
    customer_type: Literal["private", "small_business"] = "private"


class Account(ImportedRecord):
    customer_id: Identifier
    contract_reference: Text
    opened_on: date
    closed_on: date | None = None
    currency: Literal["EUR"] = "EUR"
    synthetic_iban: Annotated[str, StringConstraints(pattern=r"^DE00[0-9]{18}$")]
    energy_type: Literal["electricity", "gas"] = "electricity"

    @model_validator(mode="after")
    def check_dates(self) -> "Account":
        if self.closed_on is not None and self.closed_on < self.opened_on:
            raise ValueError("closed_on precedes opened_on")
        return self


class Invoice(ImportedRecord):
    account_id: Identifier
    reference: Text
    issued_on: date
    due_on: date
    service_start: date
    service_end: date
    amount_cents: Cents
    currency: Literal["EUR"] = "EUR"

    @model_validator(mode="after")
    def check_dates(self) -> "Invoice":
        if self.due_on < self.issued_on or self.service_end < self.service_start:
            raise ValueError("Invalid invoice date range")
        return self


class InvoiceLine(ImportedRecord):
    invoice_id: Identifier
    line_number: int = Field(strict=True, ge=1)
    description: Text
    net_cents: SignedCents
    tax_cents: SignedCents
    gross_cents: SignedCents

    @model_validator(mode="after")
    def check_total(self) -> "InvoiceLine":
        if self.net_cents + self.tax_cents != self.gross_cents:
            raise ValueError("net_cents + tax_cents must equal gross_cents")
        return self


class BankStatementImport(Record):
    dataset_id: Identifier
    source_system: Text
    file_sha256: Digest
    filename: Text
    imported_at: AwareDatetime
    row_count: int = Field(strict=True, ge=0)


class ImportRow(Record):
    import_id: Identifier
    row_number: int = Field(strict=True, ge=1)
    payload_sha256: Digest
    outcome: Literal["accepted", "duplicate", "rejected", "conflict"]
    record_id: Identifier | None = None
    reason: Text

    @model_validator(mode="after")
    def check_record_link(self) -> "ImportRow":
        if self.outcome in ("accepted", "duplicate") and self.record_id is None:
            raise ValueError("accepted and duplicate rows require record_id")
        return self


class Payment(ImportedRecord):
    source_system: Text
    bank_event_id: Text
    booked_on: date
    value_on: date
    amount_cents: Cents
    currency: Literal["EUR"] = "EUR"
    account_id: Identifier | None = None  # Claimed account, not an approved match.
    reference: Text | None = None


class Reversal(ImportedRecord):
    source_system: Text
    bank_event_id: Text
    payment_id: Identifier
    kind: Literal["refund", "chargeback"]
    amount_cents: Cents  # Positive magnitude of a cash outflow.
    booked_on: date
    value_on: date
    currency: Literal["EUR"] = "EUR"
    reason: Text


class ReconciliationRun(Record):
    dataset_id: Identifier
    input_sha256: Digest
    result_sha256: Digest | None = None
    rules_version: Text
    config_sha256: Digest
    as_of: date
    known_at: AwareDatetime
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    status: Literal["running", "completed", "failed"]

    @model_validator(mode="after")
    def check_completion(self) -> "ReconciliationRun":
        if self.known_at > self.started_at:
            raise ValueError("known_at must not exceed started_at")
        if (self.status == "running") != (self.completed_at is None):
            raise ValueError("Only running runs may omit completed_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at precedes started_at")
        if (self.status == "completed") != (self.result_sha256 is not None):
            raise ValueError("Only completed runs must have a result_sha256")
        return self


class Allocation(Record):
    payment_id: Identifier
    invoice_id: Identifier
    run_id: Identifier
    decision_id: Identifier | None = None
    amount_cents: Cents
    effective_on: date
    created_at: AwareDatetime
    reason_code: Literal["exact_reference", "explicit_combined", "manual_approved"]
    confidence: Literal["exact", "manual"]

    @model_validator(mode="after")
    def check_authority(self) -> "Allocation":
        manual = self.reason_code == "manual_approved"
        if manual != (self.decision_id is not None) or manual != (self.confidence == "manual"):
            raise ValueError("Manual allocations require a decision and manual confidence")
        return self


class AllocationRelease(Record):
    allocation_id: Identifier
    reversal_id: Identifier | None = None
    decision_id: Identifier | None = None
    amount_cents: Cents
    effective_on: date
    created_at: AwareDatetime
    reason: Text

    @model_validator(mode="after")
    def check_authority(self) -> "AllocationRelease":
        if (self.reversal_id is None) == (self.decision_id is None):
            raise ValueError("Provide exactly one reversal_id or decision_id")
        return self


class Correction(Record):
    invoice_id: Identifier
    decision_id: Identifier
    amount_cents: SignedCents  # Positive increases receivable; negative reduces it.
    effective_on: date
    created_at: AwareDatetime
    reason: Text
    reverses_correction_id: Identifier | None = None

    @model_validator(mode="after")
    def check_nonzero(self) -> "Correction":
        if self.amount_cents == 0:
            raise ValueError("A correction must be nonzero")
        return self


class ReviewCase(Record):
    payment_id: Identifier | None = None
    invoice_id: Identifier | None = None
    run_id: Identifier
    candidate_invoice_ids: tuple[Identifier, ...] = ()
    reason_code: Literal[
        "missing_reference",
        "ambiguous",
        "unknown_reference",
        "amount_mismatch",
        "account_mismatch",
        "overpayment",
        "reversal_conflict",
        "invoice_correction",
    ]
    reason: Text
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_subject(self) -> "ReviewCase":
        if (self.payment_id is None) == (self.invoice_id is None):
            raise ValueError("Provide exactly one payment_id or invoice_id")
        if (self.invoice_id is not None) != (self.reason_code == "invoice_correction"):
            raise ValueError("invoice_correction requires an invoice subject")
        if len(set(self.candidate_invoice_ids)) != len(self.candidate_invoice_ids):
            raise ValueError("Candidate invoice IDs must be unique")
        return self


class ManualDecision(Record):
    case_id: Identifier
    action: Literal["allocate", "release", "correct_invoice", "leave_unapplied", "reject"]
    actor: Text
    reason: Text
    created_at: AwareDatetime
    supersedes_decision_id: Identifier | None = None
    resolved_account_id: Identifier | None = None


class AuditEvent(Record):
    entity_type: Text
    entity_id: Identifier
    action: Text
    actor: Text
    occurred_at: AwareDatetime
    payload_sha256: Digest
    run_id: Identifier | None = None


class OperatorInvoice(ImportedRecord):
    operator_code: Annotated[str, StringConstraints(pattern=r"^SYN_OPERATOR_[A-Z0-9_]+$")]
    reference: Text
    issued_on: date
    due_on: date
    net_cents: SignedCents
    tax_cents: SignedCents
    gross_cents: Cents
    currency: Literal["EUR"] = "EUR"

    @model_validator(mode="after")
    def check_total(self) -> "OperatorInvoice":
        if self.net_cents + self.tax_cents != self.gross_cents or self.due_on < self.issued_on:
            raise ValueError("Invalid operator invoice total or date range")
        return self
