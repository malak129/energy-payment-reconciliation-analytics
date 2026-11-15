# Phase 7 measured performance

Executed 15 November 2026, Windows 11 build 26200, Python 3.12.14,
Intel Core i5-1235U (12 logical CPUs), 16,890,912,768 bytes physical RAM.
About 105.5 GB disk space was available at baseline. Measurements use
`time.perf_counter`; these are single observed runs, not latency guarantees.
The final acceptance run overlapped the coverage-enabled regression suite, so
CPU/disk contention affects the results. No extrapolated throughput is claimed.

| Stage | 500 customers / 12 periods (seconds) | 750 customers / 12 periods (seconds) |
|---|---:|---:|
| Generate in-memory dataset | 1.1601 | 5.1231 |
| Export source bundle | 1.4305 | 6.0044 |
| Import into new SQLite database | 12.2316 | 30.6560 |
| Reconcile and persist baseline | 5.4374 | 20.4239 |

| Default-size workflow stage | Seconds |
|---|---:|
| Explicit manual allocation | 6.8333 |
| Explicit reversal | 10.3057 |
| Full report query | 3.9381 |
| Excel export | 8.3336 |
| Exception CSV export | 0.0358 |
| Indexed payment ID query | 0.0001129 |
| First dashboard AppTest render | 4.3944 |
| Duplicate source import | 5.5700 |
| Reconciliation rerun preserving manual history | 11.3195 |
| Separate HTTP server startup to health response | 1.6746 |

The HTTP probe used a newly generated isolated database, explicit loopback port
8507 and read-only mode. It received `ok` at `/_stcore/health` and terminated only
its own child process. HTTP health startup does not measure browser rendering;
the AppTest measurement exercises the real application and service interfaces.
All seven pages subsequently rendered without exceptions. Browser network/render
latency was not benchmarked.

The 500-customer source contains 7,296 unique bank events and five byte-identical
duplicate file receipts. The larger source contains 10,945 unique bank events and
five duplicate receipts. Both reconciliations passed nonnegative entity balances.
The smaller workflow also completed allocation, reversal, exports, all pages,
duplicate import and stable rerun. The larger test measured generation/import/
reconciliation only; it did not benchmark a larger Excel workbook or every page.

Windows process peak working set was **1,137,283,072 bytes** (about 1.06 GiB) across
both datasets, workbook loading and AppTest. It includes native-library memory and
retained objects/caches; it is not per-stage memory or a memory-leak assessment.
An earlier diagnostic attempt used expensive tracemalloc instrumentation and did
not complete the harness; those timings are excluded. Subsequent harness-only
contract and 64-bit memory API errors were corrected before this successful run.

Raw evidence: `outputs/phase7/acceptance.json`, its run-specific `progress.json`,
and `outputs/phase7/server-probe.json`. Successful acceptance directory:
`outputs/phase7/acceptance-20261115T182356`. Earlier isolated attempts are retained
for inspection and are not reported as successful acceptance runs.

Reproduce from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe tools/phase7_acceptance.py
.\.venv\Scripts\python.exe tools/phase7_server_probe.py
```

Each acceptance invocation creates a new timestamped directory. It never resets,
restores over, or allocates against the primary database. The server probe expects
port 8507 to be free and fails if its child cannot start; it does not stop an
unrelated server. Timings will vary with cache warmth, dataset size and concurrent
activity. Current bounds are suitable for the measured local portfolio workload;
no production-scale capacity claim is made.
