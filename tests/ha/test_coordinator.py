"""Tests for RCXAZAirQualityCoordinator.

All BLE I/O and HA Bluetooth lookups are mocked — no hardware required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.rcxaz_air_quality.const import DOMAIN
from custom_components.rcxaz_air_quality.coordinator import RCXAZAirQualityCoordinator
from custom_components.rcxaz_air_quality.protocol import SensorReading
from tests.ha.conftest import (
    SAMPLE_ENV_READING,
    SAMPLE_MERGED_READING,
    TEST_ADDRESS,
    TEST_NAME,
)


def _make_entry(options: dict | None = None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.unique_id = TEST_ADDRESS
    entry.title = TEST_NAME
    entry.options = options or {}
    return entry


@pytest.mark.asyncio
async def test_coordinator_setup_connects(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """async_setup() creates a client and connects."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    assert coordinator._client is not None
    mock_ha_client.connect.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_reading_via_callback(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """Coordinator receives data via on_data_updated callback."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    assert coordinator.data is None

    coordinator._on_reading(SAMPLE_ENV_READING)

    assert coordinator.data is not None
    assert coordinator.data.temperature_c == 22.5
    assert coordinator.data.humidity_pct == 60


@pytest.mark.asyncio
async def test_coordinator_health_check_reconnects(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """_async_update_data() reconnects if disconnected."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    mock_ha_client.is_connected = False
    result = await coordinator._async_update_data()

    mock_ha_client.connect.assert_called()
    assert result == SAMPLE_MERGED_READING


@pytest.mark.asyncio
async def test_coordinator_shutdown_disconnects_client(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """async_shutdown() calls disconnect() on the client."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()
        await coordinator.async_shutdown()

    mock_ha_client.disconnect.assert_called_once()
    assert coordinator._client is None


@pytest.mark.asyncio
async def test_coordinator_get_rssi(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """get_rssi() returns the RSSI from the Bluetooth registry."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    rssi = coordinator.get_rssi()
    assert rssi == -72


@pytest.mark.asyncio
async def test_coordinator_client_property(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """client property returns the BLE client."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    assert coordinator.client is mock_ha_client


@pytest.mark.asyncio
async def test_clock_sync_triggers_on_first_health_check(
    hass, mock_ble_device, mock_ha_client, mock_bluetooth,
):
    """sync_clock is called on the very first health check after connect (count=0)."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    await coordinator._async_update_data()

    mock_ha_client.sync_clock.assert_called_once()
    assert coordinator._clock_sync_count == 1


@pytest.mark.asyncio
async def test_clock_sync_triggers_again_after_interval(
    hass, mock_ble_device, mock_ha_client, mock_bluetooth,
):
    """sync_clock is called again after ~120 health checks (~1 hour)."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    # Call 1: count=0 → syncs, count becomes 1
    await coordinator._async_update_data()
    mock_ha_client.sync_clock.assert_called_once()
    assert coordinator._clock_sync_count == 1

    # 119 more calls (Calls 2–120): count goes 1 → 120,
    # 119*30 = 3570 < 3600 → no sync
    for _ in range(119):
        await coordinator._async_update_data()

    assert mock_ha_client.sync_clock.call_count == 1
    assert coordinator._clock_sync_count == 120

    # Call 121: count=120 → 120*30 = 3600 → syncs, count resets to 0, then 1
    await coordinator._async_update_data()
    assert mock_ha_client.sync_clock.call_count == 2
    assert coordinator._clock_sync_count == 1


@pytest.mark.asyncio
async def test_clock_sync_counter_resets_on_reconnect(
    hass, mock_ble_device, mock_ha_client, mock_bluetooth,
):
    """Clock-sync counter resets on reconnect, so sync fires immediately."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    # Call 1: count=0 → syncs, count becomes 1
    await coordinator._async_update_data()
    mock_ha_client.sync_clock.assert_called_once()
    assert coordinator._clock_sync_count == 1

    # Disconnect triggers a reconnect on the next health check.
    # During that same call, count is reset to 0 → sync fires again.
    mock_ha_client.is_connected = False
    await coordinator._async_update_data()  # Call 2: reconnects, count=0 → syncs, count=1
    assert mock_ha_client.sync_clock.call_count == 2  # sync on reconnect too
    assert coordinator._clock_sync_count == 1

    # After reconnect, the mock client is connected again
    mock_ha_client.is_connected = True

    # Call 3: count=1, no sync, count=2
    await coordinator._async_update_data()
    assert mock_ha_client.sync_clock.call_count == 2
    assert coordinator._clock_sync_count == 2

    # 118 more calls (Calls 4–121): count goes 2 → 120,
    # 119*30 = 3570 < 3600 → no sync
    for _ in range(118):
        await coordinator._async_update_data()

    assert mock_ha_client.sync_clock.call_count == 2
    assert coordinator._clock_sync_count == 120

    # Call 122: count=120 → 120*30 = 3600 → syncs, count resets to 1
    await coordinator._async_update_data()
    assert mock_ha_client.sync_clock.call_count == 3
    assert coordinator._clock_sync_count == 1
