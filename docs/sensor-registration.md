# Sensor inventory and registration

The current deployment uses 12 AM103 sensors. The database stores planned and
registered quantities separately in `sensor_models`; `/api/sensor-models`
reports both. Register each installed AM103 only after its actual DevEUI,
building, and room are known.

| Type | Planned units | Measurements |
|---|---:|---|
| `am103` | 12 | CO2, temperature, humidity, battery |
| `am107` | 0 (phased out) | Legacy support: CO2, temperature, humidity, PIR activity, light, TVOC, pressure, battery |
| `ct305` | 0 (phased out) | Legacy support: three phase currents, cumulative current totals, panel temperature |

The deployment decision is to use all 12 AM103 units. This supersedes the
source CSV note that said 10 active plus 3 spares. AM107 and CT305 data support
is retained for historical compatibility, but they are not planned devices.

UG65 units are network gateways; the PCs, storage and TVs are infrastructure.
They are not registered as measurement sensors in `devices`.

## Apply the schema

On the Linux server, start through the launcher. On first use it asks for the
server address and creates `.env` with generated credentials:

```bash
bash run.sh
docker compose logs migrate
```

The migration job must finish successfully before API/ingestion start. It
supports both new and existing volumes; do not delete a volume to upgrade it.
Historical SQL files are recorded with checksums. Add a new migration for
future changes instead of editing an already-applied file.

Migration 0003 stored the original 12/4/3 source inventory. Migration 0005
updates the active plan to 12/0/0 and activates KEH, EOJ, ARK, and SiS. It does
not delete any AM107/CT305 device registrations or readings.
It archives the old Library record from discovery without changing its ID,
device associations, or readings. Existing history remains accessible by ID.

## Register a physical device

1. Join the sensor to the selected LoRaWAN network server using its real radio
   credentials. Keep application keys in the network server's configuration.
2. Look up building IDs at `/api/buildings`; use slugs rather than assuming IDs
   are identical between databases.
3. Insert the real DevEUI, model type, label, and room. For example, replace the
   illustrative DevEUI and room below with the installed AM103's actual values:

   ```sql
   INSERT INTO devices (eui, building_id, type, label, room)
   SELECT '24e124128b123456', id, 'am103', 'EOJ — Teaching room 1', 'Actual room'
   FROM buildings WHERE slug = 'eoj' AND is_active;
   ```

4. Confirm a real uplink appears in `/api/buildings/{id}/current`, with recent
   `metric_updated` timestamps. `/history` exposes every decoded metric.
   `/api/sensor-models` shows how many devices of each type are registered.

## Legacy AM107 measurement interpretation

AM107 is phased out of the active fleet. This section documents how existing
AM107 records and readings remain available for compatibility.

The decoder follows the [Milesight AM107 payload reference](https://github.com/Milesight-IoT/SensorDecoders/blob/main/am-series/am107/am107-decoder.js).
It preserves all ten numeric outputs: `battery`, `temperature`, `humidity`,
`activity`, `illumination`, `infrared_and_visible`, `infrared`, `co2`, `tvoc`,
and `pressure`. The six-byte light record contains three separate values;
PIR activity is a 16-bit count. It is not treated as a people count or an
occupied/vacant flag. The mobile view exposes these measurements with their
own freshness timestamps.

AM103 and AM107 both contribute CO2/temperature to climate summaries,
coverage, freshness checks, and sustained-CO2 recommendations. A fresh activity
report cannot make old climate readings current. Energy per occupied hour and
automated ventilation control need a separate, validated method/integration.
