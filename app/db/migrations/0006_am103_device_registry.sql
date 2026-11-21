-- Seed the supplied AM103 device registry for this deployment.
-- AppKeys are intentionally omitted; they belong in ChirpStack only.
-- This migration runs once, so later room/location edits are not overwritten
-- each time run.sh starts the stack.

DO $$
DECLARE
    missing_slugs TEXT[];
BEGIN
    SELECT array_agg(required.slug)
      INTO missing_slugs
      FROM (VALUES
          ('kjolv-egelands-hus'),
          ('arne-rettedals-hus'),
          ('eoj'),
          ('sis')
      ) AS required(slug)
     WHERE NOT EXISTS (
         SELECT 1 FROM buildings b
          WHERE b.slug = required.slug AND b.is_active
     );

    IF missing_slugs IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot register AM103s: active building slugs missing: %', missing_slugs;
    END IF;
END $$;

INSERT INTO devices (eui, building_id, type, label, room)
SELECT lower(s.eui), b.id, 'am103', s.label, s.room
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
  JOIN buildings b ON b.slug = s.building_slug AND b.is_active
ON CONFLICT (eui) DO UPDATE
    SET building_id = EXCLUDED.building_id,
        type = EXCLUDED.type,
        label = EXCLUDED.label,
        room = EXCLUDED.room;
