# Sensor inventory and registration

The supplied CSV specifies model quantities, not individual radio identities.
The database stores that plan in `sensor_models`; `/api/sensor-models` returns
planned and registered quantities separately. Register installed devices only
after their actual DevEUI, building, and room are known.

| Type | Planned units | Measurements |
|---|---:|---|
| `am103` | 12, including spares | CO2, temperature, humidity, battery |
| `am107` | 4 | CO2, temperature, humidity, PIR activity, light, TVOC, pressure, battery |
| `ct305` | 3 | Three phase currents, three cumulative current totals, panel temperature |

The AM103 source notes conflict with its quantity: 10 active + 3 spares
does not fit 12 units. The test fleet uses 10 active plus 2 spares; device registration
does not invent an extra unit or enforce that unconfirmed allocation.

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

Migration 0003 stores the 12/4/3 inventory and activates KEH, EOJ, ARK, and SiS.
It archives the old Library record from discovery without changing its ID,
device associations, or readings. Existing history remains accessible by ID.

## Register a physical device

1. Join the sensor to the selected LoRaWAN network server using its real radio
   credentials. Keep application keys in the network server's configuration.
2. Look up building IDs at `/api/buildings`; use slugs rather than assuming IDs
   are identical between databases.
3. Insert the real DevEUI, model type, label, and room. For example, replace the
   illustrative DevEUI and room below with the installed AM107's actual values:

   ```sql
   INSERT INTO devices (eui, building_id, type, label, room)
   SELECT '24e124128b123456', id, 'am107', 'EOJ — Auditorium', 'Actual room'
   FROM buildings WHERE slug = 'eoj' AND is_active;
   ```

4. Confirm a real uplink appears in `/api/buildings/{id}/current`, with recent
   `metric_updated` timestamps. `/history` exposes every decoded metric.
   `/api/sensor-models` shows how many devices of each type are registered.

## AM107 measurement interpretation

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
