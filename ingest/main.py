"""MQTT -> TimescaleDB ingest service.

Subscribes to the gateway MQTT broker, decodes Milesight uplinks, and writes
one row per metric to the ``readings`` table.

Expected message format (ChirpStack-style JSON, as published by the UG65's
embedded network server)::

    {"devEUI": "...", "data": "<base64 frame payload>", "time": "..."}

Both ChirpStack v3 (``devEUI`` at top level) and v4 (``deviceInfo.devEui``)
are supported; the base64 payload is always in ``data``.
"""

import base64
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import psycopg

if __package__:
    from .decoders import decode_samples
else:
    from decoders import decode_samples

log = logging.getLogger("ingest")

DATABASE_URL = os.environ["DATABASE_URL"]
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "application/+/device/+/event/up")
MAX_SAMPLE_AGE = timedelta(days=88)  # Inside the baseline's 89-day aggregate refresh.
MAX_FUTURE_SKEW = timedelta(minutes=5)


class Database:
    """A single persistent connection that reconnects transparently."""

    def __init__(self) -> None:
        self._conn: psycopg.Connection | None = None

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(DATABASE_URL, autocommit=True)
        return self._conn

    def reset(self) -> None:
        """Close the failed connection; reconnect lazily on the next lookup."""
        try:
            if self._conn is not None:
                self._conn.close()
        except psycopg.Error:
            pass
        self._conn = None

    def execute_in_transaction(self, statement_factory) -> None:
        """Run ``statement_factory(conn)`` inside one transaction.

        Retries a bounded number of times when the connection fails mid-write
        (e.g. a transient database restart), so a brief outage does not
        silently drop uplinks that MQTT has already acknowledged.
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                with self.conn.transaction():
                    statement_factory(self.conn)
                return
            except (psycopg.OperationalError, psycopg.InterfaceError,
                    psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                self.reset()
                if attempts >= 3:
                    raise
                time.sleep(min(2 ** (attempts - 1), 5))


# Registry entries are re-read from the database after this many seconds, so
# device edits (retirement, relabeling, re-homing) propagate without a restart.
REGISTRY_TTL_SECONDS = float(os.environ.get("REGISTRY_TTL_SECONDS", "300"))


class DeviceRegistry:
    """In-memory cache of DevEUI -> (device_id, device_type) with a TTL.

    Entries expire so registry changes made through ChirpStack provisioning or
    SQL migrations take effect while ingest keeps running. Unregistered
    devices are *not* cached: a device registered after startup is picked up
    by its very next uplink.
    """

    def __init__(self, db: Database, ttl: float = REGISTRY_TTL_SECONDS) -> None:
        self._db = db
        self._ttl = ttl
        self._cache: dict[str, tuple[float, tuple[int, str]]] = {}

    def get(self, eui: str) -> tuple[int, str] | None:
        """Return (device_id, type) for ``eui``, or None if unregistered."""
        now = time.monotonic()
        entry = self._cache.get(eui)
        if entry is not None and now - entry[0] < self._ttl:
            return entry[1]
        row = self._db.conn.execute(
            "SELECT id, type FROM devices WHERE eui = %s AND is_active", (eui,)
        ).fetchone()
        if row is None:
            # Do not cache misses — registration must take effect immediately.
            self._cache.pop(eui, None)
            return None
        device = (row[0], row[1])
        self._cache[eui] = (now, device)
        return device

    def clear(self) -> None:
        self._cache.clear()


def parse_message(payload: bytes) -> tuple[str, bytes, datetime]:
    """Extract ``(dev_eui, frame_payload, timestamp)`` from a gateway message.

    Raises ``ValueError``/``KeyError`` on anything that is not a valid uplink.
    """
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("message must be a JSON object")

    raw = data.get("data")
    if not isinstance(raw, str) or not raw:
        raise ValueError("message must have a nonempty base64 'data' string")

    # DevEUI lives in different places across ChirpStack v3 and v4.
    device_info = data.get("deviceInfo")
    if device_info is None:
        device_info = {}
    if not isinstance(device_info, dict):
        raise ValueError("deviceInfo must be an object")
    eui = device_info.get("devEui") or data.get("devEUI") or data.get("devEui")
    if not isinstance(eui, str) or re.fullmatch(r"[0-9a-fA-F]{16}", eui) is None:
        raise ValueError("devEUI must contain 16 hexadecimal characters")

    # A stable network timestamp is required for idempotency. Synthesizing 'now'
    # would turn every retransmission into a different measurement.
    iso = data.get("time")
    if not isinstance(iso, str) or not iso:
        raise ValueError("time must be an ISO timestamp")
    ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))

    if ts.tzinfo is None:
        raise ValueError("time must include a timezone")
    ts = ts.astimezone(timezone.utc)
    if ts - datetime.now(timezone.utc) > MAX_FUTURE_SKEW:
        raise ValueError("time is more than five minutes in the future")
    frame = base64.b64decode(raw, validate=True)
    if not frame:
        raise ValueError("decoded payload is empty")
    return eui.lower(), frame, ts


class WriteBuffer:
    """Bounded FIFO of decoded uplinks waiting to be persisted.

    When the database is unreachable after the write path's own retries, the
    message goes here instead of being dropped. ``flush`` replays buffered
    rows in arrival order; if the buffer overflows, the oldest rows are lost
    (and logged) so ingest keeps consuming fresh telemetry.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._rows: deque[tuple] = deque(maxlen=maxlen)
        self.dropped = 0

    def __len__(self) -> int:
        return len(self._rows)

    def add(self, rows: list[tuple]) -> None:
        overflow = len(self._rows) + len(rows) - self._rows.maxlen
        if overflow > 0:
            for _ in range(overflow):
                self._rows.popleft()
            self.dropped += overflow
            log.error("Write buffer full; discarded %d oldest reading rows", overflow)
        self._rows.extend(rows)

    def flush(self, db: Database) -> bool:
        """Try to persist all buffered rows. Returns True when the buffer is empty."""
        while self._rows:
            # Replay one uplink at a time. A retired device or invalid payload
            # must not poison the entire buffer and block unrelated sensors.
            key = self._rows[0][:2]
            batch = []
            for row in self._rows:
                if row[:2] != key:
                    break
                batch.append(row)
            try:
                db.execute_in_transaction(_insert_rows(batch))
            except (psycopg.IntegrityError, psycopg.DataError):
                self.dropped += len(batch)
                log.warning("Discarding %d buffered rows rejected by database constraints", len(batch))
            except psycopg.Error:
                log.warning("Still unable to flush %d buffered rows", len(batch))
                return False
            # Only remove what we actually wrote (add() may have extended it).
            written = min(len(batch), len(self._rows))
            for _ in range(written):
                self._rows.popleft()
        return True


def _insert_rows(rows: list[tuple]):
    def statement(conn):
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO readings (time, device_id, metric, value) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (device_id, metric, time) DO NOTHING",
                rows,
            )
    return statement


def handle_message(db: Database, registry: DeviceRegistry, msg: mqtt.MQTTMessage,
                   buffer: WriteBuffer | None = None) -> None:
    """Decode and persist an uplink; skip malformed or unknown messages."""
    try:
        eui, frame, ts = parse_message(msg.payload)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        log.warning("Rejected uplink on %s: %s", msg.topic, exc)
        return

    try:
        device = registry.get(eui)
    except psycopg.Error:
        log.exception("Database lookup failed for %s; reconnecting", eui)
        db.reset()
        registry.clear()
        return

    if device is None:
        log.warning("Unregistered device %s on %s — skipping", eui, msg.topic)
        return

    device_id, device_type = device
    try:
        samples = decode_samples(frame, device_type, ts)
    except ValueError as exc:
        log.warning("Decode skipped for %s (%s): %s", eui, device_type, exc)
        return
    if not samples:
        log.info("No supported measurements decoded for %s (%s, %d payload bytes)", eui, device_type, len(frame))
        return

    now = datetime.now(timezone.utc)
    rows = []
    for sample_time, metrics in samples:
        if not now - MAX_SAMPLE_AGE <= sample_time <= now + MAX_FUTURE_SKEW:
            log.warning("Skipped sample for %s at %s: outside the 88-day/five-minute ingestion window", eui, sample_time.isoformat())
            continue
        rows.extend((sample_time, device_id, metric, value) for metric, value in metrics.items())
    if not rows:
        return

    try:
        db.execute_in_transaction(_insert_rows(rows))
    except (psycopg.IntegrityError, psycopg.DataError) as exc:
        registry.clear()
        log.warning("Database rejected telemetry for %s (SQLSTATE %s): %s", eui, exc.sqlstate, exc.diag.message_primary)
        return
    except psycopg.Error:
        log.exception("Insert failed for device %s after retries", device_id)
        if buffer is not None:
            buffer.add(rows)
            log.warning("Buffered %d rows for device %s (%d pending)",
                        len(rows), device_id, len(buffer))
        return

    if buffer is not None and len(buffer):
        # The database answered again; keep buffered history ordered ahead of
        # any newer uplink that arrives next.
        try:
            buffer.flush(db)
        except psycopg.Error:
            pass

    log.info("%s (%s): processed %d metric rows across %d sample timestamps; newest=%s", eui, device_type,
             len(rows), len({row[0] for row in rows}), max(row[0] for row in rows).isoformat())


def on_subscribe(client, userdata, mid, reason_code_list, properties) -> None:
    if any(code.is_failure for code in reason_code_list):
        log.error("MQTT subscription rejected for topic %s: %s", MQTT_TOPIC, reason_code_list)
    else:
        log.info("MQTT subscription confirmed for topic %s", MQTT_TOPIC)


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
    """(Re)subscribe to the uplink topic and flush any buffered rows."""
    if reason_code.is_failure:
        log.error("MQTT connection rejected: %s", reason_code)
        return
    client.subscribe(MQTT_TOPIC)
    db, registry, buffer = userdata
    if len(buffer):
        log.info("Broker reachable; flushing %d buffered rows", len(buffer))
        try:
            buffer.flush(db)
        except psycopg.Error:
            log.exception("Buffered rows remain unpersisted; retrying on next message")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    db, registry, buffer = userdata
    if len(buffer):
        # Opportunistically replay buffered rows before ingesting new ones so
        # history stays in order once the database recovers.
        try:
            buffer.flush(db)
        except psycopg.Error:
            pass
    handle_message(db, registry, msg, buffer)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database()
    registry = DeviceRegistry(db)
    buffer = WriteBuffer(maxlen=int(os.environ.get("WRITE_BUFFER_ROWS", "1000")))

    # CallbackAPIVersion.VERSION2 is the modern paho-mqtt 2.x API.
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=(db, registry, buffer))
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")
    if not username or not password:
        raise RuntimeError("MQTT_USERNAME and MQTT_PASSWORD are required")
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    # Reconnect with backoff if the broker is temporarily unreachable.
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    log.info(
        "Ingest starting: host=%s port=%s topic=%s",
        MQTT_HOST, MQTT_PORT, MQTT_TOPIC,
    )
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()  # blocks and handles MQTT reconnects internally


if __name__ == "__main__":
    main()
