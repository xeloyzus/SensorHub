-- Current deployment decision: use 12 AM103 sensors; phase out AM107 and CT305.
-- Keep legacy model rows, device records, and readings for compatibility/history.
UPDATE sensor_models SET planned_quantity = 12 WHERE type = 'am103';
UPDATE sensor_models SET planned_quantity = 0 WHERE type IN ('am107', 'ct305');
