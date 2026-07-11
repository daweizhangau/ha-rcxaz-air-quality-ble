"""Unit tests for xs_air_quality.protocol — pure logic, no BLE hardware required.

All test packets are taken verbatim from the protocol analysis in
README_ANALYSIS.md.
"""
from __future__ import annotations

import pytest

from custom_components.xs_air_quality.protocol import (
    FRAME_PREFIX,
    ACTIVATION_BYTE,
    PAGE_DATETIME,
    PAGE_ENVIRONMENT,
    PAGE_PARTICULATES,
    PAGE_ACK,
    PAGE_SET_DATETIME,
    SensorReading,
    compute_checksum,
    make_datetime_payload,
    parse_frame,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def frame(hex_str: str) -> bytearray:
    """Convert a compact hex string to a bytearray."""
    return bytearray.fromhex(hex_str)


# ── Known-good frames from README_ANALYSIS.md ─────────────────────────────────
# Each entry: (label, hex_frame, expected_reading_fields)
# expected_reading_fields is a dict of attributes to check on SensorReading

KNOWN_FRAMES = [
    # Page 0x1003 — Datetime / Timestamp
    (
        "datetime_timestamp",
        "23041003000164a4",
        {"timestamp_counter": 1, "page_id": PAGE_DATETIME},
    ),
    # Page 0x1004 (4B) — Environment: temperature + humidity
    (
        "environment_temp_hum",
        "2306100400b400393c",
        {"temperature_c": 18.0, "humidity_pct": 57, "page_id": PAGE_ENVIRONMENT},
    ),
    (
        "environment_temp_hum_2",
        "2306100400b5003a3a",
        {"temperature_c": 18.1, "humidity_pct": 58, "page_id": PAGE_ENVIRONMENT},
    ),
    # Page 0x1004 (6B) — Air quality: CO₂, TVOC, HCHO
    (
        "air_quality_1",
        "23081004019000060002f9",
        {"co2_ppm": 400, "tvoc_mgm3": 0.006, "hcho_mgm3": 0.002, "page_id": PAGE_ENVIRONMENT},
    ),
    (
        "air_quality_2",
        "23081004019e0005000402",
        {"co2_ppm": 414, "tvoc_mgm3": 0.005, "hcho_mgm3": 0.004, "page_id": PAGE_ENVIRONMENT},
    ),
    (
        "air_quality_3",
        "23081004019300070004fb",
        {"co2_ppm": 403, "tvoc_mgm3": 0.007, "hcho_mgm3": 0.004, "page_id": PAGE_ENVIRONMENT},
    ),
    # Page 0x1007 — Particulates: PM1.0, PM2.5, PM10
    (
        "particulates_1",
        "230810070002000600085d",
        {"pm1_0": 2, "pm2_5": 6, "pm10": 8, "page_id": PAGE_PARTICULATES},
    ),
    (
        "particulates_2",
        "230810070003000a000d6b",
        {"pm1_0": 3, "pm2_5": 10, "pm10": 13, "page_id": PAGE_PARTICULATES},
    ),
    # Page 0x0401 — Acknowledgment
    (
        "ack",
        "230504010600003c",
        {"page_id": PAGE_ACK},
    ),
]


# ── parse_frame ────────────────────────────────────────────────────────────────

class TestParseFrame:

    @pytest.mark.parametrize("label,hex_pkt,expected", KNOWN_FRAMES)
    def test_known_frames(self, label, hex_pkt, expected):
        result = parse_frame(frame(hex_pkt))
        assert result is not None, f"{label}: parse_frame returned None"
        for attr, value in expected.items():
            actual = getattr(result, attr)
            if isinstance(value, float):
                assert actual == pytest.approx(value, abs=0.005), (
                    f"{label}: {attr} expected {value}, got {actual}"
                )
            else:
                assert actual == value, f"{label}: {attr} expected {value}, got {actual}"

    def test_returns_none_for_empty(self):
        assert parse_frame(bytearray()) is None

    def test_returns_none_for_wrong_prefix(self):
        assert parse_frame(bytes([0x00, 0x04, 0x10, 0x03, 0x00, 0x01, 0x64])) is None

    def test_returns_none_for_too_short(self):
        assert parse_frame(bytes([0x23, 0x04, 0x10])) is None

    def test_returns_none_for_bad_checksum(self):
        """Frame with wrong checksum is rejected."""
        bad = frame("23041003000164a0")  # last byte should be a4
        assert parse_frame(bad) is None

    def test_accepts_bytearray_and_bytes(self):
        result_bytes = parse_frame(bytes([0x23, 0x04, 0x10, 0x03, 0x00, 0x01, 0x64, 0xa4]))
        result_ba = parse_frame(bytearray([0x23, 0x04, 0x10, 0x03, 0x00, 0x01, 0x64, 0xa4]))
        assert result_bytes is not None
        assert result_ba is not None
        assert result_bytes.timestamp_counter == result_ba.timestamp_counter

    def test_unknown_page_returns_reading_with_page_id(self):
        """An unknown page ID still returns a SensorReading with page_id set."""
        prefix_body = bytes([FRAME_PREFIX, 0x03, 0xFF, 0xFF, 0x01])
        cksum = compute_checksum(prefix_body)
        data = prefix_body + bytes([cksum])
        result = parse_frame(data)
        assert result is not None
        assert result.page_id == 0xFFFF


# ── make_datetime_payload ─────────────────────────────────────────────────────

class TestComputeChecksum:

    def test_datetime_frame(self):
        """Checksum of known datetime frame matches expected."""
        frame = bytes([0x23, 0x09, 0x01, 0x06, 0x26, 0x07, 0x11, 0x00, 0x06, 0x01, 0x06])
        assert compute_checksum(frame) == 0x97

    def test_environment_frame(self):
        frame = bytes([0x23, 0x06, 0x10, 0x04, 0x00, 0xce, 0x00, 0x3d])
        assert compute_checksum(frame) == 0x52

    def test_air_quality_frame(self):
        frame = bytes([0x23, 0x08, 0x10, 0x04, 0x01, 0x93, 0x00, 0x08, 0x00, 0x03])
        assert compute_checksum(frame) == 0x07

    def test_particulates_frame(self):
        frame = bytes([0x23, 0x08, 0x10, 0x07, 0x00, 0x02, 0x00, 0x05, 0x00, 0x0a])
        assert compute_checksum(frame) == 0x60

class TestMakeDatetimePayload:

    def test_frame_structure(self):
        """Payload has correct prefix, length, and page ID."""
        from datetime import datetime
        dt = datetime(2026, 7, 11, 0, 6, 1)
        payload = make_datetime_payload(dt)
        assert payload[0] == FRAME_PREFIX
        assert payload[1] == 9  # body length
        assert payload[2:4] == bytes([0x01, 0x06])  # page ID

    def test_bcd_encoding(self):
        """BCD values are correctly encoded."""
        from datetime import datetime
        # Use a date with unambiguous BCD: 2025-03-15 12:34:56
        dt = datetime(2025, 3, 15, 12, 34, 56)
        payload = make_datetime_payload(dt)
        # Body starts at offset 2
        body = payload[2:]
        assert body[2] == 0x25  # year 25
        assert body[3] == 0x03  # month 03
        assert body[4] == 0x15  # day 15
        assert body[5] == 0x12  # hour 12
        assert body[6] == 0x34  # minute 34
        assert body[7] == 0x56  # second 56

    def test_day_of_week_monday(self):
        from datetime import datetime
        # 2025-01-06 is a Monday
        dt = datetime(2025, 1, 6)
        payload = make_datetime_payload(dt)
        body = payload[2:]
        assert body[8] == 1  # Monday = 1

    def test_day_of_week_sunday(self):
        from datetime import datetime
        # 2025-01-12 is a Sunday
        dt = datetime(2025, 1, 12)
        payload = make_datetime_payload(dt)
        body = payload[2:]
        assert body[8] == 7  # Sunday = 7


# ── ACTIVATION_BYTE ────────────────────────────────────────────────────────────

class TestActivationByte:

    def test_activation_byte_value(self):
        assert ACTIVATION_BYTE == bytes([0x1E])

    def test_activation_byte_length(self):
        assert len(ACTIVATION_BYTE) == 1


# ── SensorReading ──────────────────────────────────────────────────────────────

class TestSensorReading:

    def test_defaults_are_none(self):
        r = SensorReading()
        assert r.temperature_c is None
        assert r.humidity_pct is None
        assert r.co2_ppm is None
        assert r.tvoc_mgm3 is None
        assert r.hcho_mgm3 is None
        assert r.pm1_0 is None
        assert r.pm2_5 is None
        assert r.pm10 is None
        assert r.timestamp_counter is None
        assert r.page_id is None

    def test_is_immutable(self):
        r = SensorReading(temperature_c=22.5)
        with pytest.raises(AttributeError):
            r.temperature_c = 23.0  # frozen dataclass

    def test_merge_readings(self):
        """Simulate merging two partial readings (environment + particulates)."""
        env = SensorReading(temperature_c=22.5, humidity_pct=60, page_id=PAGE_ENVIRONMENT)
        pm  = SensorReading(pm1_0=5, pm2_5=10, pm10=15, page_id=PAGE_PARTICULATES)
        # In practice the coordinator merges these; verify fields are independent
        assert env.temperature_c == 22.5
        assert env.pm1_0 is None
        assert pm.pm1_0 == 5
        assert pm.temperature_c is None
