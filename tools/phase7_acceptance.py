"""Isolated, reproducible acceptance/performance run; never opens primary for writes."""

# Timed callables run synchronously inside measured(); none escape the loop.
# ruff: noqa: B023

import hashlib
import json
import os
import platform
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import openpyxl
from streamlit.testing.v1 import AppTest

from energy_reconciliation.dashboard.pages import PAGES
from energy_reconciliation.data_generation.export import export_dataset
from energy_reconciliation.data_generation.generator import generate_dataset
from energy_reconciliation.data_generation.settings import GenerationSettings
from energy_reconciliation.persistence.database import Database
from energy_reconciliation.persistence.service import Store
from energy_reconciliation.reporting.data import read_report
from energy_reconciliation.reporting.excel import SHEETS, export

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "SYNTHETIC_DEMO:phase7-acceptance"


def main():
    primary = ROOT / "data/phase4-demo.sqlite3"
    original = hashlib.sha256(primary.read_bytes()).hexdigest()
    root = ROOT / "outputs/phase7" / datetime.now(UTC).strftime("acceptance-%Y%m%dT%H%M%S")
    root.mkdir()
    metrics = {
        "environment": {
            "python": platform.python_version(),
            "os": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "root": str(root),
    }
    timings = {}

    def measured(name, action):
        start = time.perf_counter()
        value = action()
        timings[name] = time.perf_counter() - start
        (root / "progress.json").write_text(json.dumps(timings, indent=2))
        print(name, round(timings[name], 4), flush=True)
        return value

    for size in (500, 750):
        prefix = str(size)
        source = root / prefix / "source"
        data = measured(
            prefix + "_generation",
            lambda: generate_dataset(GenerationSettings(customer_count=size)),
        )
        measured(prefix + "_source_export", lambda data=data: export_dataset(data, source))
        del data
        db = Database(root / prefix / "isolated.sqlite3")
        store = Store(db)
        measured(
            prefix + "_import", lambda: store.import_directory(source, ACTOR, "Phase 7 import")
        )
        measured(
            prefix + "_reconciliation", lambda: store.persist_reconciliation(ACTOR, "Baseline")
        )
        baseline = store.current()
        assert all(p.unapplied_cents >= 0 for p in baseline.payments)
        assert all(i.outstanding_cents >= 0 for i in baseline.invoices)
        if size == 750:
            metrics["larger_counts"] = baseline.source_counts
            db.close()
            continue
        case = store.list_cases(reason="missing_reference")[0]
        view = store.inspect_case(case["id"])
        target = next(
            i for i in view["candidate_balances"] if i["outstanding_cents"] >= case["amount_cents"]
        )
        decision = measured(
            "manual_allocation",
            lambda: store.allocate_case(
                case["id"],
                [{"invoice_id": target["invoice_id"], "amount_cents": case["amount_cents"]}],
                ACTOR,
                "Explicit supported synthetic selection",
                case["version"],
                case["ledger_revision"],
            ),
        )
        allocated = store.current()
        assert allocated.controls["net_allocated_cents"] == (
            baseline.controls["net_allocated_cents"] + case["amount_cents"]
        )
        after_case = store.inspect_case(case["id"])
        measured(
            "manual_reversal",
            lambda: store.reverse_decision(
                decision["decision_id"],
                ACTOR,
                "Restore synthetic acceptance allocation",
                after_case["ledger_revision"],
                expected_version=after_case["case"]["version"],
            ),
        )
        restored = store.current()
        assert restored.controls == baseline.controls
        report = measured("report_query", lambda: read_report(db.path))
        workbook = measured("excel_export", lambda: export(report, root / "reports"))
        csv_path = measured(
            "csv_export", lambda: export(report, root / "reports", kind="exceptions")
        )
        wb = openpyxl.load_workbook(workbook, data_only=True)
        assert wb.sheetnames == SHEETS
        # Independent SQL sums using selected run memberships, not historical totals.
        with closing(sqlite3.connect(db.path)) as c:
            run_id = restored.run.id
            total_a = c.execute(
                "select sum(a.amount_cents) from allocations a join run_allocations r "
                "on a.id=r.allocation_id where r.run_id=?",
                (run_id,),
            ).fetchone()[0]
            total_l = c.execute(
                "select sum(a.amount_cents) from allocation_releases a join run_releases r "
                "on a.id=r.release_id where r.run_id=?",
                (run_id,),
            ).fetchone()[0]
            assert total_a - total_l == restored.controls["net_allocated_cents"]
            measured(
                "indexed_payment_query",
                lambda: c.execute(
                    "select * from payments where id=?", (baseline.payments[0].payment_id,)
                ).fetchone(),
            )
        headers = {cell.value: n for n, cell in enumerate(wb["Invoice Register"][5])}
        values = list(wb["Invoice Register"].iter_rows(min_row=6, values_only=True))
        # Currency cells are euros; Decimal(str(...)) restores exact cents.
        from decimal import Decimal

        outstanding = sum(
            int(Decimal(str(row[headers["Outstanding (EUR)"]])) * 100) for row in values if row[0]
        )
        assert outstanding == restored.controls["outstanding_cents"]
        wb.close()
        os.environ["ENERGY_RECONCILIATION_DB"] = str(db.path)
        os.environ["ENERGY_RECONCILIATION_EXPORTS"] = str(root / "dashboard-exports")
        os.environ["ENERGY_RECONCILIATION_READ_ONLY"] = "1"
        app = measured(
            "dashboard_first_render",
            lambda: AppTest.from_file(
                str(ROOT / "src/energy_reconciliation/dashboard/app.py"), default_timeout=120
            ).run(),
        )
        assert not app.exception
        for page in PAGES:
            app.sidebar.radio[0].set_value(page).run(timeout=120)
            assert not app.exception, page
        measured("duplicate_import", lambda: store.import_directory(source, ACTOR, "Repeat import"))
        measured("repeat_reconciliation", lambda: store.persist_reconciliation(ACTOR, "Repeat run"))
        assert store.current() == restored
        metrics.update(
            {
                "workbook": str(workbook),
                "csv": str(csv_path),
                "pages": list(PAGES),
                "controls": restored.controls,
                "source_counts": restored.source_counts,
                "manual_amount_cents": case["amount_cents"],
            }
        )
        db.close()
    # Windows records process peak working set, including native library memory.
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working_set",
                "working_set",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    ]
    assert ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    peak = counters.peak_working_set
    assert hashlib.sha256(primary.read_bytes()).hexdigest() == original
    metrics.update(
        {
            "timings_seconds": timings,
            "process_peak_working_set_bytes": peak,
            "primary_unchanged_sha256": original,
        }
    )
    (ROOT / "outputs/phase7/acceptance.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
