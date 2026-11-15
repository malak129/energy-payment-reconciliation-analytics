"""Read-only database queries and bounded, explicitly invalidated analytical cache."""

from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from sqlalchemy import func, literal_column, or_, select

from energy_reconciliation.ingestion.csv_dataset import ensure
from energy_reconciliation.persistence import schema as s
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reporting.data import read_report


@contextmanager
def reader(path):
    db = Database(Path(path), read_only=True)
    try:
        yield Store(db)
    finally:
        db.close()


def identity(path):
    path = Path(path).resolve()
    ensure(path.is_file(), "Database missing. Initialize, import and reconcile with the CLI first.")

    def stamp(p):
        return (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None

    return (
        str(path),
        stamp(path),
        stamp(Path(str(path) + "-wal")),
        stamp(Path(str(path) + "-journal")),
    )


@st.cache_data(max_entries=4, ttl=120, show_spinner=False)
def _snapshot(path, token, dataset_id, run_id):
    return read_report(Path(path), dataset_id=dataset_id, run_id=run_id, lightweight=True)


def snapshot(path, dataset_id=None, run_id=None):
    token = identity(path)
    return _snapshot(token[0], token, dataset_id, run_id)


def invalidate():
    _snapshot.clear()
    _case_snapshot.clear()


def catalog(path):
    with reader(path) as store, store.db.engine.connect() as c:
        c.exec_driver_sql("BEGIN")
        return dict(
            datasets=c.execute(select(s.datasets.c.id).order_by(s.datasets.c.id)).scalars().all(),
            heads={r["dataset_id"]: dict(r) for r in c.execute(select(s.ledger_heads)).mappings()},
            runs=[
                dict(r)
                for r in c.execute(
                    select(
                        s.runs.c.id,
                        s.runs.c.dataset_id,
                        s.runs.c.as_of,
                        s.runs.c.known_at,
                        s.runs.c.kind,
                        s.runs.c.rule_version,
                        s.runs.c.source_version_id,
                        s.runs.c.result_sha256,
                    ).order_by(s.runs.c.known_at.desc(), s.runs.c.id)
                ).mappings()
            ],
        )


@st.cache_data(max_entries=8, ttl=60, show_spinner=False)
def _case_snapshot(path, token, case_id):
    with reader(path) as store:
        return store.inspect_case(case_id)


def case_view(path, case_id):
    token = identity(path)
    return _case_snapshot(token[0], token, case_id)


def audit_page(
    path,
    dataset_id,
    *,
    search="",
    start: date | None = None,
    end: date | None = None,
    page=1,
    size=50,
):
    ensure(type(page) is int and page >= 1 and 1 <= size <= 100, "Invalid audit page")
    ensure(start is None or end is None or start <= end, "Date range is reversed")
    conditions = [s.audit_events.c.dataset_id == dataset_id]
    if search.strip():
        conditions.append(
            or_(
                *(
                    func.lower(col).contains(search.strip().lower(), autoescape=True)
                    for col in (
                        s.audit_events.c.entity_id,
                        s.audit_events.c.action,
                        s.audit_events.c.payment_id,
                        s.audit_events.c.invoice_id,
                        s.audit_events.c.account_id,
                        s.audit_events.c.run_id,
                    )
                )
            )
        )
    if start:
        conditions.append(s.audit_events.c.occurred_at >= start.isoformat() + "T00:00:00")
    if end:
        conditions.append(
            s.audit_events.c.occurred_at < (end + timedelta(days=1)).isoformat() + "T00:00:00"
        )
    with reader(path) as store, store.db.engine.connect() as c:
        c.exec_driver_sql("BEGIN")
        total = c.execute(
            select(func.count()).select_from(s.audit_events).where(*conditions)
        ).scalar_one()
        rows = [
            dict(r)
            for r in c.execute(
                select(literal_column("rowid").label("sequence"), s.audit_events)
                .where(*conditions)
                .order_by(literal_column("rowid").desc())
                .offset((page - 1) * size)
                .limit(size)
            ).mappings()
        ]
    return rows, total


def operations_metadata(path, dataset_id):
    with reader(path) as store, store.db.engine.connect() as c:
        return dict(
            rules=[dict(r) for r in c.execute(select(s.rule_versions)).mappings()],
            imports=[
                dict(r)
                for r in c.execute(
                    select(s.import_batches)
                    .join(
                        s.source_versions, s.source_versions.c.id == s.import_batches.c.version_id
                    )
                    .where(s.source_versions.c.dataset_id == dataset_id)
                ).mappings()
            ],
        )
