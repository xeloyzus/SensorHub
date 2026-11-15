"""Shared helpers for decoding Milesight LoRaWAN uplink payloads.

Every Milesight sensor frames a measurement as three consecutive fields::

    [channel (1 byte)] [type (1 byte)] [data (N bytes)]

The ``(channel, type)`` pair uniquely determines both the data length and its
meaning. Multi-byte values are little-endian (confirmed by the official decoder
examples, e.g. temperature bytes ``18 01`` -> 0x0118 -> 280 -> 28.0 °C).
"""

from collections.abc import Iterator

# A spec entry is (data_length, metric_name, divisor, signed).
Spec = dict[tuple[int, int], tuple[int, str, int, bool]]

# Fixed-length metadata supported by the official AM103/CT305 decoders.
# Skip only known lengths; guessing the size of an unknown record is unsafe.
METADATA_LENGTHS = {
    (0xFF, 0x01): 1,  # protocol version
    (0xFF, 0x09): 2,  # hardware version
    (0xFF, 0x0A): 2,  # firmware version
    (0xFF, 0xFF): 2,  # TSL version
    (0xFF, 0x16): 8,  # serial number
    (0xFF, 0x0F): 1,  # LoRaWAN class
    (0xFF, 0xFE): 1,  # reset event
    (0xFF, 0x0B): 1,  # device status
}


def iter_fields(
    payload: bytes, spec: Spec, metadata_lengths: dict[tuple[int, int], int] | None = None
) -> Iterator[tuple[int, int, bytes]]:
    """Yield ``(channel, type, data)`` for each record in ``payload``.

    Iteration stops at the first unknown record or a truncated payload, because
    in both cases the remaining record lengths can no longer be determined.
    """
    metadata_lengths = METADATA_LENGTHS if metadata_lengths is None else metadata_lengths
    i, n = 0, len(payload)
    while i + 1 < n:
        key = (payload[i], payload[i + 1])
        entry = spec.get(key)
        if entry is None:
            length = metadata_lengths.get(key)
            if length is not None and i + 2 + length <= n:
                i += 2 + length
                continue
            return
        start, end = i + 2, i + 2 + entry[0]
        if end > n:
            return
        yield key[0], key[1], payload[start:end]
        i = end


def read_int(data: bytes, signed: bool = False) -> int:
    """Read ``data`` as a little-endian integer."""
    return int.from_bytes(data, "little", signed=signed)
