"""Tests for the Milesight payload decoders (pure functions, no I/O)."""

from datetime import datetime, timedelta, timezone

from ingest.decoders import am103_decoder, am107_decoder, ct305_decoder, decode, decode_samples


def test_am103_full_example():
    # Official example: 017564 03671801 04686D 077DC501
    result = am103_decoder.decode(bytes.fromhex("0175640367180104686D077DC501"))
    assert result == {
        "battery": 100.0,
        "temperature": 28.0,
        "humidity": 54.5,
        "co2": 453.0,
    }


def test_am103_timestamped_history_uses_embedded_time_and_continues_into_live_data():
    event_time = datetime(2026, 11, 24, 22, tzinfo=timezone.utc)
    sample_time = event_time-timedelta(minutes=5)
    history = b"\x20\xce" + int(sample_time.timestamp()).to_bytes(4, "little") + bytes.fromhex("e1005abc02")
    payload = history + bytes.fromhex("ff1800030175640367dc00046850077d4c04")
    samples = decode_samples(payload, "am103", event_time)
    assert samples == [
        (sample_time, {"temperature": 22.5, "humidity": 45, "co2": 700}),
        (event_time, {"battery": 100, "temperature": 22, "humidity": 40, "co2": 1100}),
    ]
    # Flat callers get only live fields; historical values never masquerade as live.
    assert decode(payload, "am103") == samples[-1][1]


def test_old_retransmission_is_not_assigned_the_new_uplink_time():
    event_time = datetime(2026, 11, 24, 22, tzinfo=timezone.utc)
    sample_time = event_time-timedelta(hours=31, minutes=24)
    history = b"\x20\xce" + int(sample_time.timestamp()).to_bytes(4, "little") + bytes.fromhex("e1005abc02")
    assert decode_samples(history, "am103", event_time)[0][0] == sample_time


def test_multiple_history_records_keep_separate_sample_times():
    now = datetime(2026, 11, 24, 22, tzinfo=timezone.utc)
    times = [now-timedelta(minutes=30), now-timedelta(minutes=15)]
    payload = b"".join(b"\x20\xce" + int(t.timestamp()).to_bytes(4, "little") + bytes.fromhex("e1005abc02") for t in times)
    assert [t for t, _ in decode_samples(payload, "am103", now)] == times


def test_ct305_total_current():
    assert ct305_decoder.decode(bytes.fromhex("039710270000")) == {"total_1": 100.0}


def test_ct305_current():
    assert ct305_decoder.decode(bytes.fromhex("0499B80B")) == {"current_1": 300.0}


def test_ct305_read_failed_sentinel_is_skipped():
    # 0xFFFF means the sensor could not read the channel -> omit it.
    assert ct305_decoder.decode(bytes.fromhex("0499FFFF")) == {}


def test_ct305_temperature():
    assert ct305_decoder.decode(bytes.fromhex("09671801")) == {"temperature": 28.0}


def test_ct305_combined_uplink():
    result = ct305_decoder.decode(
        bytes.fromhex(
            "0397102700000499B80B0597102700000699D0070797102700000899C40909671801"
        )
    )
    assert result == {
        "total_1": 100.0,
        "current_1": 300.0,
        "total_2": 100.0,
        "current_2": 200.0,
        "total_3": 100.0,
        "current_3": 250.0,
        "temperature": 28.0,
    }


def test_empty_payloads_do_not_raise():
    assert am103_decoder.decode(b"") == {}
    assert am107_decoder.decode(b"") == {}
    assert ct305_decoder.decode(b"") == {}


def test_metadata_before_and_between_am103_measurements():
    result = am103_decoder.decode(bytes.fromhex("ff0101017564ff0901000367180104686d077dc501"))
    assert result == {"battery": 100, "temperature": 28, "humidity": 54.5, "co2": 453}


def test_ct305_metadata_does_not_hide_current():
    assert ct305_decoder.decode(bytes.fromhex("ff0a01000499b80b")) == {"current_1": 300}


def test_truncated_metadata_and_unknown_records_stop_safely():
    assert am103_decoder.decode(bytes.fromhex("ff16abcd")) == {}
    assert am103_decoder.decode(bytes.fromhex("ffaa0000777dc501")) == {}


def test_am107_all_measurements_and_decoder_dispatch():
    payload = bytes.fromhex(
        "0175640367dc00046850056a050006655e0190013200077d4c04087d780009739427"
    )
    assert decode(payload, "am107") == {
        "battery": 100, "temperature": 22, "humidity": 40, "activity": 5,
        "illumination": 350, "infrared_and_visible": 400, "infrared": 50,
        "co2": 1100, "tvoc": 120, "pressure": 1013.2,
    }


def test_am107_metadata_does_not_hide_climate_after_light_record():
    payload = bytes.fromhex("ff08010203040506ff18007f056a00000665000000000000077d00000367cbff")
    assert am107_decoder.decode(payload) == {
        "activity": 0, "illumination": 0, "infrared_and_visible": 0,
        "infrared": 0, "co2": 0, "temperature": -5.3,
    }


def test_am107_truncated_light_and_unknown_metadata_stop_safely():
    assert am107_decoder.decode(bytes.fromhex("01756406650102030405")) == {"battery": 100}
    assert am107_decoder.decode(bytes.fromhex("ff08010203")) == {}
    assert am107_decoder.decode(bytes.fromhex("ffaa0000077d4c04")) == {}
