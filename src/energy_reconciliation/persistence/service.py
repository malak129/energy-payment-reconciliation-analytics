"""Transactional import, immutable runs, optimistic review workflow and financial operations."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, literal_column, select, update

from energy_reconciliation.ingestion.csv_dataset import (
    TABLES,
    InputDataset,
    SourceOccurrence,
    ensure,
    load_dataset,
    validate_input,
)
from energy_reconciliation.models import records as m
from energy_reconciliation.persistence import schema as s
from energy_reconciliation.persistence.overlay import Operation, Target, replay
from energy_reconciliation.reconciliation.engine import default_options, reconcile
from energy_reconciliation.reconciliation.results import ReconciliationResult, RunOptions
from energy_reconciliation.utilities.serialization import canonical, fingerprint, stable_id


class StaleUpdate(ValueError):
    pass


def text_json(value):
    return canonical(value).decode("utf-8")


def identity(kind):
    return f"syn_{kind}_{uuid4().hex}"


def actor_reason(actor, reason):
    ensure(
        isinstance(actor, str)
        and actor.startswith("SYNTHETIC_DEMO:")
        and 0 < len(actor.removeprefix("SYNTHETIC_DEMO:").strip()) <= 100,
        "Actor must be explicit, e.g. SYNTHETIC_DEMO:student (not authentication)",
    )
    ensure(
        isinstance(reason, str) and 0 < len(reason.strip()) <= 1000, "A nonempty reason is required"
    )


def put(connection, table, rows):
    """Insert immutable rows in batches; equality is the only allowed upsert."""
    if not rows:
        return set()
    keyed = {row["id"]: row for row in rows}
    ensure(len(keyed) == len(rows), f"Duplicate {table.name} IDs in operation")
    existing = {}
    keys = list(keyed)
    for start in range(0, len(keys), 800):
        existing.update(
            {
                r["id"]: r
                for r in connection.execute(
                    select(table).where(table.c.id.in_(keys[start : start + 800]))
                ).mappings()
            }
        )
    fresh = []
    for key, row in keyed.items():
        if key in existing:
            ensure(
                all(existing[key][name] == value for name, value in row.items()),
                f"Conflicting immutable {table.name} record {key}",
            )
        else:
            fresh.append(row)
    for start in range(0, len(fresh), 800):
        connection.execute(table.insert(), fresh[start : start + 800])
    return {r["id"] for r in fresh}


class Store:
    def __init__(self, database):
        self.db = database
        self.db.initialize()

    def now(self):
        value = self.db.clock()
        ensure(value.tzinfo is not None, "Application clock must be timezone aware")
        return value.astimezone(UTC)

    def audit(
        self, connection, actor, action, entity_type, entity_id, reason, details=None, **refs
    ):
        row = dict(
            id=identity("audit"),
            occurred_at=self.now().isoformat(),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
            details_json=text_json(details or {}),
            synthetic=1,
            **{
                k: refs.get(k)
                for k in ("dataset_id", "run_id", "payment_id", "invoice_id", "account_id")
            },
        )
        connection.execute(s.audit_events.insert().values(**row))

    def rejected(self, actor, action, error, details=None):
        with self.db.transaction() as connection:
            details = details or {}
            refs = {}
            if details.get("case_id"):
                case = (
                    connection.execute(
                        select(s.review_cases).where(s.review_cases.c.id == details["case_id"])
                    )
                    .mappings()
                    .first()
                )
                if case:
                    refs.update(dataset_id=case["dataset_id"], payment_id=case["payment_id"])
            for key, table in (
                ("payment_id", s.payments),
                ("invoice_id", s.invoices),
                ("dataset_id", s.datasets),
            ):
                if (
                    isinstance(details.get(key), str)
                    and connection.execute(
                        select(table.c.id).where(table.c.id == details[key])
                    ).first()
                ):
                    refs[key] = details[key]
            self.audit(
                connection,
                actor if isinstance(actor, str) and actor else "SYNTHETIC_DEMO:unattributed",
                action + "_REJECTED",
                "operation",
                identity("rejected"),
                str(error),
                details,
                **refs,
            )

    def import_directory(self, root: Path, actor: str, reason: str):
        try:
            actor_reason(actor, reason)
            data = load_dataset(root)
            files = {name: (root / name).read_bytes() for name in data.source_hashes}
            files["manifest.json"] = (root / "manifest.json").read_bytes()
            ensure(
                all(
                    hashlib.sha256(raw).hexdigest()
                    == (
                        data.source_manifest_sha256
                        if name == "manifest.json"
                        else data.source_hashes[name]
                    )
                    for name, raw in files.items()
                ),
                "Source changed during import; retry",
            )
            return self.import_input(data, actor, reason, files)
        except Exception as exc:
            self.rejected(actor, "IMPORT", exc, {"source_directory": str(root)})
            raise

    def import_input(self, data: InputDataset, actor: str, reason: str, files=None):
        actor_reason(actor, reason)
        validate_input(data)
        version_id = stable_id(
            "sourceversion",
            [
                data.dataset.id,
                data.source_manifest_sha256,
                data.source_hashes,
                {
                    name: [r.model_dump(mode="json") for r in rows]
                    for name, rows in data.tables.items()
                },
            ],
        )
        with self.db.transaction() as connection:
            put(
                connection,
                s.datasets,
                [
                    {
                        "id": data.dataset.id,
                        "synthetic": 1,
                        "payload_json": text_json(
                            data.dataset.model_dump(
                                mode="json", exclude={"content_sha256", "effective_at"}
                            )
                        ),
                    }
                ],
            )
            duplicate = (
                connection.execute(
                    select(s.source_versions.c.id).where(s.source_versions.c.id == version_id)
                ).first()
                is not None
            )
            if not duplicate:
                old_head = connection.execute(
                    select(s.source_heads.c.version_id).where(
                        s.source_heads.c.dataset_id == data.dataset.id
                    )
                ).scalar_one_or_none()
                if old_head:
                    protected = set(
                        connection.execute(
                            select(s.version_records.c.record_id).where(
                                s.version_records.c.version_id == old_head,
                                s.version_records.c.table_name.not_in(
                                    ("bank_statements", "import_rows", "statement_audit_events")
                                ),
                            )
                        ).scalars()
                    )
                    incoming = {
                        r.id
                        for name, rows in data.tables.items()
                        if name not in ("bank_statements", "import_rows", "statement_audit_events")
                        for r in rows
                    }
                    ensure(
                        protected <= incoming,
                        "Complete source revision cannot omit previously accepted records",
                    )
                    oldmeta = json.loads(
                        connection.execute(
                            select(s.source_versions.c.metadata_json).where(
                                s.source_versions.c.id == old_head
                            )
                        ).scalar_one()
                    )
                    from dataclasses import replace

                    data = replace(
                        data,
                        bank_known_at={
                            key: min(
                                value,
                                datetime.fromisoformat(
                                    oldmeta["bank_known_at"].get(key, value.isoformat())
                                ),
                            )
                            for key, value in data.bank_known_at.items()
                        },
                    )
                source_rows = [
                    {
                        "id": r.id,
                        "dataset_id": data.dataset.id,
                        "table_name": name,
                        "payload_sha256": fingerprint(r.model_dump(mode="json")),
                        "payload_json": text_json(r.model_dump(mode="json")),
                        "synthetic": 1,
                    }
                    for name, rows in data.tables.items()
                    for r in rows
                ]
                put(connection, s.source_records, source_rows)
                self._import_typed(connection, data)
                metadata = {
                    "dataset": data.dataset.model_dump(mode="json"),
                    "bank_known_at": {k: v.isoformat() for k, v in data.bank_known_at.items()},
                    "source_manifest_sha256": data.source_manifest_sha256,
                    "source_hashes": data.source_hashes,
                    "duplicate_file_receipts": data.duplicate_file_receipts,
                    "duplicate_event_representations": data.duplicate_event_representations,
                }
                put(
                    connection,
                    s.source_versions,
                    [
                        {
                            "id": version_id,
                            "dataset_id": data.dataset.id,
                            "manifest_sha256": data.source_manifest_sha256,
                            "metadata_json": text_json(metadata),
                        }
                    ],
                )
                members = [
                    {
                        "version_id": version_id,
                        "record_id": r.id,
                        "table_name": name,
                        "ordinal": index,
                    }
                    for name, rows in data.tables.items()
                    for index, r in enumerate(rows)
                ]
                for start in range(0, len(members), 800):
                    connection.execute(s.version_records.insert(), members[start : start + 800])
                file_rows = [
                    {
                        "id": stable_id(
                            "file", [data.dataset.id, name, hashlib.sha256(raw).hexdigest()]
                        ),
                        "dataset_id": data.dataset.id,
                        "path": name,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "content": raw,
                    }
                    for name, raw in (files or {}).items()
                ]
                put(connection, s.source_files, file_rows)
                if file_rows:
                    connection.execute(
                        s.version_files.insert(),
                        [{"version_id": version_id, "file_id": r["id"]} for r in file_rows],
                    )
                put(
                    connection,
                    s.provenance,
                    [
                        {
                            "id": stable_id("occurrence", [version_id, index]),
                            "version_id": version_id,
                            "record_id": p.record_id,
                            "ordinal": index,
                            "payload_json": text_json(asdict(p)),
                        }
                        for index, p in enumerate(data.provenance)
                    ],
                )
                if connection.execute(
                    select(s.source_heads).where(s.source_heads.c.dataset_id == data.dataset.id)
                ).first():
                    connection.execute(
                        update(s.source_heads)
                        .where(s.source_heads.c.dataset_id == data.dataset.id)
                        .values(version_id=version_id)
                    )
                else:
                    connection.execute(
                        s.source_heads.insert().values(
                            dataset_id=data.dataset.id, version_id=version_id
                        )
                    )
            batch = identity("import")
            outcome = "DUPLICATE" if duplicate else "IMPORTED"
            connection.execute(
                s.import_batches.insert().values(
                    id=batch,
                    version_id=version_id,
                    occurred_at=self.now().isoformat(),
                    outcome=outcome,
                    actor=actor,
                )
            )
            self.audit(
                connection,
                actor,
                "IMPORT_" + outcome,
                "source_version",
                version_id,
                reason,
                {
                    "batch_id": batch,
                    "unique_bank_events": len(data.rows("payments"))
                    + len(data.rows("refunds_chargebacks")),
                    "duplicate_representations": data.duplicate_event_representations,
                },
                dataset_id=data.dataset.id,
            )
        return {
            "dataset_id": data.dataset.id,
            "version_id": version_id,
            "outcome": outcome,
            "batch_id": batch,
        }

    def _import_typed(self, c, data):
        def rows(name, mapping):
            return [{"id": r.id, **mapping(r)} for r in data.rows(name)]

        put(
            c,
            s.customers,
            rows("customers", lambda r: dict(dataset_id=r.dataset_id, display_name=r.display_name)),
        )
        put(
            c,
            s.accounts,
            rows(
                "accounts",
                lambda r: dict(
                    dataset_id=r.dataset_id,
                    customer_id=r.customer_id,
                    contract_reference=r.contract_reference,
                    currency=r.currency,
                ),
            ),
        )
        put(
            c,
            s.invoices,
            rows(
                "invoices",
                lambda r: dict(
                    dataset_id=r.dataset_id,
                    account_id=r.account_id,
                    reference=r.reference.strip().upper(),
                    issued_on=r.issued_on.isoformat(),
                    due_on=r.due_on.isoformat(),
                    amount_cents=r.amount_cents,
                ),
            ),
        )
        put(
            c,
            s.invoice_items,
            rows(
                "invoice_items",
                lambda r: dict(
                    invoice_id=r.invoice_id,
                    line_number=r.line_number,
                    net_cents=r.net_cents,
                    tax_cents=r.tax_cents,
                    gross_cents=r.gross_cents,
                ),
            ),
        )
        put(
            c,
            s.bank_statements,
            rows(
                "bank_statements",
                lambda r: dict(
                    dataset_id=r.dataset_id,
                    source_system=r.source_system,
                    file_sha256=r.file_sha256,
                    imported_at=r.imported_at.isoformat(),
                ),
            ),
        )
        event_rows = [
            dict(
                id=r.id,
                dataset_id=r.dataset_id,
                source_system=r.source_system,
                bank_event_id=r.bank_event_id,
                kind="payment" if isinstance(r, m.Payment) else r.kind,
                booked_on=r.booked_on.isoformat(),
                currency=r.currency,
                amount_cents=r.amount_cents,
            )
            for r in (*data.rows("payments"), *data.rows("refunds_chargebacks"))
        ]
        existing = {
            (r["dataset_id"], r["source_system"], r["bank_event_id"]): r["id"]
            for r in c.execute(select(s.bank_events)).mappings()
        }
        ensure(
            all(
                existing.get((r["dataset_id"], r["source_system"], r["bank_event_id"]), r["id"])
                == r["id"]
                for r in event_rows
            ),
            "Conflicting stable bank-event identity",
        )
        put(c, s.bank_events, event_rows)
        put(
            c,
            s.payments,
            rows("payments", lambda r: dict(account_id=r.account_id, reference=r.reference)),
        )
        put(
            c,
            s.reversals,
            rows("refunds_chargebacks", lambda r: dict(payment_id=r.payment_id, reason=r.reason)),
        )
        put(c, s.source_runs, rows("authoring_runs", lambda r: {}))
        put(
            c,
            s.source_cases,
            rows("review_cases", lambda r: dict(run_id=r.run_id, invoice_id=r.invoice_id)),
        )
        put(c, s.source_decisions, rows("manual_decisions", lambda r: dict(case_id=r.case_id)))
        correction_rows = rows(
            "corrections",
            lambda r: dict(
                invoice_id=r.invoice_id,
                decision_id=r.decision_id,
                amount_cents=r.amount_cents,
                effective_on=r.effective_on.isoformat(),
                reverses_correction_id=r.reverses_correction_id,
            ),
        )
        put(
            c,
            s.corrections,
            sorted(correction_rows, key=lambda r: r["reverses_correction_id"] is not None),
        )
        put(
            c,
            s.import_rows,
            rows(
                "import_rows",
                lambda r: dict(
                    import_id=r.import_id, record_id=r.record_id, row_number=r.row_number
                ),
            ),
        )

    def dataset_id(self, c, dataset_id=None):
        ids = c.execute(select(s.datasets.c.id)).scalars().all()
        ensure(
            dataset_id in ids if dataset_id else len(ids) == 1, "Specify one imported dataset ID"
        )
        return dataset_id or ids[0]

    def load_input(self, c, version_id, *, include_provenance=True, table_names=None):
        row = (
            c.execute(select(s.source_versions).where(s.source_versions.c.id == version_id))
            .mappings()
            .one()
        )
        meta = json.loads(row["metadata_json"])
        tables = {name: [] for name in TABLES}
        statement = (
            select(s.version_records.c.table_name, s.source_records.c.payload_json)
            .join(s.source_records, s.source_records.c.id == s.version_records.c.record_id)
            .where(s.version_records.c.version_id == version_id)
            .order_by(s.version_records.c.table_name, s.version_records.c.ordinal)
        )
        if table_names is not None:
            statement = statement.where(s.version_records.c.table_name.in_(table_names))
        for name, payload in c.execute(statement):
            tables[name].append(TABLES[name].model_validate_json(payload))
        provenance = []
        for payload in (
            c.execute(
                select(s.provenance.c.payload_json)
                .where(s.provenance.c.version_id == version_id)
                .order_by(s.provenance.c.ordinal)
            ).scalars()
            if include_provenance
            else ()
        ):
            value = json.loads(payload)
            value["original_values"] = tuple(tuple(pair) for pair in value["original_values"])
            provenance.append(SourceOccurrence(**value))
        return InputDataset(
            m.Dataset.model_validate(meta["dataset"]),
            {k: tuple(v) for k, v in tables.items()},
            {k: datetime.fromisoformat(v) for k, v in meta["bank_known_at"].items()},
            meta["source_manifest_sha256"],
            meta["source_hashes"],
            tuple(provenance),
            meta["duplicate_file_receipts"],
            meta["duplicate_event_representations"],
        )

    def _result(self, c, run_id):
        payload = c.execute(select(s.runs.c.result_json).where(s.runs.c.id == run_id)).scalar_one()
        result = ReconciliationResult.model_validate_json(payload)
        ensure(
            fingerprint(result.model_dump(mode="json", exclude={"run"}))
            == result.run.result_sha256,
            "Stored result hash mismatch",
        )
        return result

    def _head(self, c, dataset_id):
        row = (
            c.execute(select(s.ledger_heads).where(s.ledger_heads.c.dataset_id == dataset_id))
            .mappings()
            .first()
        )
        ensure(row is not None, "Reconcile this dataset before reviewing or changing money")
        return row

    def operations(self, c, dataset_id):
        return [
            Operation.model_validate_json(p)
            for p in c.execute(
                select(s.decisions.c.payload_json)
                .where(s.decisions.c.dataset_id == dataset_id)
                .order_by(s.decisions.c.sequence)
            ).scalars()
        ]

    def _header(self, c, result, version_id, base_id=None):
        put(
            c,
            s.rule_versions,
            [
                {
                    "id": result.rules_version,
                    "description": "Versioned financial rules; see engine and database guides",
                }
            ],
        )
        return put(
            c,
            s.runs,
            [
                dict(
                    id=result.run.id,
                    dataset_id=result.run.dataset_id,
                    source_version_id=version_id,
                    rule_version=result.rules_version,
                    base_run_id=base_id,
                    kind="LEDGER" if base_id else "ENGINE",
                    as_of=result.run.as_of.isoformat(),
                    known_at=result.run.known_at.isoformat(),
                    input_sha256=result.run.input_sha256,
                    result_sha256=result.run.result_sha256,
                    result_json=text_json(result.model_dump(mode="json")),
                    controls_json=text_json(result.controls),
                    status="completed",
                )
            ],
        )

    def _effects(self, c, result, actor, reason):
        new_allocs = put(
            c,
            s.allocations,
            [
                dict(
                    id=a.id,
                    run_id=a.run_id,
                    payment_id=a.payment_id,
                    invoice_id=a.invoice_id,
                    decision_id=a.decision_id,
                    amount_cents=a.amount_cents,
                    payload_json=text_json(a.model_dump(mode="json")),
                )
                for a in result.allocations
            ],
        )
        new_releases = put(
            c,
            s.allocation_releases,
            [
                dict(
                    id=r.id,
                    allocation_id=r.allocation_id,
                    decision_id=r.decision_id,
                    reversal_id=r.reversal_id,
                    amount_cents=r.amount_cents,
                    payload_json=text_json(r.model_dump(mode="json")),
                )
                for r in result.releases
            ],
        )
        for table, column, ids in (
            (s.run_allocations, "allocation_id", [a.id for a in result.allocations]),
            (s.run_releases, "release_id", [r.id for r in result.releases]),
        ):
            existing = set(
                c.execute(select(table.c[column]).where(table.c.run_id == result.run.id)).scalars()
            )
            fresh = [{"run_id": result.run.id, column: key} for key in ids if key not in existing]
            for start in range(0, len(fresh), 800):
                c.execute(table.insert(), fresh[start : start + 800])
        invoice_accounts = dict(c.execute(select(s.invoices.c.id, s.invoices.c.account_id)).all())
        audit_rows = []
        alloc_map = {a.id: a for a in result.allocations}
        for a in result.allocations:
            if a.id in new_allocs:
                audit_rows.append(
                    dict(
                        id=identity("audit"),
                        occurred_at=self.now().isoformat(),
                        actor=actor,
                        action="ALLOCATION_CREATED",
                        entity_type="Allocation",
                        entity_id=a.id,
                        reason=reason,
                        details_json=text_json(
                            {"amount_cents": a.amount_cents, "decision_id": a.decision_id}
                        ),
                        dataset_id=result.run.dataset_id,
                        run_id=result.run.id,
                        payment_id=a.payment_id,
                        invoice_id=a.invoice_id,
                        account_id=invoice_accounts[a.invoice_id],
                        synthetic=1,
                    )
                )
        for r in result.releases:
            if r.id in new_releases:
                a = alloc_map[r.allocation_id]
                audit_rows.append(
                    dict(
                        id=identity("audit"),
                        occurred_at=self.now().isoformat(),
                        actor=actor,
                        action="ALLOCATION_RELEASED",
                        entity_type="AllocationRelease",
                        entity_id=r.id,
                        reason=r.reason,
                        details_json=text_json(
                            {
                                "amount_cents": r.amount_cents,
                                "reversal_id": r.reversal_id,
                                "decision_id": r.decision_id,
                            }
                        ),
                        dataset_id=result.run.dataset_id,
                        run_id=result.run.id,
                        payment_id=a.payment_id,
                        invoice_id=a.invoice_id,
                        account_id=invoice_accounts[a.invoice_id],
                        synthetic=1,
                    )
                )
        for start in range(0, len(audit_rows), 800):
            c.execute(s.audit_events.insert(), audit_rows[start : start + 800])
        known_effects = set(
            c.execute(
                select(s.run_effects.c.effect_id).where(s.run_effects.c.run_id == result.run.id)
            ).scalars()
        )
        reversal_parents = dict(c.execute(select(s.reversals.c.id, s.reversals.c.payment_id)).all())
        correction_invoices = dict(
            c.execute(select(s.corrections.c.id, s.corrections.c.invoice_id)).all()
        )
        correction_invoices.update(
            dict(
                c.execute(
                    select(s.adjustments.c.id, s.adjustments.c.invoice_id).where(
                        s.adjustments.c.invoice_id.is_not(None)
                    )
                ).all()
            )
        )
        payment_accounts = {p.payment_id: p.validated_account_id for p in result.payments}
        for effect in result.adjustments:
            if effect.id not in known_effects:
                c.execute(
                    s.run_effects.insert().values(
                        run_id=result.run.id,
                        effect_id=effect.id,
                        source_record_id=effect.source_record_id,
                        payload_json=text_json(effect.model_dump(mode="json")),
                    )
                )
                payment_id = reversal_parents.get(effect.source_record_id)
                invoice_id = correction_invoices.get(effect.source_record_id)
                self.audit(
                    c,
                    actor,
                    effect.kind.upper() + "_HANDLED",
                    "AdjustmentEffect",
                    effect.source_record_id,
                    effect.reason,
                    effect.model_dump(mode="json"),
                    dataset_id=result.run.dataset_id,
                    run_id=result.run.id,
                    payment_id=payment_id,
                    invoice_id=invoice_id,
                    account_id=invoice_accounts.get(invoice_id)
                    if invoice_id
                    else payment_accounts.get(payment_id),
                )

    def _sync_cases(self, c, result, actor, reason):
        existing = {
            r["id"]: r
            for r in c.execute(
                select(s.review_cases).where(s.review_cases.c.dataset_id == result.run.dataset_id)
            ).mappings()
        }
        pending = set()
        for item in result.review_queue:
            ensure(
                item.subject_type == "payment",
                "Unsupported review subject for persisted payment workflow",
            )
            key = stable_id("case", [result.run.dataset_id, item.subject_id, item.reason_code])
            pending.add(key)
            if key not in existing:
                c.execute(
                    s.review_cases.insert().values(
                        id=key,
                        dataset_id=result.run.dataset_id,
                        payment_id=item.subject_id,
                        origin_run_id=result.run.id,
                        reason_code=item.reason_code,
                        status="OPEN",
                        version=1,
                        opened_at=self.now().isoformat(),
                        updated_at=self.now().isoformat(),
                    )
                )
                self.audit(
                    c,
                    actor,
                    "CASE_OPENED",
                    "ReviewCase",
                    key,
                    reason,
                    dataset_id=result.run.dataset_id,
                    run_id=result.run.id,
                    payment_id=item.subject_id,
                )
            elif existing[key]["status"] == "RESOLVED":
                self._transition(
                    c,
                    existing[key],
                    "REOPENED",
                    actor,
                    "New snapshot has remaining review cash",
                    result.run.id,
                )
            if not c.execute(
                select(s.case_evidence).where(
                    s.case_evidence.c.case_id == key, s.case_evidence.c.run_id == result.run.id
                )
            ).first():
                c.execute(
                    s.case_evidence.insert().values(
                        case_id=key,
                        run_id=result.run.id,
                        payload_json=text_json(item.model_dump(mode="json")),
                    )
                )
        for key, row in existing.items():
            if key not in pending and row["status"] != "RESOLVED":
                self._transition(
                    c,
                    row,
                    "RESOLVED",
                    actor,
                    "No pending cash review in accepted snapshot",
                    result.run.id,
                )

    def _transition(self, c, row, status, actor, reason, run_id=None):
        old = row["status"]
        allowed = {
            "OPEN": {"IN_REVIEW", "RESOLVED"},
            "IN_REVIEW": {"OPEN", "RESOLVED"},
            "RESOLVED": {"REOPENED"},
            "REOPENED": {"OPEN", "IN_REVIEW", "RESOLVED"},
        }
        ensure(status in allowed[old], f"Invalid review transition {old} -> {status}")
        changed = c.execute(
            update(s.review_cases)
            .where(s.review_cases.c.id == row["id"], s.review_cases.c.version == row["version"])
            .values(status=status, version=row["version"] + 1, updated_at=self.now().isoformat())
        )
        if changed.rowcount != 1:
            raise StaleUpdate("Stale review version; inspect and retry explicitly")
        self.audit(
            c,
            actor,
            "CASE_" + status,
            "ReviewCase",
            row["id"],
            reason,
            {"from": old, "to": status, "version": row["version"] + 1},
            dataset_id=row["dataset_id"],
            run_id=run_id,
            payment_id=row["payment_id"],
        )

    def _activate(self, c, result, actor, reason):
        head = (
            c.execute(
                select(s.ledger_heads).where(s.ledger_heads.c.dataset_id == result.run.dataset_id)
            )
            .mappings()
            .first()
        )
        if head and head["run_id"] == result.run.id:
            return head["revision"]
        revision = head["revision"] + 1 if head else 1
        if head:
            c.execute(
                update(s.ledger_heads)
                .where(s.ledger_heads.c.dataset_id == result.run.dataset_id)
                .values(run_id=result.run.id, revision=revision)
            )
        else:
            c.execute(
                s.ledger_heads.insert().values(
                    dataset_id=result.run.dataset_id, run_id=result.run.id, revision=revision
                )
            )
        self._sync_cases(c, result, actor, reason)
        self.audit(
            c,
            actor,
            "SNAPSHOT_ACTIVATED",
            "ReconciliationRun",
            result.run.id,
            reason,
            {"revision": revision, "supersedes": head["run_id"] if head else None},
            dataset_id=result.run.dataset_id,
            run_id=result.run.id,
        )
        return revision

    def persist_reconciliation(
        self, actor, reason, dataset_id=None, options=None, historical=False
    ):
        try:
            actor_reason(actor, reason)
            with self.db.transaction() as c:
                dataset_id = self.dataset_id(c, dataset_id)
                version = c.execute(
                    select(s.source_heads.c.version_id).where(
                        s.source_heads.c.dataset_id == dataset_id
                    )
                ).scalar_one()
                data = self.load_input(c, version)
                head = (
                    c.execute(
                        select(s.ledger_heads).where(s.ledger_heads.c.dataset_id == dataset_id)
                    )
                    .mappings()
                    .first()
                )
                old = self._result(c, head["run_id"]) if head else None
                options = options or (
                    RunOptions(evaluation_date=old.run.as_of, known_at=old.run.known_at)
                    if old
                    else default_options(data.dataset.effective_at.date())
                )
                options.aware()
                if old and not historical:
                    ensure(
                        options.evaluation_date >= old.run.as_of
                        and options.known_at >= old.run.known_at,
                        "Older cutoff requires historical=True; ledger cannot move backwards",
                    )
                base = reconcile(data, options)
                self._header(c, base, version)
                self._effects(c, base, actor, reason)
                result = replay(base, data, self.operations(c, dataset_id))
                self._header(
                    c, result, version, base.run.id if result.run.id != base.run.id else None
                )
                self._effects(c, result, actor, reason)
                if not historical:
                    self._activate(c, result, actor, reason)
                self.audit(
                    c,
                    actor,
                    "RECONCILIATION_COMPLETED",
                    "ReconciliationRun",
                    result.run.id,
                    reason,
                    {"historical": historical, "controls": result.controls},
                    dataset_id=dataset_id,
                    run_id=result.run.id,
                )
                return result
        except Exception as exc:
            self.rejected(actor, "RECONCILIATION", exc)
            raise

    def current(self, dataset_id=None, run_id=None):
        with self.db.engine.connect() as c:
            dataset_id = self.dataset_id(c, dataset_id)
            if run_id is None:
                head = self._head(c, dataset_id)
                run_id = head["run_id"]
            result = self._result(c, run_id)
            ensure(result.run.dataset_id == dataset_id, "Run belongs to another dataset")
            return result

    def ledger_info(self, dataset_id=None):
        with self.db.engine.connect() as c:
            dataset_id = self.dataset_id(c, dataset_id)
            return dict(self._head(c, dataset_id))

    def list_cases(
        self,
        dataset_id=None,
        reason=None,
        status=None,
        min_cents=None,
        max_cents=None,
        opened_from=None,
        opened_to=None,
    ):
        if min_cents is not None:
            ensure(type(min_cents) is int, "Amount filter must be integer cents")
        if max_cents is not None:
            ensure(type(max_cents) is int, "Amount filter must be integer cents")
        with self.db.engine.connect() as c:
            dataset_id = self.dataset_id(c, dataset_id)
            head = self._head(c, dataset_id)
            result = self._result(c, head["run_id"])
            amounts = {p.payment_id: p.unapplied_cents for p in result.payments}
            query = select(s.review_cases).where(s.review_cases.c.dataset_id == dataset_id)
            query = (
                query.where(s.review_cases.c.status == status)
                if status
                else query.where(s.review_cases.c.status != "RESOLVED")
            )
            if reason:
                query = query.where(s.review_cases.c.reason_code == reason)
            rows = []
            for row in c.execute(query.order_by(s.review_cases.c.id)).mappings():
                amount = amounts.get(row["payment_id"], 0)
                if (
                    min_cents is not None
                    and amount < min_cents
                    or max_cents is not None
                    and amount > max_cents
                ):
                    continue
                if (
                    opened_from
                    and row["opened_at"][:10] < opened_from
                    or opened_to
                    and row["opened_at"][:10] > opened_to
                ):
                    continue
                rows.append({**row, "amount_cents": amount, "ledger_revision": head["revision"]})
            return rows

    def inspect_case(self, case_id):
        with self.db.engine.connect() as c:
            case = (
                c.execute(select(s.review_cases).where(s.review_cases.c.id == case_id))
                .mappings()
                .one()
            )
            head = self._head(c, case["dataset_id"])
            run = c.execute(select(s.runs).where(s.runs.c.id == head["run_id"])).mappings().one()
            data = self.load_input(c, run["source_version_id"])
            result = self._result(c, head["run_id"])
            payment = next(p for p in data.rows("payments") if p.id == case["payment_id"])
            queue = next(
                (
                    e
                    for e in result.review_queue
                    if e.subject_id == payment.id and e.reason_code == case["reason_code"]
                ),
                None,
            )
            outcome = next(p for p in result.payments if p.payment_id == payment.id)
            invoices = {i.id: i for i in data.rows("invoices")}
            suggested = queue.candidates if queue else ()
            return {
                "synthetic": True,
                "case": dict(case),
                "ledger_revision": head["revision"],
                "payment": payment.model_dump(mode="json"),
                "source_known_at": data.bank_known_at[payment.id].isoformat(),
                "source_provenance": [
                    asdict(p) for p in data.provenance if p.record_id == payment.id
                ],
                "balance": outcome.model_dump(mode="json"),
                "candidates": [candidate.model_dump(mode="json") for candidate in suggested],
                "candidate_invoices": [
                    invoices[candidate.invoice_id].model_dump(mode="json")
                    for candidate in suggested
                ],
                "candidate_balances": [
                    i.model_dump(mode="json")
                    for i in result.invoices
                    if i.invoice_id in {candidate.invoice_id for candidate in suggested}
                ],
                "decisions": [
                    o.model_dump(mode="json")
                    for o in self.operations(c, case["dataset_id"])
                    if o.case_id == case_id
                ],
            }

    def change_case(self, case_id, status, actor, reason, expected_version, note=""):
        try:
            actor_reason(actor, reason)
            ensure(
                status in ("OPEN", "IN_REVIEW"),
                "RESOLVED/REOPENED require an accepted financial action",
            )
            with self.db.transaction() as c:
                row = (
                    c.execute(select(s.review_cases).where(s.review_cases.c.id == case_id))
                    .mappings()
                    .one()
                )
                if type(expected_version) is not int or row["version"] != expected_version:
                    raise StaleUpdate("Stale review version")
                self._transition(c, row, status, actor, reason)
                if note:
                    self.audit(
                        c,
                        actor,
                        "REVIEW_NOTE",
                        "ReviewCase",
                        case_id,
                        reason,
                        {"note": note},
                        dataset_id=row["dataset_id"],
                        payment_id=row["payment_id"],
                    )
        except Exception as exc:
            self.rejected(actor, "CASE_TRANSITION", exc, {"case_id": case_id})
            raise

    def _guard(self, c, dataset_id, expected_revision, case_id=None, expected_version=None):
        head = self._head(c, dataset_id)
        if type(expected_revision) is not int or head["revision"] != expected_revision:
            raise StaleUpdate("Stale ledger revision; inspect controls and retry explicitly")
        case = None
        if case_id:
            case = (
                c.execute(select(s.review_cases).where(s.review_cases.c.id == case_id))
                .mappings()
                .one()
            )
            ensure(case["dataset_id"] == dataset_id, "Cross-dataset case")
            if type(expected_version) is not int or case["version"] != expected_version:
                raise StaleUpdate("Stale review version; inspect the case")
        return head, case

    def allocate_case(
        self,
        case_id,
        targets,
        actor,
        reason,
        expected_version,
        expected_revision,
        note="",
        request_id=None,
    ):
        return self._financial(
            "allocate",
            actor,
            reason,
            {"targets": targets},
            case_id=case_id,
            expected_version=expected_version,
            expected_revision=expected_revision,
            note=note,
            request_id=request_id,
        )

    def defer_case(self, case_id, actor, reason, expected_version, expected_revision, note=""):
        return self._financial(
            "defer",
            actor,
            reason,
            {},
            case_id=case_id,
            expected_version=expected_version,
            expected_revision=expected_revision,
            note=note,
        )

    def correct_invoice(
        self, invoice_id, amount_cents, actor, reason, expected_revision, note="", request_id=None
    ):
        return self._financial(
            "correction",
            actor,
            reason,
            {"invoice_id": invoice_id, "amount_cents": amount_cents},
            expected_revision=expected_revision,
            note=note,
            request_id=request_id,
        )

    def cash_outflow(
        self,
        payment_id,
        kind,
        amount_cents,
        bank_event_id,
        actor,
        reason,
        expected_revision,
        releases=None,
        note="",
        request_id=None,
    ):
        return self._financial(
            kind,
            actor,
            reason,
            {
                "payment_id": payment_id,
                "amount_cents": amount_cents,
                "bank_event_id": bank_event_id,
                "releases": releases or [],
            },
            expected_revision=expected_revision,
            note=note,
            request_id=request_id,
        )

    def reverse_decision(
        self,
        decision_id,
        actor,
        reason,
        expected_revision,
        expected_version=None,
        note="",
        request_id=None,
    ):
        with self.db.engine.connect() as c:
            payload = c.execute(
                select(s.decisions.c.payload_json).where(s.decisions.c.id == decision_id)
            ).scalar_one()
            original = Operation.model_validate_json(payload)
        ensure(
            original.action in ("allocate", "correction"),
            "Bank cash, deferrals and undo entries cannot be reversed",
        )
        return self._financial(
            "reverse",
            actor,
            reason,
            {},
            case_id=original.case_id,
            dataset_id=original.dataset_id,
            expected_revision=expected_revision,
            expected_version=expected_version,
            note=note,
            request_id=request_id,
            reverses_decision_id=decision_id,
        )

    def _financial(
        self,
        action,
        actor,
        reason,
        payload,
        expected_revision,
        case_id=None,
        expected_version=None,
        dataset_id=None,
        note="",
        request_id=None,
        reverses_decision_id=None,
    ):
        try:
            actor_reason(actor, reason)
            ensure(len(note) <= 2000, "Note is too long")
            with self.db.transaction() as c:
                if case_id:
                    dataset_id = c.execute(
                        select(s.review_cases.c.dataset_id).where(s.review_cases.c.id == case_id)
                    ).scalar_one()
                elif not dataset_id and payload.get("invoice_id"):
                    dataset_id = c.execute(
                        select(s.invoices.c.dataset_id).where(
                            s.invoices.c.id == payload["invoice_id"]
                        )
                    ).scalar_one_or_none()
                    ensure(dataset_id is not None, "Unknown invoice")
                elif not dataset_id and payload.get("payment_id"):
                    dataset_id = c.execute(
                        select(s.bank_events.c.dataset_id).where(
                            s.bank_events.c.id == payload["payment_id"]
                        )
                    ).scalar_one_or_none()
                    ensure(dataset_id is not None, "Unknown payment")
                dataset_id = self.dataset_id(c, dataset_id)
                operation_id = (
                    stable_id("decision", [dataset_id, request_id])
                    if request_id
                    else identity("decision")
                )
                intent = {
                    "action": action,
                    "case_id": case_id,
                    "actor": actor,
                    "reason": reason,
                    "note": note,
                    "payload": payload,
                    "reverses_decision_id": reverses_decision_id,
                }
                previous = c.execute(
                    select(s.decisions.c.payload_json).where(s.decisions.c.id == operation_id)
                ).scalar_one_or_none()
                if previous:
                    saved = json.loads(previous)
                    ensure(
                        saved["payload"].get("request_intent") == intent,
                        "Request ID reused with different intent",
                    )
                    return {
                        "decision_id": operation_id,
                        "reused": True,
                        "run_id": self._head(c, dataset_id)["run_id"],
                    }
                head, case = self._guard(
                    c, dataset_id, expected_revision, case_id, expected_version
                )
                current = self._result(c, head["run_id"])
                headrow = (
                    c.execute(select(s.runs).where(s.runs.c.id == head["run_id"])).mappings().one()
                )
                version = c.execute(
                    select(s.source_heads.c.version_id).where(
                        s.source_heads.c.dataset_id == dataset_id
                    )
                ).scalar_one()
                if action == "reverse":
                    version = headrow["source_version_id"]
                else:
                    ensure(
                        version == headrow["source_version_id"],
                        "New import pending; reconcile before manual changes",
                    )
                created = self.now()
                ensure(
                    created >= current.run.known_at,
                    "Clock predates ledger cutoff; historical financial change rejected",
                )
                data = self.load_input(c, version)
                operations = self.operations(c, dataset_id)
                sequence = max((o.sequence for o in operations), default=0) + 1
                content = json.loads(text_json(payload))
                if action == "allocate":
                    ensure(
                        case["status"] in ("OPEN", "IN_REVIEW", "REOPENED"),
                        "Case is already resolved",
                    )
                    content["payment_id"] = case["payment_id"]
                    content["targets"] = [
                        Target.model_validate(t).model_dump(mode="json") for t in content["targets"]
                    ]
                if action == "correction":
                    amount = content["amount_cents"]
                    ensure(
                        type(amount) is int and 0 < abs(amount) <= 9000000000000000,
                        "Correction requires nonzero integer cents within model bounds",
                    )
                if action in ("refund", "chargeback"):
                    event = m.Reversal(
                        id=stable_id("reversal", operation_id),
                        synthetic=True,
                        dataset_id=dataset_id,
                        source_record_id=operation_id,
                        source_system="SYN_LOCAL_ADJUSTMENT",
                        bank_event_id=content["bank_event_id"],
                        payment_id=content["payment_id"],
                        kind=action,
                        amount_cents=content["amount_cents"],
                        booked_on=current.run.as_of,
                        value_on=current.run.as_of,
                        reason=reason,
                    )
                    content["event"] = event.model_dump(mode="json")
                    # Durable explicit release signatures survive automatic snapshot IDs changing.
                    alloc_map = {a.id: a for a in current.allocations}
                    for item in content["releases"]:
                        ensure(
                            item["allocation_id"] in alloc_map, "Unknown allocation in release plan"
                        )
                        allocation = alloc_map[item["allocation_id"]]
                        item["signature"] = {
                            k: v
                            for k, v in allocation.model_dump(mode="json").items()
                            if k
                            in (
                                "payment_id",
                                "invoice_id",
                                "decision_id",
                                "amount_cents",
                                "effective_on",
                            )
                        }
                content["request_intent"] = json.loads(text_json(intent))
                operation = Operation(
                    id=operation_id,
                    dataset_id=dataset_id,
                    case_id=case_id,
                    sequence=sequence,
                    action=action,
                    effective_on=current.run.as_of,
                    created_at=created,
                    actor=actor,
                    reason=reason,
                    note=note,
                    payload=content,
                    reverses_decision_id=reverses_decision_id,
                )
                base = reconcile(
                    data, RunOptions(evaluation_date=current.run.as_of, known_at=created)
                )
                prior = replay(base, data, operations)
                ensure(
                    self._balances(prior) == self._balances(current),
                    "New knowledge changes balances; reconcile explicitly before a manual action",
                )
                if action == "defer":
                    operation = operation.model_copy(update={"origin_run_id": current.run.id})
                    self._insert_decision(
                        c,
                        operation,
                        base.run.id
                        if c.execute(select(s.runs.c.id).where(s.runs.c.id == base.run.id)).first()
                        else headrow["base_run_id"] or current.run.id,
                    )
                    self.audit(
                        c,
                        actor,
                        "REVIEW_DEFERRED",
                        "ReviewCase",
                        case_id,
                        reason,
                        {"note": note},
                        dataset_id=dataset_id,
                        run_id=current.run.id,
                        payment_id=case["payment_id"],
                    )
                    self._touch_case(c, case, actor, reason)
                    return {"decision_id": operation.id, "run_id": current.run.id, "reused": False}
                result = replay(base, data, [*operations, operation])
                self._header(c, base, version)
                self._effects(c, base, actor, reason)
                self._header(c, result, version, base.run.id)
                operation = operation.model_copy(update={"origin_run_id": result.run.id})
                self._insert_decision(c, operation, base.run.id)
                self._insert_adjustment(c, operation, operations)
                self._effects(c, result, actor, reason)
                revision = self._activate(c, result, actor, reason)
                if case:
                    nowcase = (
                        c.execute(select(s.review_cases).where(s.review_cases.c.id == case_id))
                        .mappings()
                        .one()
                    )
                    if action == "allocate" and nowcase["status"] in ("OPEN", "REOPENED"):
                        self._transition(
                            c,
                            nowcase,
                            "IN_REVIEW",
                            actor,
                            "Part of the receipt remains unresolved",
                            result.run.id,
                        )
                    elif nowcase["version"] == case["version"]:
                        self._touch_case(c, nowcase, actor, reason)
                self.audit(
                    c,
                    actor,
                    "DECISION_" + action.upper(),
                    "ManualDecision",
                    operation.id,
                    reason,
                    {"note": note, "case_id": case_id, "revision": revision},
                    dataset_id=dataset_id,
                    run_id=result.run.id,
                    payment_id=case["payment_id"] if case else content.get("payment_id"),
                    invoice_id=content.get("invoice_id"),
                )
                return {
                    "decision_id": operation.id,
                    "run_id": result.run.id,
                    "revision": revision,
                    "reused": False,
                }
        except Exception as exc:
            self.rejected(
                actor,
                "FINANCIAL_ACTION",
                exc,
                {
                    "action": action,
                    "case_id": case_id,
                    "payment_id": payload.get("payment_id"),
                    "invoice_id": payload.get("invoice_id"),
                },
            )
            raise

    def _balances(self, result):
        return {
            "controls": result.controls,
            "payments": {
                p.payment_id: (
                    p.received_cents,
                    p.reversed_cents,
                    p.allocated_cents,
                    p.unapplied_cents,
                    p.validated_account_id,
                )
                for p in result.payments
            },
            "invoices": {
                i.invoice_id: (i.adjusted_face_cents, i.allocated_cents, i.outstanding_cents)
                for i in result.invoices
            },
        }

    def _touch_case(self, c, case, actor, reason):
        c.execute(
            update(s.review_cases)
            .where(s.review_cases.c.id == case["id"], s.review_cases.c.version == case["version"])
            .values(version=case["version"] + 1, updated_at=self.now().isoformat())
        )
        self.audit(
            c,
            actor,
            "CASE_TOUCHED",
            "ReviewCase",
            case["id"],
            reason,
            {"version": case["version"] + 1},
            dataset_id=case["dataset_id"],
            payment_id=case["payment_id"],
        )

    def _insert_decision(self, c, op, base_id):
        put(
            c,
            s.decisions,
            [
                dict(
                    id=op.id,
                    dataset_id=op.dataset_id,
                    case_id=op.case_id,
                    base_run_id=base_id,
                    sequence=op.sequence,
                    action=op.action,
                    effective_on=op.effective_on.isoformat(),
                    created_at=op.created_at.isoformat(),
                    actor=op.actor,
                    reason=op.reason,
                    note=op.note,
                    payload_json=text_json(op.model_dump(mode="json")),
                    reverses_decision_id=op.reverses_decision_id,
                )
            ],
        )

    def _insert_adjustment(self, c, op, prior):
        if op.action in ("refund", "chargeback"):
            event = m.Reversal.model_validate(op.payload["event"])
            put(
                c,
                s.source_records,
                [
                    dict(
                        id=event.id,
                        dataset_id=op.dataset_id,
                        table_name="local_reversals",
                        payload_sha256=fingerprint(event.model_dump(mode="json")),
                        payload_json=text_json(event.model_dump(mode="json")),
                        synthetic=1,
                    )
                ],
            )
            put(
                c,
                s.bank_events,
                [
                    dict(
                        id=event.id,
                        dataset_id=op.dataset_id,
                        source_system=event.source_system,
                        bank_event_id=event.bank_event_id,
                        kind=event.kind,
                        booked_on=event.booked_on.isoformat(),
                        currency=event.currency,
                        amount_cents=event.amount_cents,
                    )
                ],
            )
            put(
                c,
                s.reversals,
                [dict(id=event.id, payment_id=event.payment_id, reason=event.reason)],
            )
            put(
                c,
                s.adjustments,
                [
                    dict(
                        id=event.id,
                        decision_id=op.id,
                        invoice_id=None,
                        reversal_id=event.id,
                        signed_cents=-event.amount_cents,
                        payload_json=text_json(event.model_dump(mode="json")),
                    )
                ],
            )
        elif (
            op.action == "correction"
            or op.action == "reverse"
            and next(o for o in prior if o.id == op.reverses_decision_id).action == "correction"
        ):
            original = next((o for o in prior if o.id == op.reverses_decision_id), None)
            amount = -original.payload["amount_cents"] if original else op.payload["amount_cents"]
            invoice_id = original.payload["invoice_id"] if original else op.payload["invoice_id"]
            correction = m.Correction(
                id=stable_id("correction", op.id),
                synthetic=True,
                invoice_id=invoice_id,
                decision_id=op.id,
                amount_cents=amount,
                effective_on=op.effective_on,
                created_at=op.created_at,
                reason=op.reason,
                reverses_correction_id=stable_id("correction", original.id) if original else None,
            )
            put(
                c,
                s.adjustments,
                [
                    dict(
                        id=correction.id,
                        decision_id=op.id,
                        invoice_id=invoice_id,
                        reversal_id=None,
                        signed_cents=amount,
                        payload_json=text_json(correction.model_dump(mode="json")),
                    )
                ],
            )

    def audit_history(
        self, dataset_id=None, payment_id=None, invoice_id=None, account_id=None, run_id=None
    ):
        with self.db.engine.connect() as c:
            query = select(s.audit_events, literal_column("audit_events.rowid").label("sequence"))
            for name, value in (
                ("dataset_id", dataset_id),
                ("payment_id", payment_id),
                ("invoice_id", invoice_id),
                ("account_id", account_id),
                ("run_id", run_id),
            ):
                if value:
                    query = query.where(s.audit_events.c[name] == value)
            return [
                {**row, "details": json.loads(row["details_json"])}
                for row in c.execute(
                    query.order_by(literal_column("audit_events.rowid"))
                ).mappings()
            ]

    def counts(self):
        with self.db.engine.connect() as c:
            return {
                name: c.execute(select(func.count()).select_from(table)).scalar_one()
                for name, table in s.metadata.tables.items()
            }
