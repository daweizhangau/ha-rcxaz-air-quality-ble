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
async def test_coordinator_setup_creates_client(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
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
async def test_coordinator_data_updated_via_callback(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """Coordinator receives data via the client's on_data_updated callback."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    # Initially no data
    assert coordinator.data is None

    # Simulate the client firing the data callback
    coordinator._on_client_data_updated(SAMPLE_ENV_READING)

    assert coordinator.data is not None
    assert coordinator.data.temperature_c == 22.5
    assert coordinator.data.humidity_pct == 60


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
async def test_coordinator_async_update_data_returns_reading(hass, mock_ble_device, mock_ha_client, mock_bluetooth):
    """_async_update_data() returns the client's last reading."""
    entry = _make_entry()

    with patch(
        "custom_components.rcxaz_air_quality.coordinator.RCXAZAirQualityHAClient",
        return_value=mock_ha_client,
    ):
        coordinator = RCXAZAirQualityCoordinator(hass, entry)
        await coordinator.async_setup()

    result = await coordinator._async_update_data()
    assert result == SAMPLE_MERGED_READING


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
