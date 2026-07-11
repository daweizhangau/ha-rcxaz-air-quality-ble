"""Shared fixtures for HA integration tests.

Uses ``pytest-homeassistant-custom-component`` which provides the
``hass`` fixture and the full HA test infrastructure without needing a
running HA instance.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import mock_config_flow

import custom_components.xs_air_quality.config_flow as _cf_module
from custom_components.xs_air_quality.config_flow import XSAirQualityConfigFlow
from custom_components.xs_air_quality.const import C760_SERVICE_UUID, DOMAIN
from custom_components.xs_air_quality.protocol import SensorReading

# ---------------------------------------------------------------------------
# Sample readings
# ---------------------------------------------------------------------------

SAMPLE_ENV_READING = SensorReading(
    temperature_c=22.5,
    humidity_pct=60,
    page_id=0x1004,
)

SAMPLE_AIR_READING = SensorReading(
    co2_ppm=400,
    tvoc_mgm3=0.006,
    hcho_mgm3=0.002,
    page_id=0x1004,
)

SAMPLE_PM_READING = SensorReading(
    pm1_0=5,
    pm2_5=10,
    pm10=15,
    page_id=0x1007,
)

SAMPLE_MERGED_READING = SensorReading(
    temperature_c=22.5,
    humidity_pct=60,
    co2_ppm=400,
    tvoc_mgm3=0.006,
    hcho_mgm3=0.002,
    pm1_0=5,
    pm2_5=10,
    pm10=15,
    page_id=0x1004,
)

# ---------------------------------------------------------------------------
# Device stub
# ---------------------------------------------------------------------------

TEST_ADDRESS = "C1:07:F3:65:DA:75"
TEST_NAME    = "XS-1234"


@pytest.fixture
def mock_ble_device() -> BLEDevice:
    """Return a fake BLEDevice for the detector."""
    device = MagicMock(spec=BLEDevice)
    device.address = TEST_ADDRESS
    device.name    = TEST_NAME
    return device


# ---------------------------------------------------------------------------
# XSAirQualityHAClient stub
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ha_client(mock_ble_device: BLEDevice) -> AsyncMock:
    """Return an AsyncMock that replaces XSAirQualityHAClient."""
    client = AsyncMock()
    client.is_connected      = True
    client.connection_status = "Connected"
    client.last_seen_at      = None
    client.last_reading      = SAMPLE_MERGED_READING
    client.connect           = AsyncMock()
    client.disconnect        = AsyncMock()
    client.update_ble_device = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Bluetooth registry stub
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bluetooth(mock_ble_device: BLEDevice):
    """Patch the HA bluetooth lookups used by the coordinator."""
    service_info = MagicMock()
    service_info.rssi = -72
    with (
        patch(
            "custom_components.xs_air_quality.coordinator.bluetooth.async_ble_device_from_address",
            return_value=mock_ble_device,
        ),
        patch(
            "custom_components.xs_air_quality.coordinator.bluetooth.async_last_service_info",
            return_value=service_info,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Config-flow test helper
# ---------------------------------------------------------------------------

@contextmanager
def flow_ctx(hass: HomeAssistant) -> Iterator[None]:
    """Context manager that makes the xs_air_quality config flow findable by HA's loader."""
    if not hasattr(hass, 'data'):
        # In some test harness versions, hass is passed as an async generator
        # that hasn't been fully resolved yet. Do nothing in that case.
        with mock_config_flow(DOMAIN, XSAirQualityConfigFlow), patch(
            "homeassistant.config_entries._support_single_config_entry_only",
            return_value=False,
        ):
            yield
        return
    hass.data.setdefault("components", {})["xs_air_quality.config_flow"] = _cf_module
    with mock_config_flow(DOMAIN, XSAirQualityConfigFlow), patch(
        "homeassistant.config_entries._support_single_config_entry_only",
        return_value=False,
    ):
        yield
    hass.data["components"].pop("xs_air_quality.config_flow", None)


def make_bluetooth_service_info(
    address: str = TEST_ADDRESS,
    name: str = TEST_NAME,
    service_uuids: list[str] | None = None,
) -> MagicMock:
    """Create a mock BluetoothServiceInfoBleak."""
    if service_uuids is None:
        service_uuids = [C760_SERVICE_UUID]
    info = MagicMock()
    info.address = address
    info.name = name
    info.service_uuids = service_uuids
    return info
