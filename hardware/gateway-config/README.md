# UG65 gateway configuration

The implemented path uses each UG65's embedded LoRaWAN network server to
forward uplinks over MQTT to the NanitesLab Mosquitto broker on the dedicated
Linux PC. The updated inventory proposes ChirpStack/MQTT on a GMKtec node;
ChirpStack is not deployed by the current Compose file. Confirm the server/edge
layout and configure the gateways for the selected network server before
changing the working path. See [`../../technical-setup.md`](../../technical-setup.md).

## Current MQTT integration (embedded network server)

On each gateway (Network Server → MQTT):

| Setting            | Value                             |
| ------------------ | --------------------------------- |
| Broker address     | the Linux server's private VPN address or local encrypted-tunnel endpoint |
| Broker port        | `1883`                            |
| Protocol           | MQTT (TCP), carried over an encrypted VPN/tunnel |
| Username           | `naniteslab-gateway`              |
| Password           | the `MQTT_GATEWAY_PASSWORD` configured on the Linux server |
| Topic prefix       | `application/1/device/` (or as configured) |

The broker's published port binds to loopback by default. Configure a managed
VPN/tunnel first; set `MQTT_BIND_ADDRESS` to the Linux server's private VPN
interface if gateways connect over that VPN. Do not expose plaintext port 1883 publicly.
Authentication does not encrypt passwords or sensor traffic.

Ingest defaults to `application/+/device/+/event/up` (ChirpStack v4). For v3,
set `MQTT_TOPIC=application/+/device/+/rx`. The broker ACL permits both layouts.
If a gateway uses a different topic, update both `MQTT_TOPIC` and
`mosquitto/acl` before deploying. Ingest uses username `naniteslab-ingest`
and a separate password, and has no permission to publish gateway readings.

For an existing deployment, add distinct random `MQTT_GATEWAY_PASSWORD` and
`MQTT_INGEST_PASSWORD` values to `.env`, establish the private network path,
and update every gateway's credentials before restarting the broker and
ingestion service. The startup script rebuilds the hashed password file each
time the broker starts, so changing a secret requires recreating the container.

## Device registration

The ingest only stores data for devices that exist in the `devices` table.
After a sensor joins the network, register it with its DevEUI, e.g.:

```sql
INSERT INTO devices (eui, building_id, type, label, room)
VALUES ('24e124128b123456', 1, 'am103', 'KEH — Teaching room 1', 'Room 1');
```

The DevEUI is printed on the sensor label and shown in the network server's
device list. Use `/api/buildings` to look up current building IDs by slug;
active buildings are KEH, EOJ, ARK, and SiS. Library's old ID is preserved
for historical access. Supported device types are `am103`, `am107`, `ct305`.
See [`../../docs/sensor-registration.md`](../../docs/sensor-registration.md)
for AM107 metrics and registration requirements.

## Uplink settings

- Confirm each sensor is set to report every **15 minutes**.
- Do **not** enable Milesight IoT Cloud — data goes directly to the custom
  backend via MQTT (IoT Cloud has no export API).
