"""Live BLE connection test for RCXAZAirQualityHAClient.

⚠️  Skipped by default — only runs with ``pytest --live`` (and one of
``--device-address``, ``--device-name``, or ``--auto``).

Connects to the physical device, streams data for ``--duration`` seconds
(default: 30), then disconnects.

Usage::

    pytest --live --auto
    pytest --live --device-address C1:07:F3:65:DA:75 --duration 60
    pytest --live --device-name XS-1234
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pytest
from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from custom_components.rcxaz_air_quality.ha_client import RCXAZAirQualityHAClient
from custom_components.rcxaz_air_quality.protocol import SensorReading

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StatusCapture:
    """Records status-change timestamps from the client callback."""

    def __init__(self) -> None:
        self.changes: list[datetime] = []

    def on_status_changed(self) -> None:
        self.changes.append(datetime.now())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
async def live_device(request: pytest.FixtureRequest) -> Optional[BLEDevice]:
    """Resolve the BLE device from CLI options (module-scoped).

    The returned BLEDevice is a lightweight wrapper — on macOS CoreBluetooth
    it is safe to pass it to BleakClient on a different event loop within
    the same module scope.
    """
    address = request.config.getoption("--device-address")
    name = request.config.getoption("--device-name")
    auto_scan = request.config.getoption("--auto")

    # use `address` directly if given, bypassing BleakScanner on the
    # fixture's event loop.  If BleakScanner is used, convert to an
    # address-only BLEDevice so the same peripheral object isn't reused
    # across loops.
    if address:
        return BLEDevice(address, name or "RCXAZ-Air", {})

    if name:
        device = await BleakScanner.find_device_by_name(name, timeout=10)
        if device is None:
            pytest.skip(f"Device named '{name}' not found")
        return BLEDevice(device.address, name, {})

    if auto_scan:
        _LOGGER.info("Scanning for 10 s to discover nearby BLE devices …")
        devices = await BleakScanner.discover(timeout=10)
        _LOGGER.info("Discovered %d devices", len(devices))
        for d in devices:
            rssi = getattr(d, 'rssi', None)
            _LOGGER.info("  %s  %s  (rssi=%s)", d.address, d.name or "(no name)", rssi)
            if d.name and "XS" in d.name:
                _LOGGER.info("→ Matched device: %s @ %s", d.name, d.address)
                return d
        _LOGGER.warning("No device with 'XS' in name found among %d devices", len(devices))
        return None

    return None


@pytest.fixture(scope="module")
def test_duration(request: pytest.FixtureRequest) -> int:
    """Return the test duration in seconds."""
    return request.config.getoption("--duration")


# ---------------------------------------------------------------------------
# Live connection test
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_connection(
    live_device: Optional[BLEDevice],
    test_duration: int,
) -> None:
    """Connect to a physical device, stream readings, then disconnect."""
    if live_device is None:
        pytest.skip("No BLE device found — specify --device-address, --device-name, or --auto")

    reading_count = 0

    def on_data_updated(reading: SensorReading) -> None:
        nonlocal reading_count
        reading_count += 1
        _LOGGER.info("[%3d] %s", reading_count, reading)

    status = _StatusCapture()

    client = RCXAZAirQualityHAClient(
        ble_device=live_device,
        on_data_updated=on_data_updated,
        on_status_changed=status.on_status_changed,
    )

    try:
        _LOGGER.info("Connecting to %s @ %s …", live_device.name, live_device.address)
        await client.connect()
        assert client.is_connected, "Client did not report connected state"

        _LOGGER.info("Streaming data for %d s …", test_duration)
        await asyncio.sleep(test_duration)

        _LOGGER.info(
            "Test complete: %d readings in %d s",
            reading_count,
            test_duration,
        )
        assert reading_count > 0, "No readings received during the test window"

    finally:
        _LOGGER.info("Disconnecting …")
        await client.disconnect()
        _LOGGER.info("Disconnected")
