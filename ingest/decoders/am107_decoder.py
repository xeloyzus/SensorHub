"""Decode AM107 telemetry, including its PIR counter and six-byte light record.

Protocol reference:
https://github.com/Milesight-IoT/SensorDecoders/blob/main/am-series/am107/am107-decoder.js
PIR activity is a numeric activity counter, not a head count or occupied flag.
"""

from .common import METADATA_LENGTHS, Spec, iter_fields, read_int

FIELDS: Spec = {
    (0x01, 0x75): (1, "battery", 1, False),
    (0x03, 0x67): (2, "temperature", 10, True),
    (0x04, 0x68): (1, "humidity", 2, False),
    (0x05, 0x6A): (2, "activity", 1, False),
    (0x06, 0x65): (6, "illumination", 1, False),
    (0x07, 0x7D): (2, "co2", 1, False),
    (0x08, 0x7D): (2, "tvoc", 1, False),
    (0x09, 0x73): (2, "pressure", 10, False),
}

AM107_METADATA_LENGTHS = {
    **METADATA_LENGTHS,
    (0xFF, 0x08): 6,  # older six-byte serial number
    (0xFF, 0x18): 2,  # enabled-sensor configuration
}


def decode(payload: bytes) -> dict[str, float]:
    result: dict[str, float] = {}
    for channel, kind, data in iter_fields(payload, FIELDS, AM107_METADATA_LENGTHS):
        if (channel, kind) == (0x06, 0x65):
            for offset, metric in enumerate(("illumination", "infrared_and_visible", "infrared")):
                result[metric] = float(read_int(data[offset * 2:offset * 2 + 2]))
        else:
            _, metric, divisor, signed = FIELDS[(channel, kind)]
            result[metric] = read_int(data, signed) / divisor
    return result
