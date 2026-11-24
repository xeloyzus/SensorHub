# Grafana device readings

Grafana reads the TimescaleDB database that the ingest service already writes.
The data path remains:

```text
UG65 → ChirpStack → MQTT → SensorHub ingest → TimescaleDB → Grafana
```

The stack provisions a **SensorHub · Live Device Readings** dashboard and a
PostgreSQL/TimescaleDB data source automatically. The dashboard opens on the
last hour, refreshes every 10 seconds, graphs the selected metric from all
devices, shows the latest stored value and timestamp for each registered
device/metric, and counts devices with readings in the selected range. Use the
Metric selector to graph CO2, temperature, humidity, battery, or another metric
that has been received. The latest-values table is independent of the chart
time range and includes registered devices that have no stored readings, plus
sensors whose most recent report is older than one hour. Use Grafana's time
picker when you want to revisit older periods; that does not change the live
one-hour default.

Grafana is published only on the server's loopback interface at port `3200`.
On the server PC, open `http://localhost:3200`. From another PC, create an SSH
tunnel:

```bash
ssh -L 3200:localhost:3200 server@SERVER_ADDRESS
```

Then open `http://localhost:3200` locally. Sign in with `GRAFANA_ADMIN_USER`
and `GRAFANA_ADMIN_PASSWORD` from the private `.env` file.

Grafana connects as `grafana_reader`, a separate PostgreSQL role that receives
SELECT-only access. The migration runner creates or updates that role and its
grants. The generated `GRAFANA_DB_PASSWORD` is separate from the database
owner's password. Do not share `.env` or expose port 3200 to the public
internet.

The same read-only account can be used in DBeaver on the server's loopback
PostgreSQL port (`POSTGRES_PORT`, default 5432). API and ingestion have their own
restricted accounts; the database owner is reserved for schema administration.

`readings` retains raw data for 90 days. Grafana queries that table directly;
the existing `readings_hourly` aggregate remains available for longer-term
reports. An empty live chart means no selected-metric rows arrived inside the
selected time range; the latest-values table still shows the newest stored row
for every known device/metric.
