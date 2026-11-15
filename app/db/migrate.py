"""Apply ordered SQL migrations to an existing database without replacing data."""

import hashlib
import logging
import os
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).with_name("migrations")
MIGRATION_LOCK = 7262612026


def migrate(db: psycopg.Connection, directory: Path = MIGRATIONS) -> None:
    # One session owns the lock across per-file transactions. A failed file is
    # rolled back and never recorded as applied.
    db.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "filename TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        for path in sorted(directory.glob("*.sql")):
            source = path.read_bytes()
            checksum = hashlib.sha256(source).hexdigest()
            row = db.execute(
                "SELECT checksum FROM schema_migrations WHERE filename = %s", (path.name,)
            ).fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise RuntimeError(f"Previously applied migration changed: {path.name}")
                continue
            with db.transaction():
                db.execute(source.decode("utf-8-sig"), prepare=False)
                db.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
            log.info("Applied %s", path.name)
    finally:
        db.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        migrate(db)


if __name__ == "__main__":
    main()
