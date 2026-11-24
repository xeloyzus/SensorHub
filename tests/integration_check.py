"""Exercise real MQTT -> decoder -> TimescaleDB -> API in the test stack.

Run inside its ingest container; refuse any database except the dedicated
integration database. Payloads and device registrations are synthetic.
"""

import base64
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

import paho.mqtt.client as mqtt
import psycopg

HOST = "mosquitto"
EUI = "24e1241200000001"
AM107_EUI = "24e1241200000005"
TOPIC = f"application/1/device/{EUI}/event/up"
GATEWAY_PASSWORD = "integration-gateway-only"
READER_PASSWORD = os.environ["MQTT_PASSWORD"]


def eventually(check, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except OSError:
            pass  # Services may still be binding sockets immediately after up.
        time.sleep(0.2)
    raise AssertionError(description)


@contextmanager
def client(username=None, password=None, rejected=False):
    connected = threading.Event()
    reasons = []
    connection = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    if username:
        connection.username_pw_set(username, password)

    def on_connect(_client, _data, _flags, reason, _properties):
        reasons.append(reason)
        connected.set()

    connection.on_connect = on_connect
    eventually(lambda: connection.connect(HOST, 1883) == mqtt.MQTT_ERR_SUCCESS, "Broker did not start listening")
    connection.loop_start()
    try:
        assert connected.wait(5), "MQTT connection callback timed out"
        assert reasons[0].is_failure == rejected, f"Unexpected MQTT connection result: {reasons[0]}"
        yield connection
    finally:
        connection.disconnect()
        connection.loop_stop()


def publish(connection, topic, payload, denied=False):
    completed = threading.Event()
    reasons = []

    def on_publish(_client, _data, _mid, reason, _properties):
        reasons.append(reason)
        completed.set()

    connection.on_publish = on_publish
    result = connection.publish(topic, payload, qos=1)
    assert result.rc == mqtt.MQTT_ERR_SUCCESS
    assert completed.wait(5), "MQTT publish acknowledgement timed out"
    assert reasons[0].is_failure == denied, f"Unexpected publish authorization: {reasons[0]}"


def api(path):
    with urlopen("http://api:8000" + path, timeout=10) as response:
        return json.load(response)


def verify_timestamped_report_freshness(db):
    """Reproduce two 31-hour stale sensors plus ten missing, then deliver samples.

    This archived synthetic building is never included in campus summaries.
    Everything runs inside the guarded disposable integration database.
    """
    building_id = db.execute(
        "INSERT INTO buildings (name,slug,is_active) VALUES "
        "('Timestamped regression','timestamped-regression',FALSE) "
        "ON CONFLICT (slug) DO UPDATE SET is_active=FALSE RETURNING id"
    ).fetchone()[0]
    devices = []
    for index in range(12):
        eui = f"24e12412{256+index:08x}"
        device_id = db.execute(
            "INSERT INTO devices (eui,building_id,type,label) VALUES (%s,%s,'am103',%s) "
            "ON CONFLICT (eui) DO UPDATE SET is_active=TRUE RETURNING id",
            (eui, building_id, f"Timestamped regression {index+1}"),
        ).fetchone()[0]
        devices.append((eui, device_id))
    ids = [device_id for _, device_id in devices]
    db.execute("DELETE FROM readings WHERE device_id=ANY(%s)", (ids,))
    now = datetime.now(timezone.utc)
    old_time = (now-timedelta(minutes=1884)).replace(microsecond=0)
    try:
        for _, device_id in devices[:2]:
            for metric, value in (("co2", 894), ("temperature", 19.1), ("humidity", 45)):
                db.execute("INSERT INTO readings (time,device_id,metric,value) VALUES (%s,%s,%s,%s)",
                           (old_time, device_id, metric, value))
        path = f"/api/buildings/{building_id}/summary"
        before = api(path)
        assert before['data_quality']['active_sensors'] == 0
        assert before['data_quality']['stale_sensors'] == 2
        assert before['data_quality']['missing_sensors'] == 10
        assert before['data_quality']['freshness']['age_minutes'] == 1884
        assert before['data_quality']['freshness']['metric'] == 'co2'
        assert before['data_quality']['freshness']['device_label'].startswith('Timestamped regression')
        assert before['data_quality']['freshness']['received_at'] is not None

        def packet(eui, sample_time, event_time):
            frame = (b'\x20\xce' + int(sample_time.timestamp()).to_bytes(4, 'little')
                     + bytes.fromhex('e1005abc02'))
            return json.dumps({'deviceInfo': {'devEui': eui}, 'time': old_time.isoformat(),
                               'rxInfo': [{'gwTime': old_time.isoformat(), 'nsTime': event_time.isoformat()}],
                               'data': base64.b64encode(frame).decode()})

        sample_time = (now-timedelta(minutes=5)).replace(microsecond=0)
        with client('sensorhub-gateway', GATEWAY_PASSWORD) as gateway:
            # Regular periodic reports can carry a gateway time 31 hours behind
            # while ChirpStack's NS receipt metadata is current. These are not
            # sensor history blocks: the stable network timestamp must win.
            periodic_time = now-timedelta(minutes=10)
            def deliver_periodic_reports():
                for eui, _ in devices[:2]:
                    payload = json.dumps({
                        'deviceInfo': {'devEui': eui}, 'time': old_time.isoformat(),
                        'rxInfo': [{'gwTime': old_time.isoformat(), 'nsTime': periodic_time.isoformat()}],
                        'data': base64.b64encode(bytes.fromhex('0175640367e10004685a077dbc02')).decode(),
                    })
                    publish(gateway, f'application/1/device/{eui}/event/up', payload)
                return api(path)['data_quality']['active_sensors'] == 2
            eventually(deliver_periodic_reports, 'Backdated gateway time incorrectly kept periodic reports stale', timeout=35)
            assert api(path)['data_quality']['stale_sensors'] == 0
            assert api(path)['co2']['current'] == 700
            for _, device_id in devices[:2]:
                assert db.execute('SELECT count(*) FROM readings WHERE device_id=%s AND time=%s',
                                  (device_id, periodic_time)).fetchone()[0] == 4
            def deliver_current_samples():
                for eui, _ in devices[:2]:
                    publish(gateway, f'application/1/device/{eui}/event/up', packet(eui, sample_time, now))
                return api(path)['data_quality']['active_sensors'] == 2
            eventually(deliver_current_samples, 'Timestamped AM103 measurements did not clear false stale status', timeout=35)
            after = api(path)
            assert after['data_quality']['stale_sensors'] == 0
            assert after['data_quality']['missing_sensors'] == 10
            assert after['co2']['current'] == 700
            assert after['temperature']['current'] == 22.5
            # Re-delivering the same sample in a later network event is idempotent.
            for eui, _ in devices[:2]:
                publish(gateway, f'application/1/device/{eui}/event/up', packet(eui, sample_time, now+timedelta(seconds=1)))
            # An old replay is retained as history without becoming current data.
            history_time = (now-timedelta(days=2)).replace(microsecond=0)
            eui, device_id = devices[0]
            publish(gateway, f'application/1/device/{eui}/event/up', packet(eui, history_time, now))
            eventually(lambda: db.execute('SELECT count(*) FROM readings WHERE device_id=%s AND time=%s',
                       (device_id, history_time)).fetchone()[0] == 3, 'Historical sample was not persisted')
        for _, device_id in devices[:2]:
            assert db.execute('SELECT count(*) FROM readings WHERE device_id=%s AND time=%s',
                              (device_id, sample_time)).fetchone()[0] == 3
            assert db.execute('SELECT max(time) FROM readings WHERE device_id=%s', (device_id,)).fetchone()[0] == sample_time
        assert api(path)['data_quality']['stale_sensors'] == 0
        print('PASS: 1884-minute stale reproduction; NS receive time fixes backdated periodic reports; historical samples keep their own age', flush=True)
    finally:
        db.execute('DELETE FROM readings WHERE device_id=ANY(%s)', (ids,))
        db.execute('UPDATE devices SET is_active=FALSE WHERE id=ANY(%s)', (ids,))


def run():
    with psycopg.connect(os.environ["ADMIN_DATABASE_URL"], autocommit=True) as db:
        if db.execute("SELECT current_database()").fetchone()[0] != "sensorhub_integration":
            raise RuntimeError("Refusing to write to a non-test database")
        assert db.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'").fetchone()
        assert db.execute("SELECT to_regclass('readings_hourly')").fetchone()[0]
        assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
        verify_timestamped_report_freshness(db)
        # Keep deployment registry rows, while isolating these smoke-test sensors
        # from the seeded active fleet. This is a disposable test database.
        db.execute("UPDATE devices SET is_active = FALSE WHERE label NOT LIKE 'Integration %'")
        active = dict(db.execute("SELECT slug, id FROM buildings WHERE is_active").fetchall())
        assert set(active) == {"kjolv-egelands-hus", "arne-rettedals-hus", "eoj", "sis"}
        building_id = active['eoj']
        inventory = api('/api/sensor-models')
        planned = {'am103': 12, 'am107': 0, 'ct305': 0}
        for model in inventory:
            assert model['planned_quantity'] == planned[model['type']]
        print("PASS: TimescaleDB migrations and hourly aggregate initialize", flush=True)

        devices = [
            (EUI, "am103", "Integration fresh"),
            ("24e1241200000002", "am103", "Integration stale"),
            ("24e1241200000003", "am103", "Integration silent"),
            ("24e1241200000004", "ct305", "Integration panel"),
            (AM107_EUI, "am107", "Integration AM107"),
        ]
        for eui, kind, label in devices:
            target_building = active['sis'] if kind == 'am107' else building_id
            db.execute("INSERT INTO devices (eui, building_id, type, label) VALUES (%s, %s, %s, %s) ON CONFLICT (eui) DO NOTHING", (eui, target_building, kind, label))
        ids = dict(db.execute("SELECT eui, id FROM devices WHERE label LIKE 'Integration %'").fetchall())
        # Make repeated smoke checks deterministic inside this guarded test DB.
        db.execute("DELETE FROM readings WHERE device_id = ANY(%s)", (list(ids.values()),))

        with client(rejected=True):
            pass
        with client("sensorhub-gateway", "wrong-password", rejected=True):
            pass
        print("PASS: anonymous and incorrect credentials are rejected", flush=True)

        with client("sensorhub-ingest", READER_PASSWORD) as reader:
            publish(reader, TOPIC, "{}", denied=True)
            with client("sensorhub-gateway", GATEWAY_PASSWORD) as gateway:
                reader_ready, gateway_ready = threading.Event(), threading.Event()
                reader_message, gateway_message = threading.Event(), threading.Event()
                reader.on_subscribe = lambda *_args: reader_ready.set()
                gateway.on_subscribe = lambda *_args: gateway_ready.set()
                reader.on_message = lambda *_args: reader_message.set()
                gateway.on_message = lambda *_args: gateway_message.set()
                reader.subscribe(TOPIC, qos=1)
                gateway.subscribe(TOPIC, qos=1)
                assert reader_ready.wait(5) and gateway_ready.wait(5)
                publish(gateway, TOPIC, '{"integration_marker":true}')
                assert reader_message.wait(5), "Reader account cannot receive authorized telemetry"
                assert not gateway_message.wait(0.5), "Write-only gateway received sensor traffic"
        with client("sensorhub-gateway", GATEWAY_PASSWORD) as gateway:
            publish(gateway, "unrelated/telemetry", "{}", denied=True)
            payload = json.dumps({"devEUI": EUI, "data": base64.b64encode(bytes.fromhex("ff01010175640367d200046850077d4c04")).decode(), "time": datetime.now(timezone.utc).isoformat()})
            def initial_uplink():
                # Ingest subscribes at QoS 0. Repeat this startup probe until
                # its subscription has reconnected after a broker restart;
                # this check does not claim durable delivery during outages.
                publish(gateway, TOPIC, payload)
                return db.execute("SELECT count(DISTINCT metric) FROM readings WHERE device_id=%s", (ids[EUI],)).fetchone()[0] == 4

            eventually(initial_uplink, "An authorized uplink did not produce its four metrics", timeout=35)
            original_time = json.loads(payload)["time"]
            publish(gateway, TOPIC, payload)
            publish(gateway, TOPIC, payload)
            # Malformed messages must not kill the real ingestion process.
            for malformed in ["[]", '{"devEUI":"bad","data":42}', "not-json"]:
                publish(gateway, TOPIC, malformed)
            payload = json.dumps({"deviceInfo": {"devEui": EUI}, "data": base64.b64encode(bytes.fromhex("ff0901000367dc00046850077d4c04")).decode(), "time": datetime.now(timezone.utc).isoformat()})
            publish(gateway, TOPIC, payload)
            eventually(lambda: db.execute("SELECT value FROM readings WHERE device_id=%s AND metric='temperature' ORDER BY time DESC LIMIT 1", (ids[EUI],)).fetchone()[0] == 22, "Ingestion did not survive malformed messages")
            assert db.execute("SELECT count(*) FROM readings WHERE device_id=%s AND time=%s", (ids[EUI], original_time)).fetchone()[0] == 4
        print("PASS: repeated uplinks do not duplicate readings", flush=True)
        print("PASS: role ACLs, metadata decoding, and malformed-message recovery", flush=True)

        with client('sensorhub-gateway', GATEWAY_PASSWORD) as gateway:
            payload = json.dumps({'deviceInfo': {'devEui': AM107_EUI}, 'data': base64.b64encode(bytes.fromhex('0175640367dc00046850056a050006655e0190013200077d4c04087d780009739427')).decode(), 'time': datetime.now(timezone.utc).isoformat()})
            publish(gateway, f'application/1/device/{AM107_EUI}/event/up', payload)
            eventually(lambda: db.execute('SELECT count(DISTINCT metric) FROM readings WHERE device_id=%s', (ids[AM107_EUI],)).fetchone()[0] == 10, 'AM107 did not store all ten metrics')
        am107_current = api(f"/api/buildings/{active['sis']}/current")['sensors'][0]
        assert am107_current['type'] == 'am107'
        assert am107_current['readings']['activity'] == 5
        assert am107_current['readings']['illumination'] == 350
        assert am107_current['readings']['pressure'] == 1013.2
        assert api(f"/api/buildings/{active['sis']}/summary")['co2']['current'] == 1100
        assert any(item['metric'] == 'activity' for item in api(f"/api/buildings/{active['sis']}/history?range=24h")['series'])
        assert next(model for model in api('/api/sensor-models') if model['type'] == 'am107')['registered_quantity'] == 1
        print('PASS: AM107 MQTT decoding, database persistence, inventory, history, and climate analytics', flush=True)

        now = datetime.now(timezone.utc)
        stale_id = ids["24e1241200000002"]
        panel_id = ids["24e1241200000004"]
        with db.transaction():
            for metric, value in {"co2": 2400, "temperature": 30, "humidity": 60}.items():
                db.execute("INSERT INTO readings (time, device_id, metric, value) VALUES (%s, %s, %s, %s)", (now-timedelta(hours=2), stale_id, metric, value))
            for metric, value in {"temperature": 80, "current_1": 0, "current_2": 0, "current_3": 0}.items():
                db.execute("INSERT INTO readings (time, device_id, metric, value) VALUES (%s, %s, %s, %s)", (now, panel_id, metric, value))

        eventually(lambda: api("/api/system/status")["mode"] == "live", "API did not enter live mode")
        current = api(f"/api/buildings/{building_id}/current")
        assert len(current["sensors"]) == 4
        assert next(sensor for sensor in current["sensors"] if sensor["label"] == "Integration silent")["updated"] is None
        assert next(sensor for sensor in current["sensors"] if sensor["label"] == "Integration fresh")["readings"]["temperature"] == 22
        result = api(f"/api/buildings/{building_id}/summary")
        assert result["co2"]["current"] == 1100
        assert result["temperature"]["current"] == 22
        assert result["energy"]["current_kw"] == 0
        assert result["data_quality"]["stale_sensors"] == 1
        assert result["data_quality"]["missing_sensors"] == 1
        assert result["recommendations"] == []
        assert api(f"/api/buildings/{building_id}/history?range=24h")["series"]
        assert api("/api/campus/summary")["co2"]["current"] == 1100
        print("PASS: real SQL/API handle silent sensors, stale readings, panel temperature, and zero current", flush=True)
        db.execute("CALL refresh_continuous_aggregate('readings_hourly', now()-interval '3 hours', now()-interval '1 hour')")
        assert db.execute("SELECT avg FROM readings_hourly WHERE device_id=%s AND metric='co2'", (stale_id,)).fetchone()[0] == 2400
        print("PASS: hourly continuous aggregate materializes real sensor history", flush=True)

        # Establish a fully current building, then insert same-sensor sustained
        # evidence using real 15-minute buckets instead of mocked history.
        with db.transaction():
            for device_id in (stale_id, ids["24e1241200000003"]):
                for metric, value in {"co2": 1100, "temperature": 22, "humidity": 40}.items():
                    db.execute("INSERT INTO readings (time, device_id, metric, value) VALUES (%s, %s, %s, %s)", (now, device_id, metric, value))
            for age in (60, 45, 30, 15):
                db.execute("INSERT INTO readings (time, device_id, metric, value) VALUES (%s, %s, 'co2', 1100)", (now-timedelta(minutes=age), ids[EUI]))
        result = api(f"/api/buildings/{building_id}/summary")
        assert result["data_quality"]["freshness"]["status"] == "current"
        assert result["recommendations"], "Sustained evidence did not produce a recommendation"
        recommendation = result["recommendations"][0]
        assert recommendation["methodology_id"] == "co2-v2"
        assert recommendation["evidence"]["sustained_minutes"] >= 45
        assert recommendation["evidence"]["device_ids"] == [ids[EUI]]
        print("PASS: live recommendations require sustained same-sensor evidence", flush=True)
        for path in ("/", "/mobile", "/overview"):
            with urlopen("http://api:8000" + path, timeout=10) as response:
                assert response.status == 200
                assert b"Campus dashboard" in response.read()
        print("PASS: display, mobile, and overview routes render in live mode", flush=True)
        for invalid in (float('nan'), float('inf'), float('-inf')):
            try:
                with db.transaction():
                    db.execute("INSERT INTO readings (time, device_id, metric, value) VALUES (now(), %s, 'co2', %s)", (ids[EUI], invalid))
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise AssertionError("Database accepted a non-finite reading")
        try:
            with db.transaction():
                db.execute("INSERT INTO devices (eui, building_id, type, label) VALUES ('invalid', %s, 'am103', 'Invalid EUI')", (building_id,))
        except psycopg.errors.CheckViolation:
            pass
        else:
            raise AssertionError("Database accepted an invalid EUI")
        print("PASS: database rejects non-finite values and malformed device IDs", flush=True)


if __name__ == "__main__":
    run()
