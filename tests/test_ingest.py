"""Gateway validation tests use real paho/psycopg imports without a broker."""

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

import psycopg

from ingest.main import Database, WriteBuffer, handle_message, main, on_connect, parse_message


def uplink(**changes):
    data = {"devEUI": "24E124128B123456", "data": base64.b64encode(bytes.fromhex("077dc501")).decode(), "time": datetime.now(timezone.utc).isoformat()}
    data.update(changes)
    return json.dumps(data).encode()


def test_v3_message_normalizes_eui_and_timezone():
    eui, payload, timestamp = parse_message(uplink(time="2020-01-01T12:00:00+02:00"))
    assert eui == "24e124128b123456"
    assert payload == bytes.fromhex("077dc501")
    assert timestamp == datetime(2020, 1, 1, 10, tzinfo=timezone.utc)


def test_v4_device_info_uses_stable_network_time():
    eui, _, timestamp = parse_message(uplink(devEUI=None, deviceInfo={"devEui": "24e124128b123456"}, time="2020-01-01T12:00:00+02:00"))
    assert eui == "24e124128b123456"
    assert timestamp == datetime(2020, 1, 1, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("timestamp", [None, ""])
def test_missing_time_is_rejected_instead_of_creating_duplicate_receipt_times(timestamp):
    with pytest.raises(ValueError, match="time"):
        parse_message(uplink(time=timestamp))


def test_buffer_discards_invalid_uplink_without_blocking_other_devices():
    buffer = WriteBuffer()
    now = datetime.now(timezone.utc)
    buffer.add([(now, 1, "humidity", 200), (now, 1, "co2", 700)])
    buffer.add([(now, 2, "co2", 800)])
    db = Mock()
    db.execute_in_transaction.side_effect = [psycopg.errors.CheckViolation(), None]
    assert buffer.flush(db)
    assert len(buffer) == 0
    assert db.execute_in_transaction.call_count == 2


def test_invalid_live_payload_is_not_retried_or_buffered():
    db, registry = Mock(), Mock()
    registry.get.return_value = (1, "am103")
    db.execute_in_transaction.side_effect = psycopg.errors.CheckViolation()
    buffer = WriteBuffer()
    handle_message(db, registry, SimpleNamespace(payload=uplink(), topic="test"), buffer)
    assert len(buffer) == 0
    registry.clear.assert_called_once()


def test_transient_database_failure_preserves_uplink_for_replay():
    db, registry = Mock(), Mock()
    registry.get.return_value = (1, "am103")
    db.execute_in_transaction.side_effect = psycopg.OperationalError()
    buffer = WriteBuffer()
    handle_message(db, registry, SimpleNamespace(payload=uplink(), topic="test"), buffer)
    assert len(buffer) == 1


def test_timestamped_am103_report_is_written_with_its_sample_time():
    event_time = datetime.now(timezone.utc)
    sample_time = (event_time-timedelta(minutes=5)).replace(microsecond=0)
    frame = b"\x20\xce" + int(sample_time.timestamp()).to_bytes(4, "little") + bytes.fromhex("e1005abc02")
    db, registry, conn = Mock(), Mock(), MagicMock()
    registry.get.return_value = (1, "am103")
    db.execute_in_transaction.side_effect = lambda statement: statement(conn)
    handle_message(db, registry, SimpleNamespace(payload=uplink(
        data=base64.b64encode(frame).decode(), time=event_time.isoformat()), topic="test"))
    rows = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    assert rows == [(sample_time, 1, "temperature", 22.5),
                    (sample_time, 1, "humidity", 45), (sample_time, 1, "co2", 700)]


def test_expired_history_does_not_hide_live_fields_in_same_packet():
    old_time = datetime.now(timezone.utc)-timedelta(days=100)
    frame = b"\x20\xce" + int(old_time.timestamp()).to_bytes(4, "little") + bytes.fromhex("e1005abc02077dc501")
    db, registry, conn = Mock(), Mock(), MagicMock()
    registry.get.return_value = (1, "am103")
    db.execute_in_transaction.side_effect = lambda statement: statement(conn)
    handle_message(db, registry, SimpleNamespace(payload=uplink(data=base64.b64encode(frame).decode()), topic="test"))
    rows = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    assert len(rows) == 1 and rows[0][2:] == ("co2", 453)


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
