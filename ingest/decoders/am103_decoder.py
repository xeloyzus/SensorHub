"""Decode a Milesight AM103 (indoor air quality) LoRaWAN uplink payload.

Spec source:
https://github.com/Milesight-IoT/SensorDecoders/tree/main/am-series/am103
"""

from datetime import datetime, timezone

from .common import METADATA_LENGTHS, Spec, iter_fields, read_int

# (channel, type) -> (length, metric, divisor, signed)
FIELDS: Spec = {
    (0x01, 0x75): (1, "battery",     1,  False),   # %
    (0x03, 0x67): (2, "temperature", 10, True),    # °C   (int16 / 10)
    (0x04, 0x68): (1, "humidity",    2,  False),   # %RH  (uint8 / 2)
    (0x07, 0x7D): (2, "co2",         1,  False),   # ppm  (uint16)
    (0x20, 0xCE): (9, "history", 1, False),
}

AM103_METADATA_LENGTHS = {**METADATA_LENGTHS, (0xFF, 0x18): 2}


def decode(payload: bytes) -> dict[str, float]:
    """Decode ``payload`` into a flat ``{metric: value}`` mapping."""
    result: dict[str, float] = {}
    for channel, kind, data in iter_fields(payload, FIELDS, AM103_METADATA_LENGTHS):
        if (channel, kind) == (0x20, 0xCE):
            continue  # Flat callers cannot represent the record's separate time.
        _, metric, divisor, signed = FIELDS[(channel, kind)]
        result[metric] = read_int(data, signed) / divisor
    return result


def decode_samples(payload: bytes, event_time: datetime) -> list[tuple[datetime, dict[str, float]]]:
    """Preserve each history record's sample time; live fields use event time.

    A retransmitted historical sample must never acquire the uplink's new time.
    History records may precede live fields or contain multiple sample times.
    """
    samples = []
    live = {}
    for channel, kind, data in iter_fields(payload, FIELDS, AM103_METADATA_LENGTHS):
        if (channel, kind) == (0x20, 0xCE):
            timestamp = datetime.fromtimestamp(read_int(data[:4]), timezone.utc)
            samples.append((timestamp, {
                "temperature": read_int(data[4:6], signed=True) / 10,
                "humidity": data[6] / 2,
                "co2": float(read_int(data[7:9])),
            }))
        else:
            _, metric, divisor, signed = FIELDS[(channel, kind)]
            live[metric] = read_int(data, signed) / divisor
    if live:
        samples.append((event_time, live))
    return samples
