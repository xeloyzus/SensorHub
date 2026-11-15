-- Additive upgrade: preserve every existing device and reading. NOT VALID
-- constraints enforce new writes without deleting historical invalid records.
ALTER TABLE devices ADD CONSTRAINT devices_eui_format
    CHECK (eui ~ '^[0-9a-f]{16}$') NOT VALID;
ALTER TABLE devices ADD CONSTRAINT devices_label_not_blank
    CHECK (btrim(label) <> '') NOT VALID;
ALTER TABLE readings ADD CONSTRAINT readings_metric_not_blank
    CHECK (btrim(metric) <> '') NOT VALID;
ALTER TABLE readings ADD CONSTRAINT readings_value_finite
    CHECK (value > '-Infinity'::double precision AND value < 'Infinity'::double precision) NOT VALID;

-- Supports per-metric latest readings and duplicate-uplink lookups.
CREATE INDEX IF NOT EXISTS idx_readings_device_metric_time
    ON readings (device_id, metric, time DESC);
CREATE INDEX IF NOT EXISTS idx_devices_building ON devices (building_id);
