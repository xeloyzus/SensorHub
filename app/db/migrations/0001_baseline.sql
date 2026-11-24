-- Complete application schema. This baseline replaces the pre-baseline migrations.
-- Existing installations require the explicit reset documented in database-schema.md.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE buildings (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name = btrim(name) AND name <> ''),
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sensor_models (
    type TEXT PRIMARY KEY CHECK (type ~ '^[a-z][a-z0-9_]*$'),
    name TEXT NOT NULL UNIQUE CHECK (name = btrim(name) AND name <> ''),
    planned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (planned_quantity >= 0)
);

-- Values are stored in one canonical unit per metric. No arrays or free-form keys.
CREATE TABLE metrics (
    metric TEXT PRIMARY KEY CHECK (metric ~ '^[a-z][a-z0-9_]*$'),
    name TEXT NOT NULL CHECK (name = btrim(name) AND name <> ''),
    unit TEXT NOT NULL CHECK (unit = btrim(unit) AND unit <> ''),
    minimum DOUBLE PRECISION,
    maximum DOUBLE PRECISION,
    kind TEXT NOT NULL DEFAULT 'gauge' CHECK (kind IN ('gauge', 'counter')),
    CHECK (minimum IS NULL OR (minimum > '-Infinity'::float8 AND minimum < 'Infinity'::float8)),
    CHECK (maximum IS NULL OR (maximum > '-Infinity'::float8 AND maximum < 'Infinity'::float8)),
    CHECK (minimum IS NULL OR maximum IS NULL OR minimum <= maximum)
);

CREATE TABLE sensor_model_metrics (
    model_type TEXT NOT NULL REFERENCES sensor_models(type) ON DELETE RESTRICT,
    metric TEXT NOT NULL REFERENCES metrics(metric) ON DELETE RESTRICT,
    display_order SMALLINT NOT NULL CHECK (display_order >= 0),
    PRIMARY KEY (model_type, metric),
    UNIQUE (model_type, display_order)
);
CREATE INDEX sensor_model_metrics_metric_idx ON sensor_model_metrics(metric);

CREATE TABLE devices (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eui TEXT NOT NULL UNIQUE CHECK (eui ~ '^[0-9a-f]{16}$'),
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE RESTRICT,
    type TEXT NOT NULL REFERENCES sensor_models(type) ON DELETE RESTRICT,
    label TEXT NOT NULL CHECK (label = btrim(label) AND label <> ''),
    room TEXT CHECK (room IS NULL OR (room = btrim(room) AND room <> '')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX devices_building_idx ON devices(building_id);
CREATE INDEX devices_type_idx ON devices(type);

CREATE TABLE readings (
    time TIMESTAMPTZ NOT NULL,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
    metric TEXT NOT NULL REFERENCES metrics(metric) ON DELETE RESTRICT,
    value DOUBLE PRECISION NOT NULL
        CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
    received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (device_id, metric, time)
);
SELECT create_hypertable('readings', 'time', chunk_time_interval => INTERVAL '7 days',
    create_default_indexes => FALSE);
-- The primary key serves device/metric/latest queries; these serve device-wide
-- and metric/time-range queries without duplicating that index.
CREATE INDEX readings_device_time_idx ON readings(device_id, time DESC);
CREATE INDEX readings_metric_time_idx ON readings(metric, time DESC);
CREATE INDEX readings_time_idx ON readings(time DESC);

-- A reading belongs to a registered, active device and a supported model metric.
-- Cross-table rules use a trigger, not a CHECK referencing another table.
CREATE FUNCTION validate_reading() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    lower_bound DOUBLE PRECISION;
    upper_bound DOUBLE PRECISION;
BEGIN
    SELECT m.minimum, m.maximum INTO lower_bound, upper_bound
      FROM public.devices d
      JOIN public.sensor_model_metrics sm ON sm.model_type = d.type AND sm.metric = NEW.metric
      JOIN public.metrics m ON m.metric = sm.metric
     WHERE d.id = NEW.device_id AND d.is_active
     FOR SHARE OF d, sm, m;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Inactive/unknown device or unsupported metric'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.value < lower_bound OR NEW.value > upper_bound THEN
        RAISE EXCEPTION 'Reading outside canonical metric range' USING ERRCODE = '23514';
    END IF;
    -- Allow a full day for bucket alignment and scheduling before a late
    -- sample falls outside the aggregate's 89-day refresh window.
    -- These clock-dependent rules must not be CHECK constraints.
    IF NEW.time < statement_timestamp() - INTERVAL '88 days'
       OR NEW.time > statement_timestamp() + INTERVAL '5 minutes' THEN
        RAISE EXCEPTION 'Reading timestamp outside the ingestion window' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER readings_validate BEFORE INSERT OR UPDATE ON readings
    FOR EACH ROW EXECUTE FUNCTION validate_reading();

-- DevEUI and hardware model identify physical hardware. Retire it rather than
-- relabelling its identity and silently reinterpreting its historical metrics.
CREATE FUNCTION protect_device_identity() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Retire devices with is_active = FALSE; device identity must survive raw-data retention'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.eui IS DISTINCT FROM OLD.eui OR NEW.type IS DISTINCT FROM OLD.type THEN
        RAISE EXCEPTION 'Device EUI and model are immutable; register another device'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER devices_identity BEFORE UPDATE OR DELETE ON devices
    FOR EACH ROW EXECUTE FUNCTION protect_device_identity();

CREATE MATERIALIZED VIEW readings_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket, device_id, metric,
       count(*) AS sample_count, sum(value) AS sum,
       avg(value) AS avg, min(value) AS min, max(value) AS max
  FROM readings
 GROUP BY bucket, device_id, metric
WITH NO DATA;
-- Raw data lives at least 90 days (retention drops complete chunks). Refresh
-- all accepted late arrivals while staying inside that retention boundary.
SELECT add_continuous_aggregate_policy('readings_hourly',
    start_offset => INTERVAL '89 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
SELECT add_retention_policy('readings', INTERVAL '90 days');

INSERT INTO metrics (metric, name, unit, minimum, maximum, kind) VALUES
    ('battery', 'Battery level', '%', 0, 100, 'gauge'),
    ('temperature', 'Temperature', 'degC', -273.15, NULL, 'gauge'),
    ('humidity', 'Relative humidity', '%RH', 0, 100, 'gauge'),
    ('co2', 'Carbon dioxide', 'ppm', 0, NULL, 'gauge'),
    ('activity', 'PIR activity', 'count', 0, NULL, 'gauge'),
    ('illumination', 'Illuminance', 'lux', 0, NULL, 'gauge'),
    ('infrared_and_visible', 'Infrared and visible light', 'count', 0, NULL, 'gauge'),
    ('infrared', 'Infrared light', 'count', 0, NULL, 'gauge'),
    ('tvoc', 'Total volatile organic compounds', 'ppb', 0, NULL, 'gauge'),
    ('pressure', 'Barometric pressure', 'hPa', 0, NULL, 'gauge'),
    ('current_1', 'Phase 1 current', 'A', 0, NULL, 'gauge'),
    ('current_2', 'Phase 2 current', 'A', 0, NULL, 'gauge'),
    ('current_3', 'Phase 3 current', 'A', 0, NULL, 'gauge'),
    ('total_1', 'Phase 1 accumulated current', 'Ah', 0, NULL, 'counter'),
    ('total_2', 'Phase 2 accumulated current', 'Ah', 0, NULL, 'counter'),
    ('total_3', 'Phase 3 accumulated current', 'Ah', 0, NULL, 'counter');

INSERT INTO sensor_models (type, name, planned_quantity) VALUES
    ('am103', 'Milesight AM103', 12),
    ('am107', 'Milesight AM107', 0),
    ('ct305', 'Milesight CT305', 0);

INSERT INTO sensor_model_metrics (model_type, metric, display_order) VALUES
    ('am103', 'battery', 0), ('am103', 'temperature', 1),
    ('am103', 'humidity', 2), ('am103', 'co2', 3),
    ('am107', 'battery', 0), ('am107', 'temperature', 1),
    ('am107', 'humidity', 2), ('am107', 'activity', 3),
    ('am107', 'illumination', 4), ('am107', 'infrared_and_visible', 5),
    ('am107', 'infrared', 6), ('am107', 'co2', 7),
    ('am107', 'tvoc', 8), ('am107', 'pressure', 9),
    ('ct305', 'current_1', 0), ('ct305', 'current_2', 1), ('ct305', 'current_3', 2),
    ('ct305', 'total_1', 3), ('ct305', 'total_2', 4), ('ct305', 'total_3', 5),
    ('ct305', 'temperature', 6);

INSERT INTO buildings (name, slug, is_active) VALUES
    ('Kjølv Egelands hus', 'kjolv-egelands-hus', TRUE),
    ('Arne Rettedals hus', 'arne-rettedals-hus', TRUE),
    ('EOJ', 'eoj', TRUE), ('SiS', 'sis', TRUE), ('Library', 'library', FALSE);

-- Initial deployment registry only; no AppKeys and no synthetic readings.
-- The migration runs once, so subsequent administrative edits survive restarts.
INSERT INTO devices (eui, building_id, type, label, room)
SELECT s.eui, b.id, 'am103', s.label, s.room
FROM (VALUES
    ('24e124725f514441', 'kjolv-egelands-hus', 'AM103-KEH-A101', 'A101'),
    ('24e124725f519422', 'kjolv-egelands-hus', 'AM103-KEH-E101', 'E101'),
    ('24e124725f514020', 'kjolv-egelands-hus', 'AM103-KEH-C106', 'C106'),
    ('24e124725f517900', 'sis', 'AM103-SiS-Styrkesal', 'Styrkesal'),
    ('24e124725f517844', 'sis', 'AM103-SiS-Functional Fitness', 'Functional Fitness'),
    ('24e124725f512512', 'kjolv-egelands-hus', 'AM103-KEH-Biblioteket', 'Biblioteket'),
    ('24e124725f517383', 'arne-rettedals-hus', 'AM103-ARH-Q120', 'Q120'),
    ('24e124725f518499', 'arne-rettedals-hus', 'AM103-ARH-G001', 'G001'),
    ('24e124725f512668', 'eoj', 'AM103-EOJ-101', '101'),
    ('24e124725f518129', 'eoj', 'AM103-EOJ-110', '110'),
    ('24e124725f516684', 'kjolv-egelands-hus', 'AM103-KEH-C101', 'C101'),
    ('24e124725f515337', 'kjolv-egelands-hus', 'AM103-KEH-Utenfor', 'Utenfor')
) AS s(eui, building_slug, label, room)
JOIN buildings b ON b.slug = s.building_slug;

COMMENT ON TABLE readings IS 'Append-only canonical measurements; one device/metric/network-event timestamp.';
COMMENT ON COLUMN readings.time IS 'ChirpStack network event time in UTC; never synthesized on receipt.';
COMMENT ON COLUMN readings.received_at IS 'Database receipt time; duplicates keep their original value and receipt time.';
COMMENT ON TABLE sensor_model_metrics IS 'Supported metric capabilities and display order for each hardware model.';
COMMENT ON COLUMN devices.is_active IS 'FALSE retires hardware without deleting measurements.';
COMMENT ON COLUMN devices.building_id IS 'Current placement; moving a device changes the building attribution of its displayed history.';
-- TimescaleDB exposes a continuous aggregate through an ordinary user view.
COMMENT ON VIEW readings_hourly IS 'Indefinite hourly summaries; use sum/sample_count for weighted averages. Counter averages are not consumption.';

-- Runtime logins are granted explicit privileges by app.db.migrate.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON FUNCTION validate_reading(), protect_device_identity() FROM PUBLIC;
