# UG65 gateway configuration

The recommended path uses ChirpStack v4 in the NanitesLab Compose stack. Each
UG65 forwards LoRaWAN packets through its built-in ChirpStack-v4 MQTT forwarder
to the shared Mosquitto broker. ChirpStack consumes those gateway frames and
publishes application uplinks for NanitesLab's ingest service. The old embedded
network-server MQTT path can remain active until ChirpStack is provisioned and
ready for cutover. See [`../../technical-setup.md`](../../technical-setup.md).

## Before switching a gateway

1. If a separate ChirpStack Docker stack is already running, back up its
   configuration and PostgreSQL data first. The new `chirpstack-postgres-data`
   volume starts empty; this Compose change does not import existing
   tenants/devices. Stop the old stack without `docker compose down -v` before
   starting the merged stack, and ensure only one broker binds host port 1883.
   Keep the old volumes until the merged ChirpStack data has been checked.
2. Start the merged Compose stack and open `http://localhost:8081` on the server.
3. In ChirpStack, create a tenant and application, then create an EU868 device
   profile with the correct LoRaWAN version and OTAA settings.
4. Register each sensor using its DevEUI, JoinEUI, and AppKey. Register the
   same DevEUI in NanitesLab's `devices` table with its building and model.
5. Confirm the server is reachable from the gateway over a private VPN/tunnel.
   Set `MQTT_BIND_ADDRESS` in `.env` to the server's private interface and
   recreate Mosquitto. The default `127.0.0.1` binding is only reachable on the
   server PC.

## UG65 Packet Forwarder settings

On each gateway, use **Packet Forwarder → General** and add/select **ChirpStack-v4**.
Set the region ID to `eu868` and configure its MQTT connection:

| Setting | Value |
|---|---|
| MQTT broker address | Server's private VPN/LAN IP or DNS name |
| MQTT port | `1883` |
| Username | `sensorhub-ug65-forwarder` |
| Password | `MQTT_FORWARDER_PASSWORD` from the server's `.env` |
| Region ID | `eu868` |
| TLS | Use a private encrypted VPN/tunnel; port 1883 itself is plaintext |

Confirm the gateway appears online in ChirpStack and that a test device's
uplink appears in ChirpStack before disabling its old embedded-network-server
MQTT transmission. Do not forward the same sensor through both network servers
after cutover, because that can create duplicate events and competing downlinks.

## Keep MQTT private

The broker port is bound to loopback by default. Never expose plaintext MQTT
port 1883 directly to the public internet. Configure the VPN/tunnel and firewall
first, then use `MQTT_BIND_ADDRESS` to bind only to the private server interface.
The `sensorhub-ug65-forwarder`, `sensorhub-chirpstack`, and
`sensorhub-ingest` accounts have separate ACLs and unique passwords. Changing
one of the MQTT passwords requires recreating the Mosquitto container so its
hashed password file is rebuilt.

## Legacy embedded network server

If you keep the UG65's embedded network server, its **Network Server → MQTT**
transmission uses username `sensorhub-gateway` and `MQTT_GATEWAY_PASSWORD`, and
publishes application uplinks to `application/<app>/device/<device>/event/up`.
Use this mode or ChirpStack for a given sensor, not both after cutover.

## Device registration in NanitesLab

NanitesLab only stores readings for devices in its `devices` table. Add the
sensor's actual DevEUI and room assignment after registering it in ChirpStack:

```sql
INSERT INTO devices (eui, building_id, type, label, room)
VALUES ('24e124128b123456', 1, 'am103', 'KEH — Teaching room 1', 'Room 1');
```

The DevEUI is printed on the sensor label and shown in ChirpStack. Supported
device types are `am103`, `am107`, and `ct305`; see
[`../../docs/sensor-registration.md`](../../docs/sensor-registration.md).
