"""Connection policy, explicit transactions and tested versioned-schema bootstrap."""

import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from energy_reconciliation.persistence import schema as s
from energy_reconciliation.utilities.serialization import fingerprint


def utc_now():
    return datetime.now(UTC)


def schema_hash():
    definitions = [
        str(CreateTable(t).compile(dialect=sqlite.dialect())) for t in s.metadata.sorted_tables
    ]
    definitions += sorted(
        str(CreateIndex(i).compile(dialect=sqlite.dialect()))
        for t in s.metadata.tables.values()
        for i in t.indexes
    )
    return fingerprint(
        {"version": s.SCHEMA_VERSION, "ddl": definitions, "immutable": sorted(s.IMMUTABLE)}
    )


def trigger_sql(name, operation):
    return (
        f'CREATE TRIGGER "immutable_{name}_{operation}" '
        f'BEFORE {operation} ON "{name}" BEGIN '
        "SELECT RAISE(ABORT, 'immutable append-only table'); END"
    )


def validate_live_schema(connection):
    """Fail closed on structural drift, independently of the stored version stamp."""

    def normalized(sql):
        return re.sub(r"\s+", " ", sql).strip().rstrip(";")

    expected = {
        ("table", t.name): normalized(str(CreateTable(t).compile(dialect=sqlite.dialect())))
        for t in s.metadata.tables.values()
    }
    expected.update(
        {
            ("index", i.name): normalized(str(CreateIndex(i).compile(dialect=sqlite.dialect())))
            for t in s.metadata.tables.values()
            for i in t.indexes
        }
    )
    expected.update(
        {
            ("trigger", f"immutable_{name}_{operation}"): normalized(trigger_sql(name, operation))
            for name in s.IMMUTABLE
            for operation in ("UPDATE", "DELETE")
        }
    )
    actual = {
        (kind, name): normalized(sql)
        for kind, name, sql in connection.exec_driver_sql(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        )
    }
    if actual != expected:
        changed = sorted(
            f"{kind}:{name}"
            for kind, name in set(actual) | set(expected)
            if actual.get((kind, name)) != expected.get((kind, name))
        )
        raise ValueError("Live schema differs from versioned contract: " + ", ".join(changed[:8]))


class Database:
    def __init__(self, path: Path, clock=utc_now, *, read_only=False):
        self.path = Path(path).resolve()
        self.clock = clock
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise ValueError("Read-only database must already exist")
            self.engine = create_engine(
                "sqlite://",
                creator=lambda: sqlite3.connect(
                    self.path.as_uri() + "?mode=ro", uri=True, timeout=30
                ),
            )
        else:
            self.engine = create_engine(
                f"sqlite:///{self.path.as_posix()}", connect_args={"timeout": 30}
            )

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            if read_only:
                connection.execute("PRAGMA query_only=ON")

    @contextmanager
    def transaction(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN" if self.read_only else "BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def initialize(self):
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            tables = inspect(connection).get_table_names()
            if tables:
                if "schema_versions" not in tables:
                    raise ValueError("Refusing to initialize an unrelated database")
                if connection.exec_driver_sql(
                    "PRAGMA application_id"
                ).scalar_one() != s.APPLICATION_ID or set(tables) != set(s.metadata.tables):
                    raise ValueError("Database application marker/tables mismatch")
                version = connection.execute(select(s.schema_versions)).mappings().all()
                if (
                    len(version) != 1
                    or version[0]["version"] != s.SCHEMA_VERSION
                    or version[0]["schema_hash"] != schema_hash()
                ):
                    raise ValueError(
                        "Unsupported schema version/signature; explicit migration required"
                    )
                validate_live_schema(connection)
                return
            if self.read_only:
                raise ValueError("Database is empty; initialize, import and reconcile first")
            s.metadata.create_all(connection)
            connection.exec_driver_sql(f"PRAGMA application_id={s.APPLICATION_ID}")
            connection.execute(
                s.schema_versions.insert().values(
                    version=s.SCHEMA_VERSION,
                    schema_hash=schema_hash(),
                    applied_at=self.clock().isoformat(),
                )
            )
            for name in sorted(s.IMMUTABLE):
                for operation in ("UPDATE", "DELETE"):
                    connection.exec_driver_sql(trigger_sql(name, operation))

    def close(self):
        self.engine.dispose()

    def backup(self, target: Path):
        target = Path(target).resolve()
        if target.exists() or target == self.path:
            raise ValueError("Backup destination must be a new file")
        if not self.path.is_file():
            raise ValueError("Source database does not exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive reservation closes the check/create race; keep its handle during backup.
        with target.open("xb"):
            try:
                with (
                    closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as source,
                    closing(sqlite3.connect(target)) as destination,
                ):
                    source.execute("PRAGMA foreign_keys=ON")
                    destination.execute("PRAGMA foreign_keys=ON")
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise ValueError("Backup integrity check failed")
                    if destination.execute("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("Backup foreign-key check failed")
            except BaseException:
                # Keep failed artifacts for inspection; they cannot overwrite another backup.
                raise
        return target

    @classmethod
    def restore(cls, source: Path, target: Path):
        if not Path(source).is_file():
            raise ValueError("Backup source must exist")
        if Path(target).exists():
            raise ValueError("Restore target must not exist")
        original = cls(source, read_only=True)
        try:
            original.initialize()
            original.backup(target)
        finally:
            original.close()
        restored = cls(target)
        restored.initialize()
        return restored

    def reset(self, confirmation: str, backup_path: Path):
        if self.read_only:
            raise ValueError("A read-only database cannot be reset")
        if confirmation != "RESET-SYNTHETIC-DEMO":
            raise ValueError("Reset requires --confirm RESET-SYNTHETIC-DEMO")
        if not self.path.is_file():
            raise ValueError("Reset requires an existing application database")
        self.initialize()
        self.backup(backup_path)
        self.close()
        self.path.unlink()  # Exact named, verified application database; backup retained.
        self.initialize()
