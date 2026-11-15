# Licenses, data provenance and attribution

Original repository code, documentation and authored fictional examples/screenshots
are released under the [MIT License](../LICENSE). No company logos, real customer
records, externally sourced dataset or proprietary SAP material are included.
Generator fixtures are authored locally; fictional names and invalid-check-digit
DE00 tokens are not taken from a customer database. Dashboard captures show that
same generated data and application UI.

Dependencies are installed through Python packaging; their source/binaries are
not vendored in this repository. They retain their respective licenses and
copyright notices. The following records the installed metadata reviewed for the
local Phase 8 environment; it is not a substitute for notices shipped with each
resolved distribution, including transitive and wheel-bundled components.

| Direct runtime dependency | Reviewed version | Declared license | Upstream |
|---|---|---|---|
| Pydantic | 2.14.3 | MIT | [pydantic](https://github.com/pydantic/pydantic) |
| SQLAlchemy | 2.1.8 | MIT | [SQLAlchemy](https://www.sqlalchemy.org/) |
| pandas | 3.1.1 | BSD-3-Clause | [pandas](https://pandas.pydata.org/) |
| NumPy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [NumPy](https://numpy.org/) |
| openpyxl | 3.1.5 | MIT | [openpyxl](https://openpyxl.readthedocs.io/) |
| XlsxWriter | 3.3.1 | BSD-2-Clause | [XlsxWriter](https://github.com/jmcnamara/XlsxWriter) |
| Streamlit | 1.67.0 | Apache-2.0 | [Streamlit](https://streamlit.io/) |
| Plotly | 6.9.0 | MIT | [Plotly Python](https://plotly.com/python/) |
| tzdata | 2026.6 | Apache-2.0 | [Python tzdata](https://github.com/python/tzdata) |

Reviewed development tools: pytest 9.2.0 (MIT), Hypothesis 6.170.15 (MPL-2.0),
Ruff 0.17.5 (MIT), coverage 7.17.3 (Apache-2.0), pip-audit 2.10.1
(Apache Software License classifier), and build 1.6.1 (MIT). These unmodified
tools are optional development dependencies, not project code relicensed under MIT.
Python and SQLite retain the notices of their own distributions. GitHub Actions
are referenced upstream workflows, not copied dependencies.

No publication rights are asserted over third-party libraries, company marks or
the employer named in the project motivation. Review the current resolved package
licenses before separately redistributing dependencies or binaries. The release
wheel contains this project's package and license; downstream environments install
their own dependency distributions.
