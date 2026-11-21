# Sensor inventory and registration

The current deployment uses 12 AM103 sensors. The database stores planned and
registered quantities separately in `sensor_models`; `/api/sensor-models`
reports both. The project registry contains the 12 supplied AM103 DevEUIs,
buildings, and rooms; `run.sh` creates the same inventory in ChirpStack.

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
server address, creates `.env` with generated credentials, and asks once for
the shared AppKey already programmed into all 12 AM103 sensors:

```bash
bash run.sh
docker compose logs migrate
```

The migration job must finish successfully before API/ingestion start. It
supports both new and existing volumes; do not delete a volume to upgrade it.
Historical SQL files are recorded with checksums. Add a new migration for
future changes instead of editing an already-applied file.

Migration 0003 stored the original 12/4/3 source inventory. Migration 0005
updates the active plan to 12/0/0 and activates KEH, EOJ, ARK, and SiS. Migration
0006 registers the supplied 12 AM103 DevEUIs with their building and room
assignments. The ChirpStack bootstrap provisions those same devices with OTAA
credentials, the shared AppKey, and an EU868/LoRaWAN 1.0.3 device profile using
regional parameters revision B. The AppKey is stored only in `.env`, not in
NanitesLab's database. The default JoinEUI is Milesight's factory value; set
`CHIRPSTACK_AM103_JOIN_EUI` in `.env` if the sensors were changed to another
JoinEUI. The migration does not delete AM107/CT305 records or
readings. These are one-time migrations; later location edits remain intact.
It archives the old Library record from discovery without changing its ID,
device associations, or readings. Existing history remains accessible by ID.

## Verify device registration

1. The launcher creates all listed sensors in NanitesLab and ChirpStack, with
   their DevEUIs, JoinEUI, room tags, and shared OTAA AppKey. Do not manually
   add a second copy of these devices.
2. Confirm all 12 devices and three gateways appear in ChirpStack. The profile
   is EU868, LoRaWAN 1.0.3, regional parameters revision B, Class A/OTAA.
3. After configuring the UG65 Semtech packet forwarders, confirm a real uplink
   appears in `/api/buildings/{id}/current`, with recent
   `metric_updated` timestamps. `/history` exposes every decoded metric.
   `/api/sensor-models` shows how many devices of each type are registered.

## Automatic registration

On a server with the updated project, `bash run.sh` applies migration 0006,
starts the services, then reconciles the ChirpStack tenant, profile,
application, gateways, devices, and OTAA keys. The API token and shared AppKey
remain in the private `.env` file. Future devices should be added through a
new migration and the ChirpStack bootstrap inventory together.

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
