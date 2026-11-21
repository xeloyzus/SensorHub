# Campus dashboard

LoRaWAN sensors feed a self-hosted stack on a **dedicated Linux PC**. Three
signage screens in KEH, EOJ, and ARK open the exposed dashboard URL directly
using Samsung's built-in internet/URL feature. The Mac Studio is used for other
work and is outside this deployment.

The current deployment uses 12 Milesight AM103 sensors and 3 UG65 gateways.
AM107 sensors and CT305 current clamps are phased out of the active plan. See
[`hardware/README.md`](hardware/README.md) for the imported source inventory
and the updated deployment decision.

See [`technical-setup.md`](technical-setup.md) for the full system design.

## Architecture

```
[12 AM103] --LoRaWAN--> [UG65: Semtech UDP]
                                             |
                                             | UDP 1700
                                             v
                                  [ChirpStack Gateway Bridge]
                                             |
                                             | MQTT gateway frames
                                             v
                                      [Mosquitto] <--> [ChirpStack]
                                           |             |       |
                                           |             |       +-- PostgreSQL + Redis
                                           |             +-- MQTT application uplinks
                                           v
                                      [ingest] --decode--> [TimescaleDB]
                                                               |
                                                               v
[Signage browsers + mobile] <--HTTPS-- [Caddy] <-- [FastAPI api] <+
```

All services run in this Compose project. The UG65 Semtech UDP packet forwarder
sends LoRaWAN frames to ChirpStack Gateway Bridge on UDP port 1700. The bridge
publishes EU868 gateway events to the shared Mosquitto broker; ChirpStack then
publishes application uplinks back to that broker for NanitesLab ingestion.
The app's decoder handles the raw Base64 payload, so a ChirpStack codec is not
required. AM107 and CT305 decoders remain for historical data compatibility;
the active deployment is 12 AM103 sensors. The previous UG65
embedded-network-server MQTT path remains available until ChirpStack is
provisioned and you are ready to switch the gateways.
The active building registry covers KEH, EOJ, ARK, and SiS.

## Repository layout

```
sensorhub/
├── docker-compose.yml      # the whole stack
├── Caddyfile               # reverse proxy + automatic HTTPS
├── .env.example            # first-run configuration template
├── scripts/                # environment setup and ChirpStack bootstrap
├── requirements-dev.txt    # test dependencies
├── run.sh                  # convenience launcher (Linux server)
├── mosquitto/              # broker config
├── chirpstack/             # ChirpStack v4 and EU868 configuration
├── chirpstack-gateway-bridge/ # Semtech UDP to EU868 MQTT bridge
├── app/                    # FastAPI backend + frontend (layered)
│   ├── main.py             # app entrypoint
│   ├── dependencies.py     # get_db dependency
│   ├── core/               # settings (config.py)
│   ├── db/                 # connection pool + SQL migrations/
│   ├── internal/           # ops endpoints (health)
│   ├── routers/            # thin HTTP layer (API + pages)
│   ├── schemas/            # Pydantic response models
│   ├── services/           # business logic
│   ├── static/             # CSS / JS / images
│   └── templates/          # Jinja2 templates (base/index/mobile)
├── ingest/                 # MQTT -> decode -> TimescaleDB
├── tests/                  # pytest suite
├── hardware/               # updated inventory, placement + gateway config
├── docs/                   # Samsung signage setup + Driftsenheten dialogue
└── report/                 # final report template
```

## Quick start

For a local installation without a fixed IP or domain, run `bash run.sh --local`
on first use. For a server, run `bash run.sh`; it asks for the hostname or
`http://SERVER_IP`. That single command creates or upgrades `.env`, asks for the
shared AM103 AppKey if needed, reconciles the TimescaleDB password with its
persistent volume, builds and starts the stack, applies migrations, and
provisions ChirpStack. It is also the command to use on later starts. Do not run
the helper scripts separately.

For local HTTP access, `bash run.sh --local` serves the app at
`http://localhost:8080`. It also accepts local network host addresses, so the
server is not tied to one DHCP address. From a Samsung screen, use the PC's
network hostname/current address with port 8080; `localhost` on the screen
refers to the screen itself. Later, change `DOMAIN`, `HTTP_PORT`, and
`HTTPS_PORT` in `.env` to use a different endpoint.

1. **Start the Linux stack.** For public HTTPS access, coordinate with UiS IT.
   Point `DOMAIN` at its approved public endpoint and arrange routing/firewall
   access for ports 80/443 to Caddy, including certificate validation. A campus
   private IP alone does not make the URL reachable by public/mobile clients.
   Docker Engine and the Compose plugin must be installed and running. Run the
   one command from the project root:

   ```bash
   bash run.sh
   ```

   Python 3 is required by the launcher. For local HTTP on port 8080, use
   `bash run.sh --local` on first use. You can also avoid the address prompt with
   `bash run.sh --domain http://SERVER_IP`.

2. **Keep gateway traffic private.** UG65 gateways use Semtech UDP on port
   `1700`, which has no authentication or encryption. Carry it over the private
   LAN/VPN and restrict access to gateway IPs. Docker-published ports can bypass
   UFW rules, so apply the restriction in the upstream firewall or Docker's
   `DOCKER-USER` chain. Mosquitto stays private on the Docker network and
   loopback; do not expose port `1883`.

3. **Use the services.** With a public hostname, Caddy obtains a TLS certificate automatically. The dashboard is served at
   `https://<DOMAIN>/`, the interactive view at
   `https://<DOMAIN>/overview`, the mobile view at `https://<DOMAIN>/mobile`,
   and the API at `https://<DOMAIN>/api/...`.

   For local HTTP access, use `http://SERVER_IP/` and the same route paths;
   DNS and a public TLS certificate are not required for that local URL.

   **Start automatically after a Linux server reboot:** enable Docker at boot
   once, then start the stack detached:

   ```bash
   sudo systemctl enable --now docker.service containerd.service
   bash run.sh
   ```

   The long-running Compose services use Docker's `always` restart policy, so
   Docker brings them back when its daemon starts. The `migrate` job is
   intentionally one-shot and runs when `bash run.sh` is invoked.

4. **ChirpStack provisioning.** On first start, `run.sh` asks once for the
   shared AM103 AppKey, stores it only in the private `.env`, and creates the
   tenant, application, EU868 profile (LoRaWAN 1.0.3, regional parameters B),
   three gateways, and 12 OTAA devices. All 12 devices receive that same key.
   The factory JoinEUI is configured by default; if the sensors' JoinEUI was
   changed, set `CHIRPSTACK_AM103_JOIN_EUI` in `.env` to that value.
   NanitesLab's migration registers the matching DevEUIs and room assignments.
   The bootstrap is repeatable; later `bash run.sh` calls preserve the key and
   reconcile the ChirpStack records.

   If another ChirpStack stack already runs on this PC, back up its database
   and configuration, stop it without deleting its volumes, and ensure only
   one broker binds host port 1883 before starting this combined stack. Its
   existing ChirpStack database is not imported automatically. Keep the backup
   until the combined stack has been checked.

   The remaining gateway work is physical network configuration: set each
   UG65 Packet Forwarder to `Semtech`, enter this server's private VPN/LAN
   address, and use UDP port `1700` for uplink and downlink. Set the radio
   region/channel plan to EU868 and check that the gateway EUI matches the
   values provisioned by the bootstrap. Restrict UDP 1700 to gateway addresses;
   Semtech UDP has no authentication or encryption. After confirming uplinks,
   disable the UG65 embedded-network-server MQTT transmission for those same
   sensors to avoid duplicate ingestion. See
   [`hardware/gateway-config/README.md`](hardware/gateway-config/README.md).

## Database upgrades

`bash run.sh` validates the existing `.env` and runs the `migrate` job before API/ingestion start.
It applies ordered SQL migrations once, records their checksums, and rolls back
a failed migration. Existing TimescaleDB volumes are upgraded in place.
Migration `0003_sensor_inventory.sql` adds legacy model capabilities, original
sensor quantities, EOJ and SiS. Migration `0005_am103_only_deployment.sql`
sets planned quantities to 12 AM103, 0 AM107, and 0 CT305. Legacy Library devices/history are preserved; that building is
archived from active discovery, and its existing ID remains directly queryable.
Migration `0006_am103_device_registry.sql` registers the supplied 12 AM103
DevEUIs and room assignments automatically; it does not store AppKeys.
`scripts/provision_chirpstack.py` provisions the corresponding ChirpStack
resources, uses regional parameters revision B, and keeps the shared AppKey
inside `.env` rather than source control or the NanitesLab database.
Migration `0004_reading_integrity.sql` adds finite-value, device-ID, and nonempty
label/metric checks for new writes, plus query indexes. Existing records are
preserved. The migration runner records checksums; applied SQL files must not
be edited. Review any historical constraint violations before validating them.

If Compose reports missing `DOMAIN`, database, Grafana, or MQTT passwords,
it has not started the services. Run `bash run.sh` from this checkout to
create first-run configuration. If `.env` already exists, fill its missing
values and preserve the password used by any existing database. Validate
without printing secrets using `docker compose --env-file .env config --quiet`.

## API

| Endpoint                          | Description                                   |
| --------------------------------- | --------------------------------------------- |
| `GET /api/buildings`              | list buildings                                |
| `GET /api/buildings/{id}/current` | latest value per metric for every sensor      |
| `GET /api/buildings/{id}/history` | downsampled history (`?range=1h\|24h\|7d\|30d`) |
| `GET /api/campus/summary`         | display/overview aggregate contract           |
| `GET /api/methodology`            | transparent thresholds and recommendation rules |
| `GET /api/system/status`          | sensor source, dashboard URL, and webpage refresh configuration |
| `GET /api/sensor-models`          | supported models, metrics, planned/registered quantities |

## Storage

- The active fleet is 12 AM103 sensors: about 1,152 uplinks/day at one report
  per sensor every 15 minutes.
- Raw readings kept 90 days, then rolled into hourly averages
  (`app/db/migrations/0002_retention.sql`). 20 GB of disk covers years of operation.

## Samsung signage screens

Set each Samsung screen's built-in URL feature to `https://<DOMAIN>/`.
The Linux PC serves the webpage, API, and data; the screens render the page
and periodically request fresh data over their internet connection. See
[`docs/signage-setup.md`](docs/signage-setup.md) for the screen setup.
The screen's integrated URL feature handles opening the page and returning
to it after startup.

## Security notes

- Mosquitto rejects anonymous clients. Its startup script creates hashed
  passwords from the two required MQTT secrets; ACLs grant gateways only
  uplink publishing and ingestion only uplink reading. The default topics
  cover ChirpStack v4 `event/up` and v3 `rx`; update both `MQTT_TOPIC` and
  `mosquitto/acl` if a gateway uses a different layout.
- MQTT is published on loopback by default. Semtech UDP is unauthenticated and
  unencrypted; allow UDP 1700 only from the gateway IPs on a trusted LAN/VPN.
- Grafana is bound to `127.0.0.1` only — reach it via an SSH tunnel.

## Data quality and recommendations

The current-readings API includes every registered sensor, even when it has
never reported. `updated` and `metric_updated` are additive sensor fields;
the existing numeric `readings` map is preserved. Missing timestamps are
treated as unknown, rather than inferred from another sensor.

Current summaries exclude metrics older than 45 minutes and timestamps in
the future. Building/campus freshness represents the least fresh sensor;
the quality object separately reports active, stale, missing, and registered
sensors. An air sensor requires CO2, temperature, and humidity timestamps;
a current clamp requires all three phase-current timestamps. A new battery
reading does not make old environmental readings current.

Indoor temperature statistics include registered AM103 and legacy AM107 air
sensors, excluding CT305 panel temperatures. Current campus
averages are weighted by reporting sensors, historical means by populated
15-minute buckets, and coverage includes registered air sensors with no data.
Historical min/max/p95 describe bucket averages, not raw peaks. Measured zero
current is retained as zero; electricity remains an estimate at 230 V using
the available fresh phases, without calibrated power-factor or kWh data.

Methodology `co2-v2` requires at least four consecutive elevated 15-minute
averages from the same sensor, spanning at least 45 minutes, with no gap
over 20 minutes. Its latest bucket must be within 35 minutes (including
bucket alignment), and its current raw CO2 reading must be less than 20
minutes old. Recommendations are suppressed when the building's overall
freshness is delayed, stale, or unknown. One-hour changes compare timestamps
one hour apart (within five minutes) and reject gaps over 20 minutes.

Ingestion validates JSON types, DevEUIs, base64, and timezone-aware timestamps,
and rejects clocks more than five minutes in the future. Known sensor metadata
is skipped safely before decoding measurements. Metric writes for each uplink
are transactional. Durable replay/deduplication during database outages and
historical sensor replay remain follow-up work; subscription delivery is
currently QoS 0.

## Development checks

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --test tests/*.test.mjs
```

The Node tests execute the mobile template's JavaScript with a minimal DOM
and simulated API responses. The optional Playwright visual check is separate.
Unit tests do not replace a deployment test with Mosquitto and TimescaleDB.

With Docker running, execute the full local integration check:

```bash
python tests/run_integration.py
```

This builds the core services and migration job in a uniquely named Compose project with
synthetic credentials, fresh database volumes, and random loopback ports.
It verifies MQTT authentication and role ACLs, decoder metadata, malformed
message handling, real SQL/API summaries, hourly aggregation, recommendations,
HTML routes, AM107's ten telemetry fields, inventory quantities, upgrades that
preserve existing readings, and broker restart with existing credential files. It removes
its own containers and volumes afterward; production data is never reused.
The startup probe repeats until the QoS 0 subscription is ready, so this check
does not establish durable message delivery during outages.

## Long-term operation (through 2030)

The data is meant to inform a CO₂ plan over many years, so treat it as
infrastructure. The retention design already supports this:
raw readings roll into **hourly averages kept indefinitely**, so year-over-year
comparisons stay possible without unbounded disk growth.

Do these things, on a schedule, and it will keep running:

1. **Yearly maintenance pass** — bump the pinned image tags (below) deliberately
   and test, instead of letting `latest` surprise you:

   ```bash
   docker compose pull
   docker compose up -d
   ```

   Pinned tags to bump: `timescale/timescaledb`, `grafana/grafana` (and any you
   pin later). `caddy:2`, `eclipse-mosquitto:2` and `python:3.12-slim` float
   within a compatible line and self-update on the next `pull`.

2. **Backups** — the 7 years of data must survive disk failure. At this data
   volume (90 days of raw data + hourly rollup) a nightly `pg_dump`
   is more than enough. Add a cron that runs:

   ```bash
   docker compose exec -T timescaledb pg_dump -U sensorhub sensorhub | gzip > backups/sensorhub-$(date +%F).sql.gz
   ```

   …and copy the file off-site (e.g. `rclone` to an object store). Keep the
   last N dumps and prune older ones.

3. **OS security updates** on the Linux server (Debian/Ubuntu example):

   ```bash
   sudo apt install -y unattended-upgrades
   sudo dpkg-reconfigure --priority=low unattended-upgrades
   ```

4. **Stable domain** — use one you will control for years (ideally under
   `uis.no`, an open item in `technical-setup.md`). Changing the domain later
   breaks the QR code, the screen's configured URL, and any bookmarked link.

5. **Uptime monitoring** — point a free monitor (e.g. UptimeRobot) at
   `https://<DOMAIN>/health` and `https://<DOMAIN>/api/system/status`, and add
   a second check for `https://<DOMAIN>/api/buildings` so a failure is noticed
   within a day rather than when someone walks past a blank signage screen.

6. **Live sensor cutover checklist**

   - `DATABASE_URL` points at the TimescaleDB service.
   - `docker compose ps` shows `chirpstack`, `chirpstack-postgres`,
     `chirpstack-redis`, `mosquitto`, `ingest`, `timescaledb`, and `api` running.
   - `/api/system/status` returns `"mode": "live"` and `"data_source": "timescaledb"`.
   - `/api/buildings/{id}/current` has recent `updated` timestamps after a gateway uplink.
   - Display header shows the sensor source and actual reading freshness.

7. **Document the handover** — the people running this in year 3 will not be
   the people who set it up. Keep `README.md` + `docs/signage-setup.md` current, and
   record where the Linux PC, domain and backups live, along with each
   signage screen's startup URL and recovery settings.
## Production dashboard links

Set `PUBLIC_BASE_URL` to the externally reachable origin, including a published
port when needed, for example `https://dashboard.uis.no` or
`http://SERVER_NETWORK_NAME:8080`. The QR image at `/qr/dashboard.png`, the
visible dashboard link, and `/api/system/status` all use this origin plus
`/overview`. If unset, the app uses the address requested by the browser.
A phone must be able to reach that address; localhost refers to the phone itself.
QR images are generated on the server, with a white quiet zone and no external
image service. Tests independently decode the exact PNG response.

The chart library is bundled under `app/static/vendor/d3` with its license;
production pages do not fetch scripts or fonts from third-party domains.
The API and ingestion containers run as an unprivileged user. The API has a
read-only filesystem, and `/health` returns HTTP 503 when the database cannot
be reached. Caddy waits for API readiness. The API port stays private to the
Compose network; forwarded-header trust assumes requests arrive through Caddy.

Repeated timestamped uplinks are ignored by ingestion using a per-device
transaction lock and an existing-reading lookup. Old duplicate readings are
preserved; this upgrade performs no telemetry deletion. Gateway messages should
include their original network timestamp for repeat detection.

See [`docs/database-schema.md`](docs/database-schema.md) for the schema and
upgrade guarantees. `app/requirements.lock` and `ingest/requirements.lock`
constrain production installs to the exact Linux dependency versions tested
with the isolated stack. Update these constraints deliberately, rebuild, and
rerun the unit and integration checks before deploying dependency changes.
