"""Version 1 SQLAlchemy Core schema. Monetary projections have explicit SQLite checks."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

SCHEMA_VERSION = 1
APPLICATION_ID = 0x53594E45
metadata = MetaData()


def pk():
    return Column("id", String, primary_key=True)


def fk(name, target, nullable=False, primary_key=False):
    return Column(
        name,
        String,
        ForeignKey(target, ondelete="RESTRICT"),
        nullable=nullable,
        primary_key=primary_key,
        index=not primary_key,
    )


def money(name="amount_cents", positive=True):
    lower = "> 0" if positive else "!= 0"
    return (
        Column(name, Integer, nullable=False),
        CheckConstraint(
            f"typeof({name}) = 'integer' AND {name} {lower} "
            f"AND {name} BETWEEN -9000000000000000 AND 9000000000000000"
        ),
    )


schema_versions = Table(
    "schema_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", String, nullable=False),
    Column("schema_hash", String, nullable=False),
)
datasets = Table(
    "datasets",
    metadata,
    pk(),
    Column("payload_json", Text, nullable=False),
    Column("synthetic", Integer, nullable=False, server_default="1"),
    CheckConstraint("synthetic=1"),
)
source_records = Table(
    "source_records",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    Column("table_name", String, nullable=False),
    Column("payload_sha256", String, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("synthetic", Integer, nullable=False),
    CheckConstraint("synthetic=1"),
    CheckConstraint("json_valid(payload_json)"),
)

customers = Table(
    "customers",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("dataset_id", "datasets.id"),
    Column("display_name", String, nullable=False),
)
accounts = Table(
    "accounts",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("dataset_id", "datasets.id"),
    fk("customer_id", "customers.id"),
    Column("contract_reference", String, nullable=False),
    Column("currency", String, nullable=False),
    CheckConstraint("currency='EUR'"),
    UniqueConstraint("dataset_id", "contract_reference"),
)
invoices = Table(
    "invoices",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("dataset_id", "datasets.id"),
    fk("account_id", "accounts.id"),
    Column("reference", String, nullable=False),
    Column("issued_on", String, nullable=False),
    Column("due_on", String, nullable=False),
    Column("currency", String, nullable=False, server_default="EUR"),
    CheckConstraint("currency='EUR'"),
    *money(),
    CheckConstraint("due_on >= issued_on"),
    UniqueConstraint("dataset_id", "reference"),
)
invoice_items = Table(
    "invoice_items",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("invoice_id", "invoices.id"),
    Column("line_number", Integer, nullable=False),
    Column("net_cents", Integer, nullable=False),
    Column("tax_cents", Integer, nullable=False),
    Column("gross_cents", Integer, nullable=False),
    CheckConstraint("net_cents+tax_cents=gross_cents"),
    CheckConstraint(
        "net_cents BETWEEN -9000000000000000 AND 9000000000000000 "
        "AND tax_cents BETWEEN -9000000000000000 AND 9000000000000000 "
        "AND gross_cents BETWEEN -9000000000000000 AND 9000000000000000"
    ),
    CheckConstraint(
        "typeof(net_cents)='integer' AND typeof(tax_cents)='integer' "
        "AND typeof(gross_cents)='integer'"
    ),
    CheckConstraint("line_number > 0"),
    UniqueConstraint("invoice_id", "line_number"),
)
bank_statements = Table(
    "bank_statements",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("dataset_id", "datasets.id"),
    Column("source_system", String, nullable=False),
    Column("file_sha256", String, nullable=False),
    Column("imported_at", String, nullable=False),
    UniqueConstraint("dataset_id", "source_system", "file_sha256"),
)
bank_events = Table(
    "bank_events",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("dataset_id", "datasets.id"),
    Column("source_system", String, nullable=False),
    Column("bank_event_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("booked_on", String, nullable=False),
    Column("currency", String, nullable=False),
    *money(),
    CheckConstraint("kind IN ('payment','refund','chargeback')"),
    CheckConstraint("currency='EUR'"),
    UniqueConstraint("dataset_id", "source_system", "bank_event_id"),
)
payments = Table(
    "payments",
    metadata,
    fk("id", "bank_events.id", primary_key=True),
    fk("account_id", "accounts.id", nullable=True),
    Column("reference", String),
)
reversals = Table(
    "reversals",
    metadata,
    fk("id", "bank_events.id", primary_key=True),
    fk("payment_id", "payments.id"),
    Column("reason", String, nullable=False),
)
source_runs = Table(
    "source_authoring_runs", metadata, fk("id", "source_records.id", primary_key=True)
)
source_cases = Table(
    "source_approval_cases",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("run_id", "source_authoring_runs.id"),
    fk("invoice_id", "invoices.id", nullable=True),
)
source_decisions = Table(
    "source_approval_decisions",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("case_id", "source_approval_cases.id"),
)
corrections = Table(
    "source_corrections",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("invoice_id", "invoices.id"),
    fk("decision_id", "source_approval_decisions.id"),
    *money(positive=False),
    Column("effective_on", String, nullable=False),
    fk("reverses_correction_id", "source_corrections.id", nullable=True),
    UniqueConstraint("reverses_correction_id"),
)
import_rows = Table(
    "source_import_rows",
    metadata,
    fk("id", "source_records.id", primary_key=True),
    fk("import_id", "bank_statements.id"),
    fk("record_id", "bank_events.id"),
    Column("row_number", Integer, nullable=False),
    CheckConstraint("row_number>0"),
    UniqueConstraint("import_id", "row_number"),
)

source_files = Table(
    "source_files",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    Column("path", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("content", LargeBinary, nullable=False),
    UniqueConstraint("dataset_id", "path", "sha256"),
)
source_versions = Table(
    "source_versions",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    Column("manifest_sha256", String, nullable=False),
    Column("metadata_json", Text, nullable=False),
)
version_records = Table(
    "version_records",
    metadata,
    fk("version_id", "source_versions.id", primary_key=True),
    fk("record_id", "source_records.id", primary_key=True),
    Column("table_name", String, nullable=False),
    Column("ordinal", Integer, nullable=False),
    UniqueConstraint("version_id", "table_name", "ordinal"),
)
version_files = Table(
    "version_files",
    metadata,
    fk("version_id", "source_versions.id", primary_key=True),
    fk("file_id", "source_files.id", primary_key=True),
)
provenance = Table(
    "source_occurrences",
    metadata,
    pk(),
    fk("version_id", "source_versions.id"),
    fk("record_id", "source_records.id"),
    Column("ordinal", Integer, nullable=False),
    Column("payload_json", Text, nullable=False),
    UniqueConstraint("version_id", "ordinal"),
)
source_heads = Table(
    "source_heads",
    metadata,
    fk("dataset_id", "datasets.id", primary_key=True),
    fk("version_id", "source_versions.id"),
)
import_batches = Table(
    "import_batches",
    metadata,
    pk(),
    fk("version_id", "source_versions.id"),
    Column("occurred_at", String, nullable=False),
    Column("outcome", String, nullable=False),
    Column("actor", String, nullable=False),
    CheckConstraint("outcome IN ('IMPORTED','DUPLICATE')"),
)

rule_versions = Table("rule_versions", metadata, pk(), Column("description", Text, nullable=False))
runs = Table(
    "reconciliation_runs",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    fk("source_version_id", "source_versions.id"),
    fk("rule_version", "rule_versions.id"),
    fk("base_run_id", "reconciliation_runs.id", nullable=True),
    Column("kind", String, nullable=False),
    Column("as_of", String, nullable=False),
    Column("known_at", String, nullable=False),
    Column("input_sha256", String, nullable=False),
    Column("result_sha256", String, nullable=False),
    Column("result_json", Text, nullable=False),
    Column("controls_json", Text, nullable=False),
    Column("status", String, nullable=False),
    CheckConstraint("kind IN ('ENGINE','LEDGER')"),
    CheckConstraint("status='completed'"),
    CheckConstraint("json_valid(result_json)"),
)
ledger_heads = Table(
    "ledger_heads",
    metadata,
    fk("dataset_id", "datasets.id", primary_key=True),
    fk("run_id", "reconciliation_runs.id"),
    Column("revision", Integer, nullable=False),
    CheckConstraint("revision>=1"),
)
review_cases = Table(
    "review_cases",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    fk("payment_id", "payments.id"),
    fk("origin_run_id", "reconciliation_runs.id"),
    Column("reason_code", String, nullable=False),
    Column("status", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("opened_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    CheckConstraint("version>=1"),
    CheckConstraint("status IN ('OPEN','IN_REVIEW','RESOLVED','REOPENED')"),
    UniqueConstraint("dataset_id", "payment_id", "reason_code"),
)
case_evidence = Table(
    "case_evidence",
    metadata,
    fk("case_id", "review_cases.id", primary_key=True),
    fk("run_id", "reconciliation_runs.id", primary_key=True),
    Column("payload_json", Text, nullable=False),
)
decisions = Table(
    "manual_decisions",
    metadata,
    pk(),
    fk("dataset_id", "datasets.id"),
    fk("case_id", "review_cases.id", nullable=True),
    fk("base_run_id", "reconciliation_runs.id"),
    Column("sequence", Integer, nullable=False),
    Column("action", String, nullable=False),
    Column("effective_on", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("note", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    fk("reverses_decision_id", "manual_decisions.id", nullable=True),
    UniqueConstraint("dataset_id", "sequence"),
    UniqueConstraint("reverses_decision_id"),
    CheckConstraint("action IN ('allocate','reverse','correction','refund','chargeback','defer')"),
)
allocations = Table(
    "allocations",
    metadata,
    pk(),
    fk("run_id", "reconciliation_runs.id"),
    fk("payment_id", "payments.id"),
    fk("invoice_id", "invoices.id"),
    fk("decision_id", "manual_decisions.id", nullable=True),
    *money(),
    Column("payload_json", Text, nullable=False),
    UniqueConstraint("run_id", "payment_id", "invoice_id"),
)
allocation_releases = Table(
    "allocation_releases",
    metadata,
    pk(),
    fk("allocation_id", "allocations.id"),
    fk("decision_id", "manual_decisions.id", nullable=True),
    fk("reversal_id", "reversals.id", nullable=True),
    *money(),
    Column("payload_json", Text, nullable=False),
    CheckConstraint("(decision_id IS NULL) != (reversal_id IS NULL)"),
    UniqueConstraint("allocation_id", "decision_id"),
    UniqueConstraint("allocation_id", "reversal_id"),
)
run_allocations = Table(
    "run_allocations",
    metadata,
    fk("run_id", "reconciliation_runs.id", primary_key=True),
    fk("allocation_id", "allocations.id", primary_key=True),
)
run_releases = Table(
    "run_releases",
    metadata,
    fk("run_id", "reconciliation_runs.id", primary_key=True),
    fk("release_id", "allocation_releases.id", primary_key=True),
)
adjustments = Table(
    "adjustments",
    metadata,
    pk(),
    fk("decision_id", "manual_decisions.id"),
    fk("invoice_id", "invoices.id", nullable=True),
    fk("reversal_id", "reversals.id", nullable=True),
    Column("signed_cents", Integer, nullable=False),
    Column("payload_json", Text, nullable=False),
    CheckConstraint("typeof(signed_cents)='integer' AND signed_cents!=0"),
)
run_effects = Table(
    "run_adjustment_effects",
    metadata,
    fk("run_id", "reconciliation_runs.id", primary_key=True),
    Column("effect_id", String, primary_key=True),
    Column("source_record_id", String, nullable=False),
    Column("payload_json", Text, nullable=False),
)
audit_events = Table(
    "audit_events",
    metadata,
    pk(),
    Column("occurred_at", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("entity_type", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("reason", Text, nullable=False),
    Column("details_json", Text, nullable=False),
    fk("dataset_id", "datasets.id", nullable=True),
    fk("run_id", "reconciliation_runs.id", nullable=True),
    fk("payment_id", "payments.id", nullable=True),
    fk("invoice_id", "invoices.id", nullable=True),
    fk("account_id", "accounts.id", nullable=True),
    Column("synthetic", Integer, nullable=False, server_default="1"),
    CheckConstraint("synthetic=1"),
)
Index("ix_audit_action_time", audit_events.c.action, audit_events.c.occurred_at)
Index("ix_review_status_reason", review_cases.c.status, review_cases.c.reason_code)
Index("ix_runs_cutoff", runs.c.dataset_id, runs.c.as_of, runs.c.known_at)

MUTABLE = {"ledger_heads", "source_heads", "review_cases"}
IMMUTABLE = set(metadata.tables) - MUTABLE
