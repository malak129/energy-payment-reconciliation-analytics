"""Reuse Phase 5 exporters, including its financial validation and no-clobber policy."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from energy_reconciliation.dashboard.queries import snapshot
from energy_reconciliation.reporting.data import read_report
from energy_reconciliation.reporting.excel import export


def generate(
    path, dataset_id, run_id, root, *, kind="excel", statuses=None, category=None, search=""
):
    if kind == "excel":
        report = read_report(Path(path), dataset_id=dataset_id, run_id=run_id)
    else:
        report = snapshot(path, dataset_id, run_id)
        rows = [
            r
            for r in report.tables["Exception Queue"]
            if (statuses is None or r["status"] in statuses)
            and (not category or r["reason_code"] == category)
            and (not search.strip() or search.strip().casefold() in str(r).casefold())
        ]
        report = replace(report, tables={**report.tables, "Exception Queue": rows})
    output = export(report, Path(root) / uuid4().hex, kind=kind, status="all")
    return output, output.read_bytes(), [r for r in report.checks if r["status"] == "FAIL"]
