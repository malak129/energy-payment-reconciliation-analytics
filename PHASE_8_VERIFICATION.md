# Phase 8 release verification — 15 November 2026

## Release status

**Published and verified:**
[malak129/energy-payment-reconciliation-analytics](https://github.com/malak129/energy-payment-reconciliation-analytics).
The repository is PUBLIC, its default branch is main, and all eight requested
topics are configured. Account `malak129` was verified through authenticated
GitHub CLI/API. The name was checked absent immediately before creation; the
local repository initially had no commits or remote. No remote content was
overwritten and no history was rewritten or force-pushed.

Verified implementation commit:
`dba6d7af8acb6dbbcdca0104a53e48ee7c5fa03a`.
[Actual GitHub Actions run 43756232832](https://github.com/malak129/energy-payment-reconciliation-analytics/actions/runs/43756232832)
completed successfully for that commit. A subsequent documentation-only commit
records these publication results and relocates the explanatory license policy;
the application/test/CI source is unchanged by that follow-up. Current main status
is available through the README's live workflow badge.

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

Remote CI results were read from GitHub, including its actual logs:

| GitHub-hosted job | Tests | Complete job |
|---|---|---|
| Windows / Python 3.12 | 250 passed in 86.64 s | SUCCESS |
| Ubuntu / Python 3.12 | 250 passed in 29.12 s | SUCCESS |
| Ubuntu / Python 3.11 | 250 passed in 31.34 s | SUCCESS |

Every job also passed installation, dependency compatibility, Ruff, documentation
links, wheel build and small deterministic financial/dashboard acceptance. These
are observed results, not an inference from local checks or workflow configuration.

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
`LICENSE`, `docs/LICENSING.md`, package metadata and MANIFEST adopt MIT and include
documentation/license in source distribution preparation. The build backend
minimum is setuptools 77 for the license-expression metadata syntax.
The explanatory license policy was moved from `LICENSE.md` to `docs/LICENSING.md`
after verifying GitHub initially presented it as a second, unidentified license.
The root `LICENSE` remains the sole standard MIT grant; no license terms changed.

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

`gh repo create` created the new public repository and pushed main successfully;
`gh repo edit` applied the requested description/topics. All 106 remote Git blobs
were compared with the reviewed initial commit and matched exactly. The README
was also inspected on the public GitHub page: headings/tables/commands display,
the genuine overview image loads at its original 1440×1000 size, and Mermaid
renders the implemented architecture without a parse error. The license API
recognizes the standard root MIT license. A local screenshot of the rendered
README is retained in ignored release evidence.

Published inventory: 44 package Python files, eight test files, six tool scripts,
34 Markdown files, seven screenshot JPEGs, three TOML files, one workflow YAML,
one source manifest, `.gitignore` and the MIT `LICENSE` (106 files total).
Useful original technical/phase reports are included as dated records.

Intentionally excluded: all generated data/oracles, the private primary SQLite
database, every backup/incident database, temporary financial exports, local
test/build/install/CI logs, virtual environments, credentials, `.env`/Streamlit
secrets, caches and distribution archives. The only committed binaries are the
seven authored synthetic dashboard screenshots, together under 1 MB. No external
financial data, company assets or personally identifying Git email was published.

Evidence was inspected before each push. The initial public implementation and
subsequent documentation updates use fast-forward history and GitHub no-reply
authorship. This report names the verified implementation commit and observed
CI run; the final delivery message identifies the latest documentation commit.

## Future updates

From a clean working tree, pull main, create a topic branch, make a scoped change,
run the documented checks and push the branch for review. Keep data/outputs,
credentials, databases and environments ignored. Do not force-push, rewrite old
financial snapshots, change ground truth to improve scores or silently replace
published evidence. Regenerate screenshots only from synthetic isolated examples.
The workflow runs again on pushes and pull requests; check its actual result
before presenting a change as verified.
