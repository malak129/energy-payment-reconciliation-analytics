"""Deterministic CSV export and synthetic statement receipt fixtures; no ingestion service."""

import csv
import hashlib
import io
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from energy_reconciliation.data_generation.generator import (
    SOURCE_SYSTEM,
    SyntheticDataset,
    canonical,
    digest,
    timestamp,
)
from energy_reconciliation.data_generation.settings import month_end
from energy_reconciliation.data_generation.validation import require, validate_dataset
from energy_reconciliation.models import records as models

TABLE_MODELS = {
    "customers": models.Customer,
    "accounts": models.Account,
    "invoices": models.Invoice,
    "invoice_items": models.InvoiceLine,
    "payments": models.Payment,
    "refunds_chargebacks": models.Reversal,
    "corrections": models.Correction,
    "review_cases": models.ReviewCase,
    "manual_decisions": models.ManualDecision,
    "authoring_runs": models.ReconciliationRun,
    "audit_events": models.AuditEvent,
}


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        converted = {}
        for name, value in row.items():
            if value is None:
                value = ""
            elif isinstance(value, bool):
                value = "true" if value else "false"
            elif isinstance(value, (list, dict, tuple)):
                value = canonical(value).decode("utf-8").strip()
            converted[name] = value
        writer.writerow(converted)
    return stream.getvalue().encode("utf-8")


def model_csv(rows: tuple | list, model: type[models.Record]) -> bytes:
    return csv_bytes([r.model_dump(mode="json") for r in rows], list(model.model_fields))


def build_export(data: SyntheticDataset) -> tuple[dict[str, bytes], dict]:
    summary = validate_dataset(data)
    files = {
        f"inputs/{name}.csv": model_csv(rows, TABLE_MODELS[name])
        for name, rows in data.business_tables().items()
    }
    groups = defaultdict(list)
    for event in sorted((*data.payments, *data.reversals), key=lambda e: (e.booked_on, e.id)):
        groups[event.booked_on.strftime("%Y-%m")].append(event)
    statements, import_rows, audits, receipts = [], [], [], []

    def fields(kind: str, key: object) -> dict:
        from uuid import uuid5

        from energy_reconciliation.data_generation.generator import NAMESPACE

        return {
            "id": f"syn_{kind}_" + uuid5(NAMESPACE, f"{data.manifest_record.id}:{kind}:{key}").hex,
            "synthetic": True,
        }

    duplicate_event_rows = 0
    for index, (month, events) in enumerate(sorted(groups.items())):
        filename = f"statement_{month}.csv"
        source_rows = [
            {
                "synthetic": True,
                "event_kind": "payment" if isinstance(e, models.Payment) else e.kind,
                "record_json": canonical(e.model_dump(mode="json")).decode("utf-8").strip(),
            }
            for e in events
        ]
        raw = csv_bytes(source_rows, ["synthetic", "event_kind", "record_json"])
        checksum = hashlib.sha256(raw).hexdigest()
        imported_at = timestamp(month_end(events[-1].booked_on))
        statement = models.BankStatementImport(
            **fields("statement", month),
            dataset_id=data.manifest_record.id,
            source_system=SOURCE_SYSTEM,
            file_sha256=checksum,
            filename=filename,
            imported_at=imported_at,
            row_count=len(events),
        )
        statements.append(statement)
        path = "statement_fixtures/" + filename
        files[path] = raw
        receipts.append(
            {
                "synthetic": True,
                "path": path,
                "import_id": statement.id,
                "expected_outcome": "accepted",
                "file_sha256": checksum,
            }
        )
        for number, event in enumerate(events, 1):
            import_rows.append(
                models.ImportRow(
                    **fields("importrow", f"{month}_{number}"),
                    import_id=statement.id,
                    row_number=number,
                    payload_sha256=digest(event.model_dump(mode="json")),
                    outcome="accepted",
                    record_id=event.id,
                    reason="Synthetic accepted-row provenance fixture",
                )
            )
        if index % 3 == 0:
            copy_path = f"statement_fixtures/statement_{month}_duplicate.csv"
            files[copy_path] = raw
            duplicate_event_rows += len(events)
            audit = models.AuditEvent(
                **fields("receipt", month),
                entity_type="BankStatementImport",
                entity_id=statement.id,
                action="synthetic_duplicate_receipt_fixture",
                actor="SYNTHETIC_GENERATOR",
                occurred_at=imported_at,
                payload_sha256=checksum,
            )
            audits.append(audit)
            receipts.append(
                {
                    "synthetic": True,
                    "path": copy_path,
                    "import_id": statement.id,
                    "expected_outcome": "duplicate",
                    "file_sha256": checksum,
                    "audit_event_id": audit.id,
                }
            )
    require(len({s.file_sha256 for s in statements}) == len(statements), "duplicate canonical file")
    require(len({r.id for r in import_rows}) == len(import_rows), "duplicate import-row ID")
    require(
        sum(s.row_count for s in statements) == len(data.payments) + len(data.reversals),
        "statement events do not cover canonical events",
    )
    files["inputs/bank_statements.csv"] = model_csv(statements, models.BankStatementImport)
    files["inputs/import_rows.csv"] = model_csv(import_rows, models.ImportRow)
    files["inputs/statement_audit_events.csv"] = model_csv(audits, models.AuditEvent)
    files["evaluation/ground_truth.json"] = canonical(data.ground_truth.model_dump(mode="json"))
    summary["counts"] |= {
        "bank_statements": len(statements),
        "import_rows": len(import_rows),
        "statement_audit_events": len(audits),
        "statement_receipts": len(receipts),
        "duplicate_statement_receipts": len(audits),
        "duplicate_event_representations": duplicate_event_rows,
        "scenario_cases": len(data.ground_truth.cases),
        "expected_applications": len(data.ground_truth.expected_applications),
        "expected_releases": len(data.ground_truth.expected_releases),
        "expected_exceptions_as_of": len(data.ground_truth.expected_exceptions),
    }
    manifest = {
        "synthetic": True,
        "purpose": "synthetic_generation_only",
        "generator_version": "1",
        "dataset": data.manifest_record.model_dump(mode="json"),
        "configuration": data.settings.semantic_config(),
        "input_files": sorted(p for p in files if p.startswith("inputs/")),
        "evaluation_files": ["evaluation/ground_truth.json"],
        "statement_receipts": receipts,
        "file_sha256": {p: hashlib.sha256(raw).hexdigest() for p, raw in sorted(files.items())},
        "summary": summary,
        "discrepancy_rate_denominator": (
            "scenario cases (one or two consecutive invoices per account)"
        ),
        "unavailable_scenarios": ["combined", "ambiguous"]
        if data.settings.billing_periods == 1
        else [],
        "warning": "Ground truth is evaluation-only. No reconciliation engine has been run.",
    }
    files["manifest.json"] = canonical(manifest)
    return files, manifest


def export_dataset(data: SyntheticDataset, output_dir: Path | None = None) -> dict:
    """Stage a new directory atomically. Identical reruns are no-ops; never overwrite other data."""
    files, manifest = build_export(data)
    target = (output_dir or data.settings.output_dir).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        existing = (
            {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
            if target.is_dir()
            else {}
        )
        if set(existing) == set(files) and all(
            existing[p].read_bytes() == raw for p, raw in files.items()
        ):
            return manifest
        raise ValueError(
            "Output is not an identical generated dataset; choose a new output directory"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".synthetic-stage-", dir=target.parent) as temporary:
        stage = Path(temporary) / "dataset"
        stage.mkdir()
        for name, raw in files.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        if target.exists():
            target.rmdir()  # Empty directory only, verified above; never recursive removal.
        os.replace(stage, target)
    return manifest
