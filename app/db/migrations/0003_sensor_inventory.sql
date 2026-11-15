-- Updated hardware.csv: 12 AM103 (including spares), 4 AM107, 3 CT305.
-- Quantities describe the plan, not installed or communicating devices.
CREATE TABLE IF NOT EXISTS sensor_models (
    type             TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    planned_quantity INTEGER NOT NULL CHECK (planned_quantity >= 0),
    metrics          TEXT[] NOT NULL
);

INSERT INTO sensor_models (type, name, planned_quantity, metrics) VALUES
    ('am103', 'Milesight AM103', 12,
     ARRAY['battery', 'temperature', 'humidity', 'co2']),
    ('am107', 'Milesight AM107', 4,
     ARRAY['battery', 'temperature', 'humidity', 'activity', 'illumination',
           'infrared_and_visible', 'infrared', 'co2', 'tvoc', 'pressure']),
    ('ct305', 'Milesight CT305', 3,
     ARRAY['current_1', 'current_2', 'current_3', 'total_1', 'total_2', 'total_3', 'temperature'])
ON CONFLICT (type) DO UPDATE SET
    name = EXCLUDED.name,
    planned_quantity = EXCLUDED.planned_quantity,
    metrics = EXCLUDED.metrics;

ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_type_check;
ALTER TABLE devices ADD CONSTRAINT devices_type_check
    CHECK (type IN ('am103', 'am107', 'ct305'));
ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_model_fkey;
ALTER TABLE devices ADD CONSTRAINT devices_model_fkey
    FOREIGN KEY (type) REFERENCES sensor_models(type);

ALTER TABLE buildings ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
INSERT INTO buildings (name, slug) VALUES ('EOJ', 'eoj'), ('SiS', 'sis')
ON CONFLICT (slug) DO NOTHING;

-- Preserve the old Library ID, devices, and readings, but use the current
-- KEH / EOJ / ARK / SiS plan for building discovery and campus summaries.
UPDATE buildings SET is_active = FALSE WHERE slug = 'library';
