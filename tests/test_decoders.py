"""Tests for the Milesight payload decoders (pure functions, no I/O)."""

from ingest.decoders import am103_decoder, am107_decoder, ct305_decoder, decode


def test_am103_full_example():
    # Official example: 017564 03671801 04686D 077DC501
    result = am103_decoder.decode(bytes.fromhex("0175640367180104686D077DC501"))
    assert result == {
        "battery": 100.0,
        "temperature": 28.0,
        "humidity": 54.5,
        "co2": 453.0,
    }


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
