# Campus dashboard — Technical Setup

Technical documentation for the UiS Green Funds sensor network, backend,
dashboard, and signage deployment (14 Sep – 31 Dec 2026).

## 1. Deployment decisions

The application and database run on a **dedicated Linux PC**. Three signage
screens in KEH, EOJ, and ARK load the exposed dashboard URL through Samsung's
built-in internet/URL feature.
The Mac Studio is reserved for other work and is outside Campus dashboard.

The imported [`hardware/hardware.csv`](hardware/hardware.csv) also lists a
GMKtec G10 for ChirpStack/MQTT. This Compose stack now runs ChirpStack on the
same Linux PC as NanitesLab; reconcile the listed hardware role with the actual
server inventory. Edge-to-central replay is not implemented.

## 2. Configured target data path

```text
12 Milesight AM103 sensors
        | LoRaWAN
        v
UG65 gateways (Semtech UDP packet forwarder)
        | UDP 1700 over private LAN/VPN
        v
Dedicated Linux PC — Docker Compose
   Gateway Bridge -> Mosquitto <-> ChirpStack -> MQTT application events
        |                          |
        +-----------> ingest <------+ -> TimescaleDB -> FastAPI -> Caddy
                                                               | HTTPS
                               +-------------------------------+----------+
                               v                               v          v
                     Signage browsers (3)          Interactive dashboard  Mobile
                             /                          /overview         /mobile
```

Grafana provides an internal administration/debug view on server loopback.
NanitesLab's ingest service decodes the raw Base64 LoRaWAN payload and writes
telemetry to its own TimescaleDB. ChirpStack has separate PostgreSQL and Redis
volumes. ChirpStack Gateway Bridge listens for Semtech UDP on port 1700 and
publishes EU868 gateway events to Mosquitto with a dedicated MQTT account. The
old UG65 embedded-network-server MQTT path remains available while
devices and gateways are being provisioned; do not ingest the same sensor via
both paths after cutover. The Compose services are configured, but gateway
cutover and real sensor registration remain manual installation steps.

## 3. Updated hardware and placement

The full inventory, source prices, and reconciled totals are in
[`hardware/README.md`](hardware/README.md). The current active sensor plan is
12 AM103 units. AM107 and CT305 from the source CSV are phased out; legacy
decoding and historical data support remain in the application.

| Equipment | Quantity | Intended placement |
|---|---:|---|
| Milesight AM103 | 12 | Active fleet: air quality across KEH, EOJ, ARK, and SiS |
| Milesight AM107 | 0 | Phased out; legacy data support retained |
| Milesight CT305 | 0 | Phased out; legacy data support retained |
| Milesight UG65 | 3 | One per major building; verify overlapping SiS coverage |
| Samsung signage TV | 3 | One per major building, opening the web URL |
| Wall mount | 3 | One per TV |
| GMKtec G10 | 1 | Listed as ChirpStack/MQTT node; server/edge role unresolved |
| 1TB SSD | 1 | Source assigns it to the excluded Mac Studio; role unresolved |

The current decision is to use all 12 AM103 units. This supersedes the source
CSV note that listed 10 active plus 3 spares.

See [`hardware/sensor-placement.md`](hardware/sensor-placement.md) for siting.
The CT305 panel-access discussion is historical; CT305 installation is not part
of the active deployment.

## 4. Repository structure

```text
sensorhub/
├── docker-compose.yml      # app, ChirpStack, and supporting services
├── Caddyfile               # HTTPS reverse proxy to FastAPI
├── .env.example            # runtime configuration template
├── run.sh                  # Linux launcher
├── mosquitto/              # broker configuration, ACLs, startup script
├── chirpstack/             # ChirpStack v4 and EU868 configuration
├── ingest/                 # MQTT parser, device registry, Milesight decoders
├── app/
│   ├── core/               # runtime settings
│   ├── db/migrations/      # schema, seeded buildings, retention policies
│   ├── routers/            # JSON endpoints and HTML page routes
│   ├── schemas/            # API response models
│   ├── services/           # queries, quality rules, analytics
│   ├── templates/          # signage, overview, mobile pages
│   └── static/             # JavaScript, CSS, QR asset
├── hardware/               # imported CSV, inventory notes, placement, gateways
├── tests/                  # Python, frontend, and Docker integration checks
├── docs/                   # Samsung signage setup; installation coordination
└── report/                 # final report template
```

## 5. Linux server and public access

Install Docker Engine and the Docker Compose plugin on the dedicated Linux
PC. The launcher checks Docker, Compose, and daemon access before starting.
Run `bash run.sh` for first-time address/credential setup, and follow the
[`README.md`](README.md) quick start. The existing services are:

| Compose service | Role |
|---|---|
| `mosquitto` | Authenticated internal broker shared by Gateway Bridge, ChirpStack, and ingest |
| `chirpstack-gateway-bridge` | Semtech UDP 1700 ingress; publishes EU868 frames to MQTT |
| `chirpstack` | LoRaWAN network server and application event publisher |
| `chirpstack-postgres` | ChirpStack's independent PostgreSQL database |
| `chirpstack-redis` | ChirpStack session and queue state |
| `migrate` | Ordered database upgrades before ingestion/API startup |
| `ingest` | AM103/AM107/CT305 decoding and transactional database writes |
| `timescaledb` | Sensor registry, readings, hourly aggregates |
| `api` | FastAPI JSON endpoints, templates, and static assets |
| `grafana` | Internal administration/debugging, bound to loopback |
| `caddy` | HTTPS reverse proxy to FastAPI |

Arrange the domain, public endpoint, firewall rules, and certificate validation
with UiS IT. In the current direct-Caddy setup, ports 80/443 reach the Linux
PC. If UiS provides its own public reverse proxy, agree the TLS/routing setup
and adapt this deployment before cutover. Public DNS pointing at a campus
private IP alone is insufficient for off-campus mobile access.

Only the web endpoint is intended for public use. Semtech UDP 1700 is
unauthenticated and unencrypted; allow it only from gateway IPs on an approved
private LAN/VPN and configure the firewall accordingly. MQTT remains on loopback
for host access and private to the Docker network. Grafana is reached through
an SSH tunnel; TimescaleDB has no published host port.

Enable Docker and containerd at boot (`sudo systemctl enable --now
docker.service containerd.service`), disable server sleep, keep OS/container
updates maintained, and back up the database to a separate destination. All
long-running Compose services use Docker's `always` restart policy and return
when the Docker daemon starts; the migration service remains a one-shot job.

## 6. Signage setup

Configure Samsung's integrated URL feature to open `https://<DOMAIN>/`
automatically. The Linux PC serves the webpage; its JavaScript rotates the
display content and requests fresh API data. The Samsung screen handles URL
startup and recovery after a power/network interruption.

Use [`docs/signage-setup.md`](docs/signage-setup.md) to verify server/network
access, data refresh, and restart behaviour on the actual displays.

## 7. Data volume and retention

- The active fleet has 12 AM103 devices, or about 1,152 uplinks/day at one
  uplink per device every 15 minutes.
- These are planning counts; actual
  message/storage volume depends on payloads and occupancy reporting cadence.
- Raw readings are retained for 90 days; hourly aggregates are kept indefinitely
  (`app/db/migrations/0002_retention.sql`). Retention refresh/replay behaviour
  must be considered before enabling historical sensor uploads.
- Ingestion currently subscribes at QoS 0. Database-outage replay, persistent
  edge buffering, and durable deduplication are follow-up work. A local broker
  alone does not establish offline data resilience.

## 8. Remaining implementation and installation work

- [ ] Resolve whether the GMKtec is the Linux application host or a separate edge node.
- [ ] Confirm the Linux PC's storage; remove/reassign the CSV's Mac Studio SSD note.
- [x] Use 12 AM103 sensors; phase AM107 and CT305 out of the active deployment.
- [ ] Confirm exact TV SKU/size and test its built-in URL feature with the webpage.
- [x] Add ChirpStack and MQTT integration to the single-host Compose stack.
- [ ] Provision the ChirpStack application/devices and cut over the UG65 gateways.
- [x] Retain AM107/CT305 legacy decoding and history compatibility; neither is in the active plan.
- [ ] Define occupancy/light metrics and energy-per-occupied-hour methodology;
  ventilation-control integration is not part of the current application.
- [x] Add EOJ/SiS to the active database registry; archive Library without deleting its data.
- [ ] Register actual sensor DevEUIs and room assignments; the CSV contains model quantities only.
- [ ] Verify LoRaWAN coverage in each intended room, including SiS.
- [ ] Agree a stable domain and exposed HTTPS route with UiS IT.
- [ ] Verify the live sensor path, all three screen startups, and backup recovery.
- [ ] Decide whether a third participant joins the project.
