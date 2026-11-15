# Phase 8 release verification — 15 November 2026

## Release status

Local release checks pass. Public repository creation/push and actual GitHub
Actions results will be recorded after publication; they are not yet claimed.
Target account `malak129` was verified through authenticated GitHub CLI/API.
The requested name `energy-payment-reconciliation-analytics` returned HTTP 404
before creation. The local repository initially had no commits or remote.

## Executed local results

| Check | Observed result |
|---|---|
| Full regression suite | **250 passed, 0 failed in 135.48 seconds**; all prior 249 cases retained |
| Ruff | All checks passed |
| Dependency compatibility | `pip check`: no broken requirements |
| Wheel | `energy_payment_reconciliation-0.1.0-py3-none-any.whl` built successfully |
| Fresh virtual environment | Created successfully; all runtime/dev dependencies installed from project metadata; doctor and pip check pass |
| Fresh installed CLI / acceptance | Console `--help` works; small financial/Excel/manual/dashboard acceptance PASS in the fresh environment |
| Small portable CI acceptance | PASS: 12 customers, 2 periods, rate 1; temporary inputs/databases |
| Full default portable acceptance | PASS: 500 customers, 12 periods, seed 42 |
| Independent synthetic evaluation | 6,904 correct automatic allocations; 0 incorrect/missing; 98 correct releases; no invoice/payment balance differences |
| Report controls / workbook | 26 PASS with zero differences; 12 worksheets; all saved monetary detail cells checked against report rows |
| Manual allocation/undo | Supported explicit synthetic target on a separate copy; all original controls restored |
| Duplicate import/rerun | Unique bank counts and selected snapshot unchanged |
| Dashboard | All seven real AppTest pages pass; all seven visited/captured in browser |
| Screenshots | Seven genuine 1440×1000 JPEG captures; visually reviewed; synthetic data/relative paths only |
| Primary / manifest / oracle | Original protected hashes unchanged |

Final staging review covers **106 files / 1,691,245 staged bytes** before this
verification-record update: 58 Python files, 34 Markdown documents, seven JPEGs,
three TOML files, one YAML workflow, one manifest and two extensionless files.
No forbidden paths or sensitive-pattern matches were found. All seven screenshots
have 1440×1000 dimensions and no EXIF metadata. All 48 relative document links and
anchors resolve. There was no prior committed history to inspect or rewrite.
The original personal Git email is not used for publication; commits use the
authenticated account's verified numeric-ID GitHub no-reply address.

Phase 7's coverage remains historical: 90.73% statements,
86.69% branches, 89.92% combined. Coverage was not remeasured for this documentation
release. Native Microsoft Excel opening/recalculation remains unverified.

## Delivered files and preserved behavior

README was rewritten around the payment-operations problem, conservative matching,
exact financial results, screenshots and a portable Windows quick start. New
guides are `docs/ARCHITECTURE.md`, `DEMO_GUIDE.md`, `FINANCIAL_CONTROLS.md`,
`TESTING.md`, `LIMITATIONS.md`, `PORTFOLIO_PRESENTATION.md`, `SCREENSHOTS.md`
and `THIRD_PARTY_NOTICES.md`. Existing technical and dated phase reports remain;
three machine-specific path prefixes were replaced with portable descriptions.

`PHASE_8_RELEASE_PLAN.md` records the initial audit and release sequence.
`tools/release_check.py` adds portable temporary-data acceptance using existing
services and safe-copy demonstrations. `tools/check_docs.py` validates relative
links, anchors and seven screenshot references locally and in CI.
`.github/workflows/ci.yml` configures
read-only-permission jobs on Ubuntu/Python 3.11 and 3.12 and Windows/Python 3.12,
with immutable pins for verified official checkout/setup-python releases.
`.gitignore` additionally excludes local secrets, logs and temporary backups.
`LICENSE`, `LICENSE.md`, package metadata and MANIFEST adopt MIT and include
documentation/license in source distribution preparation. The build backend
minimum is setuptools 77 for the license-expression metadata syntax.

One fresh-demo defect was found: the report demonstration checker assumed an
empty Excel table must materialize its reserved blank row as worksheet cells.
The checker now accepts either valid empty-table read-back shape. Its new
`test_fresh_baseline_safe_copy_demonstration` regression verifies the initially
empty Manual Decisions table, safe allocation/undo and unchanged input baseline.
No matching policy, monetary sign, schema, engine or financial service was changed.

## Financial evidence and safety boundaries

The default release baseline has net cash 215,688,500 cents, net allocated cash
206,799,184 cents, unapplied cash 8,889,316 cents, adjusted receivables
224,162,712 cents and outstanding receivables 17,363,528 cents. Both independent
conservation differences are zero. Evaluation is explicit and separate from
runtime reconciliation; intended relationships never authorize matches.

All 33 historical source-file hashes and the private primary are checked with the
existing read-only Phase 7 audit. The private primary SHA256 remains
`d6674a691b1d07880e90b86ade2ad554e29030bc179b2b0fb386957720608158`.
All generated release examples use new temporary locations or `data/portfolio*`.
Screenshots use a read-only working copy, not the private primary. README commands
generate a fresh baseline, export it, restore a distinct working copy and explicitly
bind Streamlit to loopback. No old database was reset or overwritten.

Original project code/documentation and authored synthetic examples/screenshots
use MIT. Runtime and development dependency metadata were reviewed; no third-party
source, binary, employer logo or external dataset is vendored. Full upstream
package notices remain with installed distributions. The project is independent,
AI-assisted, synthetic-only and does not claim affiliation, endorsement, SAP
integration, real-world matching accuracy or employment experience.

## Reproduction and evidence

Commands actually executed include the complete README generation/init/import/
reconcile/export/restore sequence; the screenshot server additionally used
`--server.port 8508 --read-only` on the working copy. All seven pages were captured
through the browser and the temporary viewport override was reset afterward.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m build --wheel
.\.venv\Scripts\python.exe tools/check_docs.py
.\.venv\Scripts\python.exe tools/release_check.py --customers 12 --billing-periods 2 --discrepancy-rate 1 --evidence outputs/phase8/small-release.json
.\.venv\Scripts\python.exe tools/release_check.py --evidence outputs/phase8/default-release.json
```

Local-only evidence is retained under ignored `outputs/phase8`: test/build logs,
fresh installation log, protected-file hashes and acceptance JSON. Public release
checks reproduce from generated temporary inputs; original incident/backup artifacts
are not included in Git. Detailed limitations are in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Publication record

Pending final reviewed staging and creation of the new repository. No publication
or successful remote CI result is asserted by this pre-publication record.

## Future updates

From a clean working tree, pull main, create a topic branch, make a scoped change,
run the documented checks and push the branch for review. Keep data/outputs,
credentials, databases and environments ignored. Do not force-push, rewrite old
financial snapshots, change ground truth to improve scores or silently replace
published evidence. Regenerate screenshots only from synthetic isolated examples.
The workflow runs again on pushes and pull requests; check its actual result
before presenting a change as verified.
