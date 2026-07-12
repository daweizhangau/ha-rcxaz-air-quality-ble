"""Tests for RCXAZAirQualityHAClient (ha_client.py).

All BLE operations are mocked — no hardware or bleak install required
(as long as bleak is importable).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice

from custom_components.rcxaz_air_quality.ha_client import RCXAZAirQualityHAClient
from custom_components.rcxaz_air_quality.protocol import (
    ACTIVATION_BYTE,
    SensorReading,
)
from tests.ha.conftest import (
    TEST_ADDRESS,
    TEST_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ble_device() -> MagicMock:
    dev = MagicMock(spec=BLEDevice)
    dev.address = TEST_ADDRESS
    dev.name    = TEST_NAME
    return dev


def _make_bleak_client(mock_write: AsyncMock | None = None) -> MagicMock:
    """Return a fake BleakClientWithServiceCache."""
    client = MagicMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.disconnect = AsyncMock()
    client.write_gatt_char = mock_write or AsyncMock()
    return client


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_subscribes_to_notifications():
    """connect() subscribes to C761 notifications."""
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()

    await client.disconnect()

    from custom_components.rcxaz_air_quality.const import C761_NOTIFY_UUID
    bleak_client.start_notify.assert_called_once()
    args, _ = bleak_client.start_notify.call_args
    assert args[0] == C761_NOTIFY_UUID


@pytest.mark.asyncio
async def test_connect_sends_activation_and_time_sync():
    """connect() sends activation byte and datetime sync to C762."""
    ble_device = _make_ble_device()
    write_mock = AsyncMock()
    bleak_client = _make_bleak_client(write_mock)

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()

    await client.disconnect()

    from custom_components.rcxaz_air_quality.const import C762_WRITE_UUID

    # First write should be activation byte
    activation_call = write_mock.call_args_list[0]
    assert activation_call[0][0] == C762_WRITE_UUID
    assert activation_call[0][1] == ACTIVATION_BYTE

    # Second write should be datetime sync
    time_sync_call = write_mock.call_args_list[1]
    assert time_sync_call[0][0] == C762_WRITE_UUID
    # Verify it's a valid datetime payload
    payload = time_sync_call[0][1]
    assert payload[0] == 0x23  # frame prefix


@pytest.mark.asyncio
async def test_disconnect_stops_notify_and_disconnects():
    """disconnect() stops notifications and disconnects."""
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()
        await client.disconnect()

    from custom_components.rcxaz_air_quality.const import C761_NOTIFY_UUID
    # stop_notify is called twice: once in connect() to clear stale subscriptions,
    # and once in disconnect()
    assert bleak_client.stop_notify.call_count >= 1
    bleak_client.stop_notify.assert_any_call(C761_NOTIFY_UUID)
    bleak_client.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Notification handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notification_parses_and_stores_reading():
    """_on_notification parses frames and stores the reading."""
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()
    captured_readings: list[SensorReading] = []

    def on_data(reading: SensorReading) -> None:
        captured_readings.append(reading)

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device, on_data_updated=on_data)
        await client.connect()

        # Simulate an environment notification
        env_frame = bytes.fromhex("2306100400b400393c")
        client._on_notification(None, bytearray(env_frame))

        await client.disconnect()

    assert len(captured_readings) == 1
    assert captured_readings[0].temperature_c == 18.0
    assert captured_readings[0].humidity_pct == 57


@pytest.mark.asyncio
async def test_notification_merges_with_previous():
    """Notifications from different pages are merged into one reading."""
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()
    captured_readings: list[SensorReading] = []

    def on_data(reading: SensorReading) -> None:
        captured_readings.append(reading)

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device, on_data_updated=on_data)
        await client.connect()

        # Simulate environment notification
        env_frame = bytes.fromhex("2306100400b400393c")
        client._on_notification(None, bytearray(env_frame))

        # Simulate air quality notification
        air_frame = bytes.fromhex("23081004019000060002f9")
        client._on_notification(None, bytearray(air_frame))

        await client.disconnect()

    # After two notifications, the merged reading should have both env and air data
    assert len(captured_readings) == 2
    merged = captured_readings[1]
    assert merged.temperature_c == 18.0
    assert merged.humidity_pct == 57
    assert merged.co2_ppm == 400
    assert merged.tvoc_mgm3 == 0.006
    assert merged.hcho_mgm3 == 0.002


@pytest.mark.asyncio
async def test_notification_ignores_invalid_frames():
    """Invalid frames are silently ignored."""
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()
    captured_readings: list[SensorReading] = []

    def on_data(reading: SensorReading) -> None:
        captured_readings.append(reading)

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device, on_data_updated=on_data)
        await client.connect()

        # Send an invalid frame (wrong prefix)
        client._on_notification(None, bytearray(b"\x00\x04\x10\x03\x00\x01\x64"))

        await client.disconnect()

    assert len(captured_readings) == 0


# ---------------------------------------------------------------------------
# connection_status property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_status_connected():
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()

    from custom_components.rcxaz_air_quality.const import CONN_STATUS_CONNECTED
    assert client.connection_status == CONN_STATUS_CONNECTED
    await client.disconnect()


@pytest.mark.asyncio
async def test_connection_status_disconnected():
    ble_device = _make_ble_device()
    client = RCXAZAirQualityHAClient(ble_device)

    from custom_components.rcxaz_air_quality.const import CONN_STATUS_DISCONNECTED
    assert client.connection_status == CONN_STATUS_DISCONNECTED


# ---------------------------------------------------------------------------
# last_seen_at property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_seen_at_none_before_notification():
    ble_device = _make_ble_device()
    client = RCXAZAirQualityHAClient(ble_device)
    assert client.last_seen_at is None


@pytest.mark.asyncio
async def test_last_seen_at_set_after_notification():
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()

        assert client.last_seen_at is None

        # Simulate a notification
        env_frame = bytes.fromhex("2306100400b400393c")
        client._on_notification(None, bytearray(env_frame))

        await client.disconnect()

        assert client.last_seen_at is not None


# ---------------------------------------------------------------------------
# last_reading property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_reading_none_before_notification():
    ble_device = _make_ble_device()
    client = RCXAZAirQualityHAClient(ble_device)
    assert client.last_reading is None


@pytest.mark.asyncio
async def test_last_reading_set_after_notification():
    ble_device = _make_ble_device()
    bleak_client = _make_bleak_client()

    with patch(
        "custom_components.rcxaz_air_quality.ha_client.establish_connection",
        AsyncMock(return_value=bleak_client),
    ), patch("asyncio.sleep", AsyncMock()):
        client = RCXAZAirQualityHAClient(ble_device)
        await client.connect()

        env_frame = bytes.fromhex("2306100400b400393c")
        client._on_notification(None, bytearray(env_frame))

        await client.disconnect()

        assert client.last_reading is not None
        assert client.last_reading.temperature_c == 18.0


# ---------------------------------------------------------------------------
# _merge_readings
# ---------------------------------------------------------------------------

class TestMergeReadings:

    def test_merge_keeps_base_fields(self):
        base = SensorReading(temperature_c=22.5, humidity_pct=60)
        update = SensorReading(co2_ppm=400, page_id=0x1004)
        merged = RCXAZAirQualityHAClient._merge_readings(base, update)
        assert merged.temperature_c == 22.5
        assert merged.humidity_pct == 60
        assert merged.co2_ppm == 400

    def test_merge_overwrites_with_update(self):
        base = SensorReading(temperature_c=22.5, humidity_pct=60)
        update = SensorReading(temperature_c=23.0, page_id=0x1004)
        merged = RCXAZAirQualityHAClient._merge_readings(base, update)
        assert merged.temperature_c == 23.0
        assert merged.humidity_pct == 60
