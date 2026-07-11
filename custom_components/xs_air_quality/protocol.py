"""Pure protocol logic for the XS- air quality detector.

All functions here are free of I/O and fully unit-testable without hardware.

Frame format (ATT Handle Value Notification on C761):
  [0]     0x23       prefix byte
  [1]     N          payload length
  [2:4]   page ID    big-endian
  [4:4+N-2] payload  page-specific data
  [4+N-1] checksum   index-XOR algorithm (see compute_checksum)

Checksum algorithm (reverse-engineered from the Android app):
  total = sum(byte[i] ^ i) for i = 0..len(frame)-2
  checksum = total & 0xFF
  The checksum is computed over ALL bytes except the checksum byte itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ── Frame constants ───────────────────────────────────────────────────────────
FRAME_PREFIX = 0x23
ACTIVATION_BYTE = bytes([0x1E])

# Page IDs
PAGE_DATETIME      = 0x1003  # Timestamp / counter
PAGE_ENVIRONMENT   = 0x1004  # Temp+humidity (4B) or CO₂+TVOC+HCHO (6B)
PAGE_PARTICULATES  = 0x1007  # PM1.0, PM2.5, PM10
PAGE_ACK           = 0x0401  # Acknowledgment
PAGE_SET_DATETIME  = 0x0106  # Set datetime command


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_checksum(frame: bytes) -> int:
    """Compute the frame checksum using the index-XOR algorithm.

    Algorithm (reverse-engineered from the Android app's app-service.js):
        total = sum(byte[i] ^ i) for i = 0..len(frame)-1
        checksum = total & 0xFF

    The checksum is computed over ALL bytes of the frame *except* the
    checksum byte itself.  When building a frame, pass the bytes before
    the checksum position.  When validating, pass frame[:-1].
    """
    return sum(b ^ i for i, b in enumerate(frame)) & 0xFF


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SensorReading:
    """A single parsed measurement from the XS- air quality detector.

    All sensor fields default to None when not present in the frame.
    """

    # Environment (page 0x1004, 4-byte payload)
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None

    # Air quality (page 0x1004, 6-byte payload)
    co2_ppm: Optional[int] = None
    tvoc_mgm3: Optional[float] = None  # mg/m³
    hcho_mgm3: Optional[float] = None  # mg/m³ (formaldehyde)

    # Particulates (page 0x1007)
    pm1_0: Optional[int] = None   # µg/m³
    pm2_5: Optional[int] = None   # µg/m³
    pm10: Optional[int] = None    # µg/m³

    # Timestamp (page 0x1003)
    timestamp_counter: Optional[int] = None

    # Raw page ID that produced this reading (for debugging)
    page_id: Optional[int] = None


# ── Command builder ───────────────────────────────────────────────────────────

def make_datetime_payload(now: Optional[datetime] = None) -> bytes:
    """Build a page 0x0106 frame to set the device's internal clock.

    The device expects BCD-encoded date/time fields and a day-of-week value
    (1=Monday .. 7=Sunday).
    """
    if now is None:
        now = datetime.now()

    # Day of week: Python weekday() Mon=0 .. Sun=6 → device expects Mon=1 .. Sun=7
    dow = now.weekday() + 1

    # BCD encoding: each nibble is a decimal digit
    year_bcd  = (now.year % 100 // 10) << 4 | (now.year % 10)
    month_bcd = (now.month // 10) << 4 | (now.month % 10)
    day_bcd   = (now.day // 10) << 4 | (now.day % 10)
    hour_bcd  = (now.hour // 10) << 4 | (now.hour % 10)
    min_bcd   = (now.minute // 10) << 4 | (now.minute % 10)
    sec_bcd   = (now.second // 10) << 4 | (now.second % 10)

    body = bytes([
        0x01, 0x06,  # page ID
        year_bcd, month_bcd, day_bcd,
        hour_bcd, min_bcd, sec_bcd,
        dow,
    ])
    frame_prefix = bytes([FRAME_PREFIX, len(body)])
    cksum = compute_checksum(frame_prefix + body)
    return frame_prefix + body + bytes([cksum])


# ── Packet parser ──────────────────────────────────────────────────────────────

def parse_frame(data: bytes | bytearray) -> Optional[SensorReading]:
    """Parse a notification frame into a SensorReading.

    Returns None if the data is invalid (wrong prefix, bad length, bad checksum).
    """
    if not data or len(data) < 4:
        return None

    if data[0] != FRAME_PREFIX:
        return None

    length = data[1]
    # Minimum body: 2 bytes (page_id) + 0 payload → 4 total + 1 checksum
    if len(data) < 2 + length + 1:
        return None

    # Validate checksum (computed over all bytes except the last)
    if compute_checksum(bytes(data[:-1])) != data[-1]:
        return None

    body = data[2:2 + length]
    page_id = (body[0] << 8) | body[1]
    payload = body[2:]

    # --- Ack page ---
    if page_id == PAGE_ACK:
        return SensorReading(page_id=page_id)

    # --- Datetime / Timestamp page ---
    if page_id == PAGE_DATETIME:
        value = int.from_bytes(payload[:2], "big") if len(payload) >= 2 else None
        return SensorReading(timestamp_counter=value, page_id=page_id)

    # --- Environment / Air quality page ---
    if page_id == PAGE_ENVIRONMENT:
        if len(payload) == 4:
            temp = int.from_bytes(payload[:2], "big") / 10.0
            hum  = int.from_bytes(payload[2:4], "big")
            return SensorReading(
                temperature_c=temp,
                humidity_pct=hum,
                page_id=page_id,
            )
        if len(payload) == 6:
            co2  = int.from_bytes(payload[:2], "big")
            tvoc = int.from_bytes(payload[2:4], "big") / 1000.0
            hcho = int.from_bytes(payload[4:6], "big") / 1000.0
            return SensorReading(
                co2_ppm=co2,
                tvoc_mgm3=tvoc,
                hcho_mgm3=hcho,
                page_id=page_id,
            )
        return SensorReading(page_id=page_id)

    # --- Particulates page ---
    if page_id == PAGE_PARTICULATES:
        values = [
            int.from_bytes(payload[i:i + 2], "big")
            for i in range(0, len(payload) - (len(payload) % 2), 2)
        ]
        pm1  = values[0] if len(values) >= 1 else None
        pm25 = values[1] if len(values) >= 2 else None
        pm10 = values[2] if len(values) >= 3 else None
        return SensorReading(pm1_0=pm1, pm2_5=pm25, pm10=pm10, page_id=page_id)

    return SensorReading(page_id=page_id)
