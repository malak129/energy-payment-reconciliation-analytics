"""Portable machine-readable results and a human-readable financial control summary."""

import os
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from energy_reconciliation.ingestion.csv_dataset import InputDataset
from energy_reconciliation.reconciliation.results import ReconciliationResult
from energy_reconciliation.utilities.serialization import canonical


def eur(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}{abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def summary(result: ReconciliationResult) -> str:
    lines = [
        "# SYNTHETIC reconciliation - financial controls",
        "",
        f"Run: {result.run.id}",
        f"Rules: {result.rules_version}",
        f"Evaluation date: {result.run.as_of.isoformat()}",
        f"Known at: {result.run.known_at.isoformat()}",
        f"Result SHA-256: {result.run.result_sha256}",
        "",
        "| Financial measure | EUR |",
        "|---|---:|",
    ]
    for name, value in result.controls.items():
        if name.endswith("_cents"):
            lines.append(f"| {name} | {eur(value)} |")
    lines += [
        "",
        "Cash = allocated + unapplied; adjusted receivables = allocated + outstanding.",
        "Control differences must be zero. These are conservation checks, not performance KPIs.",
        "",
        f"Active matched payment events: {result.controls['matched_event_count']}",
        f"Unmatched positive-cash events: {result.controls['unmatched_event_count']}",
        f"Fully reversed events: {result.controls['reversed_event_count']}",
        f"Automatic allocation records: {len(result.allocations)}",
        f"Allocation releases: {len(result.releases)}",
        f"Manual-review items: {len(result.review_queue)}",
        "",
        "Payment classifications:",
    ]
    lines.extend(
        f"- {name}: {count}"
        for name, count in sorted(Counter(p.classification for p in result.payments).items())
    )
    lines += ["", "Exception counts (including informational outstanding-invoice records):"]
    lines.extend(f"- {name}: {count}" for name, count in result.exception_counts_by_reason.items())
    lines += ["", "Source/cutoff counts:"]
    lines.extend(f"- {name}: {count}" for name, count in result.source_counts.items())
    lines += [
        "",
        "Manual items remain unresolved; this snapshot is not a persisted ledger.",
        "Ground truth was not read. No database, dashboard or Excel reporting was used.",
        "",
    ]
    return "\n".join(lines)


def write_files(files: dict[str, bytes], target: Path) -> None:
    target = target.resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        existing = (
            {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
            if target.is_dir()
            else {}
        )
        if set(existing) == set(files) and all(
            existing[name].read_bytes() == raw for name, raw in files.items()
        ):
            return
        raise ValueError("Output differs from existing contents; choose a new output directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reconciliation-", dir=target.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        for name, raw in files.items():
            (stage / name).write_bytes(raw)
        if target.exists():
            target.rmdir()  # Verified empty; no recursive removal of existing results.
        os.replace(stage, target)


def export_result(result: ReconciliationResult, data: InputDataset, target: Path) -> None:
    write_files(
        {
            "reconciliation.json": canonical(result.model_dump(mode="json")),
            "review_queue.json": canonical(
                {
                    "synthetic": True,
                    "run_id": result.run.id,
                    "items": [e.model_dump(mode="json") for e in result.review_queue],
                }
            ),
            "source_provenance.jsonl": b"".join(canonical(asdict(p)) for p in data.provenance),
            "summary.md": summary(result).encode("utf-8"),
        },
        target,
    )
