"""Real TimescaleDB contract tests, run before the MQTT/API integration smoke test.

Creates/drops only a uniquely named test database on the isolated test server.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.db.migrate import MIGRATIONS, migrate

INSERT = "INSERT INTO public.readings (time, device_id, metric, value) VALUES (%s, %s, %s, %s)"


def rejected(db, statement, parameters=(), error=psycopg.IntegrityError):
    try:
        with db.transaction():
            db.execute(statement, parameters)
    except error:
        return
    raise AssertionError(f"Database accepted forbidden operation: {statement}")


def verify_registry_upgrade(db):
    with TemporaryDirectory() as directory:
        baseline = MIGRATIONS / "0001_baseline.sql"
        (Path(directory) / baseline.name).write_text(baseline.read_text())
        migrate(db, Path(directory))
    targets = ("24e124725f517900", "24e124725f517844", "24e124725f515337")
    identities = dict(db.execute("SELECT eui,id FROM devices WHERE eui=ANY(%s)", (list(targets),)))
    device = identities[targets[-1]]
    assert db.execute(
        "SELECT b.slug,d.label,d.room FROM devices d JOIN buildings b ON b.id=d.building_id WHERE d.id=%s",
        (device,),
    ).fetchone() == ("kjolv-egelands-hus", "AM103-KEH-Utenfor", "Utenfor")
    now = datetime.now(timezone.utc)
    db.execute(INSERT, (now, device, "temperature", 22))
    migrate(db)
    rows = db.execute(
        "SELECT d.eui,d.id,b.slug,d.label,d.room FROM devices d JOIN buildings b ON b.id=d.building_id "
        "WHERE d.eui=ANY(%s) ORDER BY d.eui", (list(targets),)
    ).fetchall()
    assert {eui: identity for eui, identity, *_ in rows} == identities
    assert all(row[2] == "sis" for row in rows)
    assert db.execute("SELECT count(*) FROM devices").fetchone()[0] == 12
    assert {row[3] for row in rows} == {
        "AM103-SiS-Styrkesal", "AM103-SiS-Functional-Fitness", "AM103-SiS-Gruppetimesal",
    }
    assert db.execute("SELECT value FROM readings WHERE device_id=%s", (device,)).fetchone()[0] == 22
    db.execute("DELETE FROM readings WHERE device_id=%s", (device,))
    print("PASS: SiS registry upgrade preserves all three device IDs and existing readings", flush=True)


def verify_baseline(db, url):
    migrate(db)
    assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(list(MIGRATIONS.glob("*.sql")))
    assert db.execute("SELECT count(*) FROM devices").fetchone()[0] == 12
    assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 0
    assert not db.execute(
        "SELECT 1 FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated"
    ).fetchall()
    assert db.execute("SELECT count(*) FROM sensor_model_metrics").fetchone()[0] == 21
    # Rerunning never re-seeds over administrative edits.
    device = db.execute("UPDATE devices SET label='Edited label' WHERE id=1 RETURNING id").fetchone()[0]
    migrate(db)
    assert db.execute("SELECT label FROM devices WHERE id=%s", (device,)).fetchone()[0] == "Edited label"
    # Undo the automatic future-table grants left by the pre-baseline migrator.
    db.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader")
    migrate(db)
    db.execute("CREATE TABLE private_future_table (id integer)")
    assert not db.execute("SELECT has_table_privilege('grafana_reader', 'private_future_table', 'SELECT')").fetchone()[0]
    now = datetime.now(timezone.utc)
    db.execute(INSERT, (now, device, "co2", 700))
    rejected(db, INSERT, (now, device, "co2", 800), psycopg.errors.UniqueViolation)
    for metric, value in (("co2", float("nan")), ("co2", float("inf")),
                          ("co2", float("-inf")), ("humidity", 101),
                          ("battery", -1), ("temperature", -274)):
        rejected(db, INSERT, (now, device, metric, value), psycopg.errors.CheckViolation)
    for metric in ("temperture", "current_1", "", "CO2"):
        rejected(db, INSERT, (now, device, metric, 1), psycopg.errors.ForeignKeyViolation)
    rejected(db, INSERT, (now, 999999, "co2", 700), psycopg.errors.ForeignKeyViolation)
    for timestamp in (now-timedelta(days=90), now+timedelta(minutes=6)):
        rejected(db, INSERT, (timestamp, device, "co2", 700), psycopg.errors.CheckViolation)
    rejected(db, "UPDATE devices SET eui='0000000000000000' WHERE id=%s", (device,))
    rejected(db, "UPDATE devices SET type='am107' WHERE id=%s", (device,))
    rejected(db, "DELETE FROM devices WHERE id=%s", (device,))
    building = db.execute("SELECT building_id FROM devices WHERE id=%s", (device,)).fetchone()[0]
    rejected(db, "DELETE FROM buildings WHERE id=%s", (building,))
    db.execute("UPDATE devices SET is_active=FALSE WHERE id=%s", (device,))
    rejected(db, INSERT, (now+timedelta(seconds=1), device, "co2", 710))
    assert db.execute("SELECT value FROM readings WHERE device_id=%s", (device,)).fetchone()[0] == 700
    db.execute("UPDATE devices SET is_active=TRUE WHERE id=%s", (device,))
    print("PASS: complete baseline, idempotent startup, identity, keys, capabilities, units/ranges, retirement", flush=True)

    # Two actual ingestion connections race on the same measurement, exactly as
    # live delivery and buffered replay can do. The first committed value wins.
    writer_url = make_conninfo(url, user="sensorhub_ingest", password=os.environ["INGEST_DB_PASSWORD"])
    target = (now+timedelta(seconds=2), device, "co2", 720)
    def writer(_):
        with psycopg.connect(writer_url) as connection:
            connection.execute(INSERT + " ON CONFLICT (device_id, metric, time) DO NOTHING", target)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(writer, range(2)))
    assert db.execute("SELECT count(*) FROM readings WHERE device_id=%s AND time=%s", (device, target[0])).fetchone()[0] == 1
    with psycopg.connect(writer_url, autocommit=True) as connection:
        rejected(connection, "SELECT value FROM readings", error=psycopg.errors.InsufficientPrivilege)
        rejected(connection, "UPDATE readings SET value=0", error=psycopg.errors.InsufficientPrivilege)
        rejected(connection, "DELETE FROM readings", error=psycopg.errors.InsufficientPrivilege)
        rejected(connection, "UPDATE devices SET label='bad'", error=psycopg.errors.InsufficientPrivilege)
        rejected(connection, "SELECT * FROM schema_migrations", error=psycopg.errors.InsufficientPrivilege)
        rejected(connection, "CREATE TABLE forbidden (id integer)", error=psycopg.errors.InsufficientPrivilege)
    for role, key in (("sensorhub_api", "API_DB_PASSWORD"), ("grafana_reader", "GRAFANA_DB_PASSWORD")):
        with psycopg.connect(make_conninfo(url, user=role, password=os.environ[key]), autocommit=True) as connection:
            assert connection.execute("SELECT count(*) FROM readings").fetchone()[0] == 2
            # Even disabling the default transaction setting cannot grant write access.
            connection.execute("SET default_transaction_read_only=off")
            rejected(connection, INSERT, (now, device, "temperature", 22), psycopg.errors.InsufficientPrivilege)
            rejected(connection, "UPDATE devices SET label='bad'", error=psycopg.errors.InsufficientPrivilege)
            rejected(connection, "SELECT * FROM schema_migrations", error=psycopg.errors.InsufficientPrivilege)
    print("PASS: concurrent ingestion/replay deduplicates and runtime privileges enforce least access", flush=True)

    # Late data is materialized, and sum/count support weighted higher rollups.
    old_time = now - timedelta(days=7, hours=2)
    db.execute(INSERT, (old_time, device, "co2", 600))
    db.execute(INSERT, (old_time+timedelta(seconds=1), device, "co2", 800))
    db.execute("CALL refresh_continuous_aggregate('readings_hourly', %s::timestamptz, %s::timestamptz)",
               (old_time-timedelta(hours=1), old_time+timedelta(hours=2)))
    summary = db.execute("SELECT sample_count, sum, avg, min, max FROM readings_hourly WHERE device_id=%s AND metric='co2'", (device,)).fetchone()
    assert summary == (2, 1400, 700, 600, 800), summary
    policy = db.execute("SELECT config->>'start_offset' FROM timescaledb_information.jobs WHERE proc_name='policy_refresh_continuous_aggregate'").fetchone()
    assert policy and "89" in policy[0], policy
    print("PASS: late readings aggregate with counts/sums and a refresh window inside raw retention", flush=True)


def verify_migration_safety(db):
    source = (MIGRATIONS / "0001_baseline.sql").read_text()
    with TemporaryDirectory() as directory:
        for migration in MIGRATIONS.glob("*.sql"):
            (Path(directory) / migration.name).write_text(migration.read_text())
        path = Path(directory) / "0001_baseline.sql"
        path.write_bytes(source.replace("\n", "\r\n").encode())
        migrate(db, Path(directory))  # Same checksum across Windows/Linux.
        path.write_text(source + "\n-- changed migration\n")
        try:
            migrate(db, Path(directory))
        except RuntimeError as error:
            assert "changed" in str(error)
        else:
            raise AssertionError("Changed migration was accepted")
        path.write_text(source + "\nSELECT 'intentional-test-failure'::integer;\n")
        try:
            migrate(db, Path(directory), reset=True)
        except psycopg.errors.InvalidTextRepresentation:
            pass
        else:
            raise AssertionError("Expected baseline installation to fail")
        assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 4
        assert db.execute("SELECT label FROM devices WHERE id=1").fetchone()[0] == "Edited label"
    db.execute("CREATE VIEW external_dependency AS SELECT * FROM readings")
    try:
        migrate(db, reset=True)
    except psycopg.errors.DependentObjectsStillExist:
        pass
    else:
        raise AssertionError("Reset silently removed an external dependent view")
    assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 4
    db.execute("DROP VIEW external_dependency")
    # An old ledger must never be mistaken for the consolidated baseline.
    db.execute("UPDATE schema_migrations SET filename='0001_init.sql' WHERE filename='0001_baseline.sql'")
    try:
        migrate(db)
    except RuntimeError as error:
        assert "--reset-database" in str(error)
    else:
        raise AssertionError("Legacy schema accepted without explicit reset")
    assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 4
    db.execute("CREATE TABLE unrelated_sentinel (id integer PRIMARY KEY)")
    db.execute("INSERT INTO unrelated_sentinel VALUES (123)")
    migrate(db, reset=True)
    assert db.execute("SELECT count(*) FROM devices").fetchone()[0] == 12
    assert db.execute("SELECT count(*) FROM readings").fetchone()[0] == 0
    assert db.execute("SELECT id FROM unrelated_sentinel").fetchone()[0] == 123
    migrate(db)
    print("PASS: checksum enforcement, legacy refusal, transactional reset/rollback, unrelated objects preserved", flush=True)


def main():
    admin_url = os.environ["ADMIN_DATABASE_URL"]
    name = "sensorhub_schema_test_" + uuid.uuid4().hex[:12]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        if admin.execute("SELECT current_database()").fetchone()[0] != "sensorhub_integration":
            raise RuntimeError("Refusing to run database design tests outside the integration server")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            url = make_conninfo(admin_url, dbname=name)
            with psycopg.connect(url, autocommit=True) as db:
                verify_registry_upgrade(db)
                verify_baseline(db, url)
                verify_migration_safety(db)
        finally:
            # Exact name generated above; never a user database.
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


if __name__ == "__main__":
    main()
