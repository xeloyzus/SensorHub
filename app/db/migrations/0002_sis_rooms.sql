-- Correct the requested placements once, preserving device IDs and readings.
-- This also inserts these devices if an installation's registry is incomplete.
INSERT INTO devices (eui, building_id, type, label, room)
SELECT s.eui, b.id, 'am103', s.label, s.room
FROM (VALUES
    ('24e124725f517900', 'AM103-SiS-Styrkesal', 'Styrkesal'),
    ('24e124725f517844', 'AM103-SiS-Functional-Fitness', 'Functional Fitness'),
    ('24e124725f515337', 'AM103-SiS-Gruppetimesal', 'Gruppetimesal')
) AS s(eui, label, room)
JOIN buildings b ON b.slug = 'sis'
ON CONFLICT (eui) DO UPDATE SET
    building_id = EXCLUDED.building_id,
    label = EXCLUDED.label,
    room = EXCLUDED.room;
