"""Grafana is provisioned against the real telemetry database."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_grafana_dashboard_defaults_to_live_all_device_readings():
    dashboard = json.loads((ROOT / "grafana/dashboards/device-readings.json").read_text())
    assert dashboard["time"] == {"from": "now-1h", "to": "now"}
    assert dashboard["refresh"] == "10s"
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    live_title = next(title for title in panels if title.startswith("Live readings by device"))
    latest_query = panels["Latest stored value for every device and metric"]["targets"][0]["rawSql"]
    assert "LEFT JOIN LATERAL" in latest_query
    assert "FROM devices" in latest_query and "JOIN buildings" in latest_query
    assert "$__timeFilter" not in latest_query
    assert "No readings stored" in latest_query
    live_query = panels[live_title]["targets"][0]["rawSql"]
    assert "$__timeFilter(r.time)" in live_query
    assert "${metric:sqlstring}" in live_query


def test_grafana_uses_internal_read_only_database_login():
    datasource = (ROOT / "grafana/provisioning/datasources/sensorhub.yaml").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    migrator = (ROOT / "app/db/migrate.py").read_text()
    assert "url: timescaledb:5432" in datasource
    assert "user: $GRAFANA_DB_USER" in datasource
    assert "password: $GRAFANA_DB_PASSWORD" in datasource
    assert "GRAFANA_DB_PASSWORD: ${GRAFANA_DB_PASSWORD" in compose
    assert "./grafana/provisioning:/etc/grafana/provisioning:ro" in compose
    assert "CREATE ROLE" in migrator and "GRANT SELECT ON ALL TABLES" in migrator
