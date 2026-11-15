# Database schema and upgrades

The application reads TimescaleDB only. Generated telemetry lives in `tests/`
and is never copied into the API or ingestion image. Migrations seed building
and sensor-model registries; they do not insert sensor readings.

| Table | Purpose |
| --- | --- |
| `buildings` | Stable building IDs, unique names/slugs, active discovery flag |
| `sensor_models` | Supported model types, metric capabilities, planned quantities |
| `devices` | Unique DevEUI, building/model foreign keys, label and room |
| `readings` | Timestamped metric values, partitioned by time as a hypertable |
| `readings_hourly` | Continuous aggregate of hourly averages/minima/maxima |
| `schema_migrations` | Applied filenames, SHA-256 checksums and timestamps |

Devices are registered explicitly; incoming messages from unknown DevEUIs are
ignored. Planned quantities are separate from installed devices. The archived
Library record keeps its ID, devices and readings while active discovery uses
KEH, EOJ, ARK and SiS.

The migration runner applies each new SQL file in a transaction under a session
advisory lock. Failed files roll back and are not recorded. Applied migration
files must not change; add another numbered file for subsequent upgrades.
Back up the database before deployment using the existing README procedure.

Migration 0004 adds indexes for device/building and per-metric history lookups.
New records require a lowercase 16-character hexadecimal DevEUI, a nonblank
device label and metric, and a finite numeric reading. These checks are added
as `NOT VALID` so historical invalid records are preserved while new writes
are checked. Current/history queries exclude non-finite and future readings.
Existing foreign keys and retention policies remain in effect.

Timestamped uplinks are idempotent through the ingest service: a transaction
lock serializes a device's writes, and each timestamp/device/metric is inserted
only if absent. Historical duplicates are not removed. Direct database writers
must use the same convention. Uplinks without a network timestamp receive the
arrival time, so gateways should always include their original timestamp.

Raw readings have a 90-day retention policy. Hourly aggregates are retained
indefinitely and refreshed on an hourly schedule. The API uses read-only
transactions with a 15-second statement timeout; migrations and ingestion
use their own write connections. `/health` probes the database and returns
HTTP 503 if it cannot be reached.

Run `python tests/run_integration.py` to test initialization, upgrades,
ingestion, duplicate delivery, invalid data, aggregates and API responses in
a separate database and disposable Docker volumes. It never selects a
production database, and cleans up its own containers and volumes afterward.
