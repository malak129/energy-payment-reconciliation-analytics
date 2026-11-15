"""Strict Phase 2 source adapter. Never opens evaluation files or uses oracle summaries."""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Literal

from energy_reconciliation.models import records as m
from energy_reconciliation.utilities.serialization import fingerprint

TABLES = {
    "customers": m.Customer,
    "accounts": m.Account,
    "invoices": m.Invoice,
    "invoice_items": m.InvoiceLine,
    "payments": m.Payment,
    "refunds_chargebacks": m.Reversal,
    "corrections": m.Correction,
    "review_cases": m.ReviewCase,
    "manual_decisions": m.ManualDecision,
    "authoring_runs": m.ReconciliationRun,
    "audit_events": m.AuditEvent,
    "bank_statements": m.BankStatementImport,
    "import_rows": m.ImportRow,
    "statement_audit_events": m.AuditEvent,
}


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)


@dataclass(frozen=True)
class SourceOccurrence:
    path: str
    row_number: int
    record_id: str
    record_type: str
    payload_sha256: str
    original_values: tuple[tuple[str, str], ...]
    duplicate_bank_event: bool = False
    synthetic: Literal[True] = True


@dataclass(frozen=True)
class InputDataset:
    dataset: m.Dataset
    tables: dict[str, tuple]
    bank_known_at: dict[str, datetime]
    source_manifest_sha256: str
    source_hashes: dict[str, str]
    provenance: tuple[SourceOccurrence, ...] = ()
    duplicate_file_receipts: int = 0
    duplicate_event_representations: int = 0

    def rows(self, name: str) -> tuple:
        return self.tables.get(name, ())


def decode_row(row: dict[str, str], model: type[m.Record], location: str) -> m.Record:
    ensure(
        None not in row and all(v is not None for v in row.values()),
        f"{location}: wrong number of CSV fields",
    )
    values = {}
    for key, value in row.items():
        if key not in model.model_fields:
            raise ValueError(f"{location}: unexpected field {key}")
        if value == "":
            values[key] = None
        elif key == "synthetic":
            ensure(value == "true", f"{location}: synthetic must be true")
            values[key] = True
        elif key.endswith("_cents") or key in ("row_number", "row_count", "line_number", "seed"):
            ensure(
                re.fullmatch(r"-?[0-9]+", value) is not None,
                f"{location}: {key} must contain integer cents/counts",
            )
            values[key] = int(value)
        elif key == "candidate_invoice_ids":
            values[key] = json.loads(value)
        else:
            if key.endswith("_on") or key in ("service_start", "service_end", "as_of"):
                ensure(
                    re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
                    f"{location}: {key} must be an ISO date",
                )
            values[key] = value
    try:
        return model.model_validate(values)
    except ValueError as exc:
        raise ValueError(f"{location}: {exc}") from exc


def _csv(raw: bytes, location: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    ensure(
        reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)),
        f"{location}: missing/duplicate column headers",
    )
    return list(reader)


def load_dataset(root: Path) -> InputDataset:
    try:
        return _load_dataset(root)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(f"Malformed dataset manifest/provenance: {exc}") from exc


def _load_dataset(root: Path) -> InputDataset:
    root = root.resolve()
    manifest_bytes = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    ensure(manifest.get("synthetic") is True, "Manifest must be explicitly synthetic")
    dataset = m.Dataset.model_validate(manifest["dataset"])
    expected = {f"inputs/{name}.csv" for name in TABLES}
    ensure(
        set(manifest["input_files"]) == expected and len(manifest["input_files"]) == len(expected),
        "Manifest must list exactly the supported canonical CSV tables",
    )
    hashes, provenance, tables, events, known = {}, [], {}, {}, {}
    duplicate_events = 0

    def read(name: str) -> bytes:
        path = (root / name).resolve()
        ensure(
            not Path(name).is_absolute() and path.is_relative_to(root),
            "Source path escapes dataset",
        )
        ensure(name == path.relative_to(root).as_posix(), "Source path must be canonical")
        ensure(name.startswith(("inputs/", "statement_fixtures/")), "Unsupported source path")
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        ensure(checksum == manifest["file_sha256"].get(name), f"{name}: SHA-256 mismatch")
        hashes[name] = checksum
        return raw

    def register(record: m.Record, path: str, number: int, original: dict) -> bool:
        nonlocal duplicate_events
        duplicate = False
        if isinstance(record, (m.Payment, m.Reversal)):
            key = (record.dataset_id, record.source_system, record.bank_event_id)
            if key in events:
                ensure(
                    events[key] == record, f"{path}:{number}: conflicting bank event identity {key}"
                )
                duplicate = True
                duplicate_events += 1
            else:
                events[key] = record
        provenance.append(
            SourceOccurrence(
                path,
                number,
                record.id,
                type(record).__name__,
                fingerprint(record.model_dump(mode="json")),
                tuple(original.items()),
                duplicate,
            )
        )
        return duplicate

    for name, model in TABLES.items():
        path = f"inputs/{name}.csv"
        rows = []
        for number, row in enumerate(_csv(read(path), path), 2):
            record = decode_row(row, model, f"{path}:{number}")
            if not register(record, path, number, row):
                rows.append(record)
        tables[name] = tuple(rows)
    statements = {s.id: s for s in tables["bank_statements"]}
    canonical_events = {e.id: e for e in events.values()}
    seen_files, canonical_rows = set(), {}
    duplicate_files = 0
    for receipt in manifest["statement_receipts"]:
        ensure(
            receipt.get("synthetic") is True and receipt["import_id"] in statements,
            "Invalid statement receipt definition",
        )
        statement = statements[receipt["import_id"]]
        path = receipt["path"]
        raw = read(path)
        ensure(
            hashes[path] == statement.file_sha256 == receipt["file_sha256"],
            f"{path}: receipt/statement hash mismatch",
        )
        identity = (dataset.id, statement.source_system, statement.file_sha256)
        duplicate_file = identity in seen_files
        duplicate_files += duplicate_file
        seen_files.add(identity)
        source_rows = _csv(raw, path)
        ensure(len(source_rows) == statement.row_count, f"{path}: statement row count mismatch")
        row_records = []
        for number, row in enumerate(source_rows, 2):
            ensure(
                set(row) == {"synthetic", "event_kind", "record_json"}
                and row["synthetic"] == "true",
                f"{path}:{number}: invalid raw statement schema",
            )
            model = m.Payment if row["event_kind"] == "payment" else m.Reversal
            try:
                record = model.model_validate_json(row["record_json"])
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            ensure(
                isinstance(record, m.Payment) or record.kind == row["event_kind"],
                f"{path}:{number}: bank event kind mismatch",
            )
            ensure(
                canonical_events.get(record.id) == record, f"{path}:{number}: not a canonical event"
            )
            ensure(
                record.source_system == statement.source_system, "Statement source-system mismatch"
            )
            ensure(
                statement.imported_at.date() >= record.booked_on,
                "Statement receipt before bank booking",
            )
            register(record, path, number, row)
            known[record.id] = min(
                known.get(record.id, statement.imported_at), statement.imported_at
            )
            row_records.append(record)
        if not duplicate_file:
            canonical_rows[statement.id] = row_records
    ensure(set(canonical_rows) == set(statements), "Statement definitions lack source receipts")
    ensure(set(known) == set(canonical_events), "Canonical cash events lack statement provenance")
    ensure(
        len([e.id for rows in canonical_rows.values() for e in rows]) == len(canonical_events),
        "An event must occur once across canonical statements",
    )
    row_keys = set()
    for row in tables["import_rows"]:
        key = (row.import_id, row.row_number)
        ensure(key not in row_keys, "Duplicate import-row provenance")
        row_keys.add(key)
        ensure(
            row.import_id in canonical_rows
            and 1 <= row.row_number <= len(canonical_rows[row.import_id]),
            "Orphan or invalid import row",
        )
        event = canonical_rows[row.import_id][row.row_number - 1]
        ensure(
            row.outcome == "accepted"
            and row.record_id == event.id
            and row.payload_sha256 == fingerprint(event.model_dump(mode="json")),
            "Import-row event/payload mismatch",
        )
    ensure(len(row_keys) == len(canonical_events), "Incomplete accepted import-row provenance")
    core = {
        name: [r.model_dump(mode="json") for r in rows]
        for name, rows in tables.items()
        if name not in ("bank_statements", "import_rows", "statement_audit_events")
    }
    ensure(fingerprint(core) == dataset.content_sha256, "Core dataset content fingerprint mismatch")
    result = InputDataset(
        dataset,
        tables,
        known,
        hashlib.sha256(manifest_bytes).hexdigest(),
        hashes,
        tuple(provenance),
        duplicate_files,
        duplicate_events,
    )
    validate_input(result)
    return result


def validate_input(data: InputDataset) -> None:
    """Cross-record invariants, independent of generation code and ground truth."""
    m.Dataset.model_validate(data.dataset.model_dump())
    rows = [r for records in data.tables.values() for r in records]
    ensure(len({r.id for r in rows}) == len(rows), "Duplicate record ID")
    for record in rows:
        type(record).model_validate(record.model_dump())
        if hasattr(record, "dataset_id"):
            ensure(record.dataset_id == data.dataset.id, "Cross-dataset record")
    maps = {name: {r.id: r for r in records} for name, records in data.tables.items()}
    customers, accounts, invoices = (maps.get(k, {}) for k in ("customers", "accounts", "invoices"))
    payments = maps.get("payments", {})
    ensure(
        len({i.reference.strip().upper() for i in invoices.values()}) == len(invoices),
        "Duplicate normalized invoice reference",
    )
    ensure(
        len({a.contract_reference for a in accounts.values()}) == len(accounts),
        "Duplicate contract",
    )
    for records in data.tables.values():
        keys = [r.source_record_id for r in records if hasattr(r, "source_record_id")]
        ensure(len(keys) == len(set(keys)), "Duplicate source record identity")
    for account in accounts.values():
        ensure(account.customer_id in customers, "Orphan account")
    line_keys, line_sums = set(), dict.fromkeys(invoices, 0)
    for line in data.rows("invoice_items"):
        ensure(
            line.invoice_id in invoices and (line.invoice_id, line.line_number) not in line_keys,
            "Orphan/duplicate invoice line",
        )
        line_keys.add((line.invoice_id, line.line_number))
        line_sums[line.invoice_id] += line.gross_cents
    for invoice in invoices.values():
        ensure(
            invoice.account_id in accounts
            and invoice.issued_on >= accounts[invoice.account_id].opened_on,
            "Orphan invoice or issue before contract",
        )
        ensure(line_sums[invoice.id] == invoice.amount_cents, "Invoice item total mismatch")
        account = accounts[invoice.account_id]
        ensure(
            account.closed_on is None or invoice.issued_on <= account.closed_on,
            "Invoice issued after contract closed",
        )
    event_keys, outflows = set(), dict.fromkeys(payments, 0)
    for event in (*data.rows("payments"), *data.rows("refunds_chargebacks")):
        key = (event.source_system, event.bank_event_id)
        ensure(key not in event_keys, "Duplicate bank event identity")
        event_keys.add(key)
        ensure(
            event.id in data.bank_known_at and data.bank_known_at[event.id].tzinfo is not None,
            "Missing/naive bank availability timestamp",
        )
        ensure(
            data.bank_known_at[event.id].date() >= event.booked_on,
            "Bank event known before its booking date",
        )
        if isinstance(event, m.Payment):
            ensure(
                event.account_id is None or event.account_id in accounts, "Orphan payment account"
            )
        else:
            ensure(event.payment_id in payments, "Orphan reversal")
            ensure(
                event.booked_on >= payments[event.payment_id].booked_on, "Reversal before payment"
            )
            outflows[event.payment_id] += event.amount_cents
            ensure(
                outflows[event.payment_id] <= payments[event.payment_id].amount_cents,
                "Reversals exceed original cash",
            )
    decisions, cases, runs = (
        maps.get(k, {}) for k in ("manual_decisions", "review_cases", "authoring_runs")
    )
    corrections = maps.get("corrections", {})
    reversed_ids, correction_decisions = set(), set()
    for correction in corrections.values():
        ensure(
            correction.invoice_id in invoices and correction.decision_id in decisions,
            "Orphan correction/decision",
        )
        invoice, decision = invoices[correction.invoice_id], decisions[correction.decision_id]
        ensure(decision.id not in correction_decisions, "Correction approval decision reused")
        correction_decisions.add(decision.id)
        ensure(decision.case_id in cases, "Orphan correction approval case")
        case = cases[decision.case_id]
        ensure(
            case.invoice_id == invoice.id
            and case.run_id in runs
            and runs[case.run_id].status == "completed"
            and decision.action == "correct_invoice"
            and decision.resolved_account_id in (None, invoice.account_id),
            "Invalid correction authority",
        )
        ensure(
            correction.effective_on >= invoice.issued_on
            and case.created_at <= decision.created_at <= correction.created_at,
            "Invalid correction effective/approval date",
        )
        ensure(
            decision.supersedes_decision_id is None,
            "Superseded decisions require Phase 4 resolution",
        )
        if correction.reverses_correction_id is not None:
            original = corrections.get(correction.reverses_correction_id)
            ensure(
                original is not None
                and original.id != correction.id
                and original.reverses_correction_id is None
                and original.id not in reversed_ids
                and original.invoice_id == correction.invoice_id
                and original.amount_cents == -correction.amount_cents
                and original.effective_on <= correction.effective_on
                and original.created_at <= correction.created_at,
                "Invalid correction undo (must be single equal opposite entry)",
            )
            reversed_ids.add(original.id)
    for case in cases.values():
        ensure(
            case.run_id in runs and (case.invoice_id in invoices or case.payment_id in payments),
            "Orphan review case",
        )
        ensure(set(case.candidate_invoice_ids) <= invoices.keys(), "Orphan review candidate")
    for decision in decisions.values():
        ensure(decision.case_id in cases, "Orphan decision")
        ensure(
            decision.resolved_account_id is None or decision.resolved_account_id in accounts,
            "Orphan resolved account",
        )
        ensure(
            decision.action == "correct_invoice",
            "Phase 3 accepts correction approvals only; manual payment resolution is Phase 4",
        )
    record_map = {r.id: r for r in rows}
    for audit in (*data.rows("audit_events"), *data.rows("statement_audit_events")):
        ensure(
            audit.entity_id in record_map and (audit.run_id is None or audit.run_id in runs),
            "Orphan audit event",
        )
        target = record_map[audit.entity_id]
        ensure(audit.entity_type == type(target).__name__, "Audit target type mismatch")
        if isinstance(target, m.Correction):
            ensure(
                audit.payload_sha256 == fingerprint(target.model_dump(mode="json")),
                "Correction approval audit hash mismatch",
            )
        elif isinstance(target, m.BankStatementImport):
            ensure(audit.payload_sha256 == target.file_sha256, "Statement audit hash mismatch")
