"""Gateway validation tests use real paho/psycopg imports without a broker."""

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ingest.main import Database, handle_message, main, on_connect, parse_message


def uplink(**changes):
    data = {"devEUI": "24E124128B123456", "data": base64.b64encode(bytes.fromhex("077dc501")).decode(), "time": "2020-01-01T12:00:00+02:00"}
    data.update(changes)
    return json.dumps(data).encode()


def test_v3_message_normalizes_eui_and_timezone():
    eui, payload, timestamp = parse_message(uplink())
    assert eui == "24e124128b123456"
    assert payload == bytes.fromhex("077dc501")
    assert timestamp == datetime(2020, 1, 1, 10, tzinfo=timezone.utc)


def test_v4_device_info_and_missing_time():
    before = datetime.now(timezone.utc)
    eui, _, timestamp = parse_message(uplink(devEUI=None, deviceInfo={"devEui": "24e124128b123456"}, time=None))
    assert eui == "24e124128b123456"
    assert before <= timestamp <= datetime.now(timezone.utc)


@pytest.mark.parametrize("payload", [b"[]", b"null", b"not-json", uplink(data=123), uplink(data="invalid!"), uplink(data=""), uplink(deviceInfo=[]), uplink(deviceInfo="invalid"), uplink(devEUI="wrong"), uplink(time=123), uplink(time="2020-01-01T12:00:00"), uplink(time=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())])
def test_malformed_uplinks_do_not_escape_callback(payload):
    db, registry = Mock(), Mock()
    handle_message(db, registry, SimpleNamespace(payload=payload, topic="test"))
    registry.get.assert_not_called()
    db.reset.assert_not_called()


def test_rejected_connection_does_not_subscribe():
    client = Mock()
    on_connect(client, None, None, SimpleNamespace(is_failure=True), None)
    client.subscribe.assert_not_called()


def test_reset_does_not_attempt_immediate_database_reconnection(monkeypatch):
    connect = Mock(side_effect=RuntimeError("Database is still offline"))
    monkeypatch.setattr("ingest.main.psycopg.connect", connect)
    db = Database()
    db.reset()
    connect.assert_not_called()


def test_ingestion_authenticates_before_connecting(monkeypatch):
    client = Mock()
    monkeypatch.setattr("ingest.main.mqtt.Client", Mock(return_value=client))
    monkeypatch.setenv("MQTT_USERNAME", "sensorhub-ingest")
    monkeypatch.setenv("MQTT_PASSWORD", "test-only-password")
    main()
    client.username_pw_set.assert_called_once_with("sensorhub-ingest", "test-only-password")
    assert client.on_message is not None
    client.connect.assert_called_once()


def test_ingestion_refuses_missing_credentials(monkeypatch):
    client = Mock()
    monkeypatch.setattr("ingest.main.mqtt.Client", Mock(return_value=client))
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="MQTT_USERNAME and MQTT_PASSWORD"):
        main()
    client.connect.assert_not_called()
