"""Coordinator for the RCXAZ Air Quality Detector.

The device pushes sensor data autonomously at ~1 Hz after an activation byte
is written.  The coordinator keeps the BLE connection **always-alive** and
pushes each notification (even partial pages) to HA entities immediately via
``async_set_updated_data``.

The DataUpdateCoordinator's periodic interval is used only as a connection
health check — the real data flow is notification-driven.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Optional

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .ha_client import DeviceNotAvailableError, RCXAZAirQualityHAClient
from .protocol import SensorReading

_LOGGER = logging.getLogger(__name__)

# Health-check interval — how often to verify the connection is still alive.
# The device pushes at ~1 Hz, so data arrives continuously between checks.
HEALTH_CHECK_INTERVAL = 30.0


class RCXAZAirQualityCoordinator(DataUpdateCoordinator[SensorReading]):
    """Coordinator that keeps an always-alive BLE connection.

    Data arrives via BLE notifications — the coordinator subscribes to the
    client's ``on_data_updated`` callback and calls ``async_set_updated_data``
    whenever a new reading (even partial) is parsed.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=HEALTH_CHECK_INTERVAL),
        )
        self.config_entry = entry
        self._address: str = entry.unique_id or ""
        self._client: Optional[RCXAZAirQualityHAClient] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Create the BLE client and connect.

        Connection is attempted immediately — if the device isn't in the
        Bluetooth registry yet, the health check will retry on the next
        interval.
        """
        ble_device = self._get_ble_device() or BLEDevice(
            self._address, "RCXAZ-Air", {}
        )
        self._client = RCXAZAirQualityHAClient(
            ble_device,
            ble_device_callback=self._get_ble_device,
            on_data_updated=self._on_reading,
            on_status_changed=self._on_status_changed,
        )

        try:
            await self._client.connect()
            _LOGGER.info("Connected to %s", self._address)
        except DeviceNotAvailableError:
            _LOGGER.debug(
                "Device %s not in Bluetooth registry yet — "
                "will retry on next health check",
                self._address,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to connect — will retry on next health check",
                exc_info=True,
            )

    async def async_shutdown(self) -> None:
        """Disconnect and clean up."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
        await super().async_shutdown()

    # ── DataUpdateCoordinator interface ────────────────────────────────────

    async def _async_update_data(self) -> SensorReading:
        """Health-check: reconnect if disconnected, return latest reading.

        This is called periodically by the DataUpdateCoordinator framework.
        The real data flow is notification-driven via _on_reading.
        """
        if self._client is None:
            raise UpdateFailed("Client not initialised")

        # Refresh BLEDevice reference for best proxy
        ble_device = self._get_ble_device()
        if ble_device is not None:
            self._client.update_ble_device(ble_device)

        if not self._client.is_connected:
            down_for = time.monotonic() - getattr(
                self._client, '_disconnect_time', time.monotonic()
            )
            try:
                await self._client.connect()
            except DeviceNotAvailableError:
                # Not in registry yet — no need to log at ERROR level
                _LOGGER.debug(
                    "Device %s not in Bluetooth registry yet — "
                    "waiting for advertisement",
                    self._address,
                )
                raise UpdateFailed(
                    f"Device {self._address} not in Bluetooth registry"
                ) from None
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Reconnect failed (down for %.0fs): %s",
                    down_for, err,
                )
                raise UpdateFailed(f"Reconnect failed: {err}") from err

        # Return the latest reading, or re-raise the last error if the
        # connection is still down and no data was ever received.  This
        # prevents a "not in Bluetooth registry" error from being logged
        # as an ERROR on the very first health check before the device
        # has had time to appear.
        reading = self._client.last_reading
        if reading is not None:
            return reading
        if not self._client.is_connected:
            raise UpdateFailed("Device not connected — waiting for advertisement")
        raise UpdateFailed("No data received yet")

    # ── Client callbacks ───────────────────────────────────────────────────

    def _on_reading(self, reading: SensorReading) -> None:
        """Called by the BLE client when a new reading (possibly partial) arrives.

        Pushes the reading to HA entities immediately via
        async_set_updated_data — sensors for the current page update
        right away without waiting for other pages.
        """
        self.async_set_updated_data(reading)

    def _on_status_changed(self) -> None:
        """Called by the BLE client when connection status changes.

        Triggers an immediate health check so reconnection starts promptly
        rather than waiting for the next scheduled interval.
        """
        self.async_update_listeners()
        if not (self._client and self._client.is_connected):
            self.hass.async_create_task(self.async_request_refresh())

    # ── Bluetooth helpers ──────────────────────────────────────────────────

    @property
    def client(self) -> RCXAZAirQualityHAClient:
        """The underlying BLE client (used by entities for properties)."""
        assert self._client is not None, "Client accessed before async_setup()"
        return self._client

    def _get_ble_device(self) -> Optional[BLEDevice]:
        """Look up the current ``BLEDevice`` from the HA Bluetooth registry."""
        assert self._address is not None
        return bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )

    def get_rssi(self) -> Optional[int]:
        """Return the last known RSSI (dBm) for the device, or None."""
        service_info = bluetooth.async_last_service_info(
            self.hass, self._address, connectable=True
        )
        return service_info.rssi if service_info is not None else None
