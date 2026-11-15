# Phase 7 local security review

This is a synthetic, single-user local demonstration. It has no authenticated
operator identity, role separation, encryption, tamper-proof audit storage, hosted
deployment hardening or production security certification. Actor strings are labels.

## Findings and safeguards

Database reads/writes use SQLAlchemy parameters for record values. The explicit SQL
metacharacter case-ID probe returns no record and leaves financial state unchanged.
Dynamic trigger/index names come from internal metadata or SQLite introspection,
not interpolated user search values. Dashboard searches filter projections.

Immutable-source and historical tables have UPDATE/DELETE triggers, foreign keys
are enabled per connection, and financial workflows use immediate transactions,
revision checks and idempotency keys. Phase 7 adds live DDL verification; a matching
version stamp alone no longer suffices. This is structural validation, not proof
against a malicious filesystem owner. Such an owner can replace code and hashes.

Backup creation now reserves destinations exclusively, restore validates without
initializing its source, and read-only reset fails before deletion. CLI reset still
requires the exact confirmation token and a preserved backup. Explicit user-selected
database/export paths are supported; there is no mandatory workspace path jail.
Generated report names use validated run identities, export publication is exclusive,
and existing outputs are refused. Filesystem identity protects pending confirmation
against ordinary same-path replacement. It is not an adversarial OS-level lock:
the trusted local filesystem assumption still applies between checks and opening.

CSV exports now escape formula prefixes after leading whitespace and initial LF,
CR or TAB. Monetary numbers retain numeric types; workbook text is written as text,
with automatic URL/formula interpretation disabled by the exporter. Exported CSV
should still be treated as untrusted if edited outside the application.

The repository's `.streamlit/config.toml` defaults to 127.0.0.1 and disables usage
telemetry. Configuration is read relative to the project working directory; always
launch from the repository root and retain explicit `--server.address=127.0.0.1`.
An explicit command/environment override can broaden access. Do not use tunnelling,
public hosting or real personal data. Loopback does not authenticate other local
users/processes. Seven AppTest pages and inherited-argument demo routing tests run
against isolated databases; the primary digest is checked independently.

## Dependencies, secrets and privacy

`pip-audit --local` initially flagged pip 25.0.1. The virtual environment installer
was upgraded to pip 26.3. Re-audit reports no known vulnerabilities for auditable
installed distributions. The unpublished editable project is skipped because it is
absent from PyPI; source review/tests cover application code. Evidence:
`outputs/phase7/dependencies.json` and `dependencies-final.json`. This is a point-in-time
advisory scan, not a guarantee against undisclosed vulnerabilities or supply-chain
compromise. Dependency compatibility is also checked with `pip check`.

A repository source/config/documentation scan for common private keys, access-key
and token patterns found no matches. This limited pattern scan is not exhaustive
secret detection. Data/output directories and the virtual environment were excluded
from that scan and are ignored by Git. No real credentials are needed. Raw audited
customers carry the Synthetic prefix, accounts use deliberately invalid-check-digit
DE00 demo IBANs, and source identifiers are synthetic. Application logs are local;
review/export audit details can include local paths and fictional financial data.
Do not substitute real bank exports or real actor identities.

Expected input/SQL errors are displayed through controlled dashboard errors; failing
transactions retain rejected-attempt audit events without partially committing money.
Test fixture/harness failures are separately documented and do not indicate user
approval of a financial operation. No primary database mutation was authorized or
performed during Phase 7. No external message, upload or publication occurred.

## Residual limitations

SQLite backups are local, not encrypted or off-device. No multi-host concurrency or
resource exhaustion protection is claimed. Strict DDL comparison may require an
explicit compatibility/migration review when SQLAlchemy changes emitted DDL. Keep
the validated dependency environment for the demonstration. Native Excel recalculation
was attempted but remains unverified. Cross-date incompatible neutralization now
fails safely and requires an explicit future reviewed rebase design.
