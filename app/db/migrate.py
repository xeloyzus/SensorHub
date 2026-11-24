"""Install/check the complete baseline, with an explicit application-only reset."""

import argparse
import hashlib
import logging
import os
from pathlib import Path
import time

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).with_name("migrations")
MIGRATION_LOCK = 7262612026
READ_TABLES = (
    "buildings", "sensor_models", "metrics", "sensor_model_metrics", "devices",
    "readings", "readings_hourly",
)
RUNTIME_ROLES = {
    "sensorhub_api": "API_DB_PASSWORD",
    "sensorhub_ingest": "INGEST_DB_PASSWORD",
    "grafana_reader": "GRAFANA_DB_PASSWORD",
}


def configure_roles(db: psycopg.Connection, passwords: dict[str, str]) -> None:
    """The owner runs DDL; API/Grafana can read and ingest can only append."""
    database = sql.Identifier(db.execute("SELECT current_database()").fetchone()[0])
    owner = sql.Identifier(db.execute("SELECT current_user").fetchone()[0])
    for name, password in passwords.items():
        role = sql.Identifier(name)
        exists = db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
        verb = "ALTER ROLE" if exists else "CREATE ROLE"
        db.execute(sql.SQL(
            verb + " {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(role, sql.Literal(password)))
        db.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        db.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role))
        # Older releases automatically granted Grafana every future table.
        db.execute(sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public REVOKE ALL ON TABLES FROM {}"
        ).format(owner, role))
        # Remove old grants before applying the allowlist. Future tables do not
        # automatically become readable by runtime accounts.
        db.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
        db.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role))
        tables = READ_TABLES if name != "sensorhub_ingest" else (
            "devices", "sensor_models", "metrics", "sensor_model_metrics",
        )
        db.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier("public", table) for table in tables), role,
        ))
        if name == "sensorhub_ingest":
            db.execute(sql.SQL(
                "GRANT INSERT (time, device_id, metric, value) ON public.readings TO {}"
            ).format(role))
            # PostgreSQL requires SELECT on the ON CONFLICT inference columns.
            db.execute(sql.SQL(
                "GRANT SELECT (device_id, metric, time) ON public.readings TO {}"
            ).format(role))
        db.execute(sql.SQL("ALTER ROLE {} SET search_path TO public").format(role))
        if name != "sensorhub_ingest":
            db.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only TO on").format(role))
        db.execute(sql.SQL("ALTER ROLE {} SET statement_timeout TO '15s'").format(role))


def reset_application(db: psycopg.Connection) -> None:
    """Drop only known application objects, transactionally and without CASCADE.

    Unrelated dependencies cause a rollback instead of being silently removed.
    TimescaleDB removes the hypertable's chunks and scheduled jobs.
    ChirpStack lives in another database and is never touched.
    """
    db.execute("DROP MATERIALIZED VIEW IF EXISTS public.readings_hourly")
    for name in ("readings", "devices", "sensor_model_metrics", "metrics", "sensor_models", "buildings", "schema_migrations"):
        db.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier("public", name)))
    for name in ("validate_reading", "protect_device_identity"):
        db.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(sql.Identifier("public", name)))


def install(db: psycopg.Connection, sources: dict[str, str], passwords: dict[str, str], reset: bool) -> None:
    # DDL, seed data, the ledger, and runtime grants commit as one unit.
    with db.transaction():
        db.execute("SET LOCAL search_path TO public")
        if reset:
            reset_application(db)
        ledger = db.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
        if ledger:
            applied = dict(db.execute("SELECT filename, checksum FROM public.schema_migrations").fetchall())
            if set(applied) - sources.keys():
                raise RuntimeError(
                    "Legacy/unknown database migrations detected. This release uses a fresh baseline. "
                    "Run bash run.sh --reset-database to discard the application data and rebuild it."
                )
        else:
            applied = {}
            if db.execute(
                "SELECT name FROM unnest(%s::text[]) AS name "
                "WHERE to_regclass('public.' || name) IS NOT NULL LIMIT 1", (list(READ_TABLES),)
            ).fetchone():
                raise RuntimeError("Unversioned database detected; use bash run.sh --reset-database")
        db.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
            "filename TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        for name, source in sources.items():
            checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if name in applied:
                if applied[name] != checksum:
                    raise RuntimeError(f"Previously applied migration changed: {name}")
                continue
            db.execute(source, prepare=False)
            db.execute("INSERT INTO public.schema_migrations (filename, checksum) VALUES (%s, %s)", (name, checksum))
            log.info("Applied %s", name)
        configure_roles(db, passwords)


def migrate(db: psycopg.Connection, directory: Path = MIGRATIONS, *, reset: bool = False) -> None:
    if not db.autocommit:
        raise RuntimeError("The migration connection must use autocommit=True")
    passwords = {name: os.environ.get(key, "") for name, key in RUNTIME_ROLES.items()}
    missing = [RUNTIME_ROLES[name] for name, value in passwords.items() if not value]
    if missing:
        raise RuntimeError("Required database runtime passwords are missing: " + ", ".join(missing))
    # Normalize checkout line endings so Windows/Linux compute identical checksums.
    sources = {
        path.name: path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        for path in sorted(directory.glob("*.sql"))
    }
    if not sources:
        raise RuntimeError("No database migrations were found")
    db.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
    try:
        # Timescale background policies can briefly contend with reset DDL.
        # Retry only transaction rollback failures; SQL/integrity errors remain
        # actionable failures. The session-level installer lock stays held.
        for attempt in range(3):
            try:
                install(db, sources, passwords, reset)
                break
            except (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure):
                if attempt == 2:
                    raise
                log.warning("Retrying database transaction after lock contention")
                time.sleep(0.5 * (attempt + 1))
    finally:
        db.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Discard and rebuild application tables; preserves ChirpStack")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        migrate(db, reset=args.reset)


if __name__ == "__main__":
    main()
