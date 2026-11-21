# UG65 gateway configuration

The NanitesLab Compose stack uses ChirpStack v4 with ChirpStack Gateway Bridge.
Each UG65 forwards LoRaWAN packets using its Semtech UDP packet forwarder to
the server on UDP port 1700. Gateway Bridge converts those packets to EU868 MQTT
events for ChirpStack. The old embedded-network-server MQTT path can remain
active until the provisioned ChirpStack deployment has received and verified
sensor uplinks. See
[`../../technical-setup.md`](../../technical-setup.md).

## Automatic ChirpStack setup

`bash run.sh` provisions these gateway records in ChirpStack:

| Gateway EUI | Name |
|---|---|
| `24e124fffef3e837` | `ARH_Gateway` |
| `24e124fffef3e679` | `KEH_Gateway` |
| `24e124fffef3f713` | `UiS_Gateway` |

It also provisions the tenant, AM103 application, and all 12 devices. The
device profile is EU868, LoRaWAN 1.0.3, regional parameters revision B, OTAA.
On first run, it asks for the shared AppKey and stores it in `.env`; the same
key is assigned to every AM103 in ChirpStack.

## Before switching a gateway

1. If a separate ChirpStack Docker stack is already running, back up its
   configuration and PostgreSQL data first. The new `chirpstack-postgres-data`
   volume starts empty; this Compose change does not import existing
   tenants/devices. Stop the old stack without `docker compose down -v` before
   starting the merged stack, and ensure only one broker binds host port 1883.
   Keep the old volumes until the merged ChirpStack data has been checked.
2. Run `bash run.sh` and wait for its ChirpStack provisioning summary.
3. Confirm the server is reachable from the gateway over a private VPN/tunnel.
   Allow UDP port `1700` from the gateway IPs to the server. The bridge listener
   is published on all server interfaces by default; set
   `GATEWAY_BRIDGE_BIND_ADDRESS` in `.env` to a private interface IP if needed.
   Keep the firewall restricted because Semtech UDP has no authentication.

## UG65 Packet Forwarder settings

On each gateway, use **Packet Forwarder → General** and add a destination of
type **Semtech**. Enter the server's private LAN/VPN address and set both
Semtech UDP ports to `1700`. Configure **Packet Forwarder → Radios** for EU868;
the channel plan must match the ChirpStack `eu868` region.

| Setting | Value |
|---|---|
| Type | `Semtech` |
| Server address | Server's private VPN/LAN IP or DNS name |
| Uplink port | `1700` / UDP |
| Downlink port | `1700` / UDP |
| Radio region / channel plan | EU868 |
| Gateway ID | Exact Gateway EUI shown on the UG65, registered identically in ChirpStack |

Confirm the gateway appears online in ChirpStack and that a test device's
uplink appears in ChirpStack before disabling its old embedded-network-server
MQTT transmission. Do not forward the same sensor through both network servers
after cutover, because that can create duplicate events and competing downlinks.

## Keep gateway traffic private

Semtech UDP port 1700 has no authentication or encryption. Use a private LAN or
VPN and restrict the server firewall to the gateway IPs. Mosquitto remains
bound to loopback by default and only Gateway Bridge connects to it over the
internal Docker network. The `sensorhub-gateway-bridge`, `sensorhub-chirpstack`,
and `sensorhub-ingest` accounts have separate ACLs and passwords. Changing the
bridge MQTT password requires recreating Mosquitto so its hashed password file
is rebuilt. Docker-published ports can bypass UFW rules; apply the source-IP
restriction in the upstream firewall or Docker's `DOCKER-USER` chain as well.

## Legacy embedded network server

If you keep the UG65's embedded network server, its **Network Server → MQTT**
transmission uses username `sensorhub-gateway` and `MQTT_GATEWAY_PASSWORD`, and
publishes application uplinks to `application/<app>/device/<device>/event/up`.
Use this mode or ChirpStack for a given sensor, not both after cutover.

## Registering additional devices in NanitesLab

NanitesLab only stores readings for devices in its `devices` table. Add the
sensor's actual DevEUI and room assignment after registering it in ChirpStack:

```sql
INSERT INTO devices (eui, building_id, type, label, room)
VALUES ('24e124128b123456', 1, 'am103', 'KEH — Teaching room 1', 'Room 1');
```

The DevEUI is printed on the sensor label and shown in ChirpStack. Supported
device types are `am103`, `am107`, and `ct305`; see
[`../../docs/sensor-registration.md`](../../docs/sensor-registration.md).
