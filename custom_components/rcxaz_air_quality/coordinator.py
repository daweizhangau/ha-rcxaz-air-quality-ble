"""Coordinator for the RCXAZ Air Quality Detector.

Unlike a poll-based coordinator, this one listens for data updates from the
BLE client's notification handler and pushes them to HA entities immediately
via ``async_set_updated_data``.

The DataUpdateCoordinator's periodic update interval is used only as a
connection health check — the real data flow is notification-driven.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .ha_client import RCXAZAirQualityHAClient
from .protocol import SensorReading

_LOGGER = logging.getLogger(__name__)

# How often to check connection health (seconds)
HEALTH_CHECK_INTERVAL = 60.0


class RCXAZAirQualityCoordinator(DataUpdateCoordinator[SensorReading]):
    """Coordinator for the RCXAZ Air Quality Detector.

    Data arrives via BLE notifications — the coordinator subscribes to the
    client's ``on_data_updated`` callback and calls ``async_set_updated_data``
    whenever a new reading is parsed.
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
        self._client: Optional[RCXAZAirQualityHAClient] = None
        self._unsub_status_changed: Optional[callable] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Create the BLE client and connect."""
        ble_device = self._get_ble_device()
        if ble_device is None:
            _LOGGER.warning("Device not available in Bluetooth registry yet")
            return

        self._client = RCXAZAirQualityHAClient(
            ble_device=ble_device,
            ble_device_callback=self._get_ble_device,
            on_data_updated=self._on_client_data_updated,
            on_status_changed=self._on_status_changed,
        )

        try:
            await self._client.connect()
        except Exception:
            _LOGGER.exception("Failed to connect to RCXAZ Air Quality Detector")

    async def async_shutdown(self) -> None:
        """Disconnect and clean up."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    # ── DataUpdateCoordinator interface ────────────────────────────────────────

    async def _async_update_data(self) -> Optional[SensorReading]:
        """Health-check update: return the latest reading if connected.

        This is called periodically by the DataUpdateCoordinator framework.
        The real data flow is notification-driven via _on_client_data_updated.
        """
        if self._client is None or not self._client.is_connected:
            # Attempt reconnection
            await self.async_setup()
        return self._client.last_reading if self._client else None

    # ── Client callbacks ───────────────────────────────────────────────────────

    def _on_client_data_updated(self, reading: SensorReading) -> None:
        """Called by the BLE client when a new reading arrives."""
        self.async_set_updated_data(reading)

    def _on_status_changed(self) -> None:
        """Called by the BLE client when connection status changes."""
        self.async_update_listeners()

    # ── Bluetooth helpers ──────────────────────────────────────────────────────

    def _get_ble_device(self) -> Optional[BLEDevice]:
        """Return the BLEDevice from HA's Bluetooth registry."""
        address = self.config_entry.unique_id
        if address is None:
            return None
        return bluetooth.async_ble_device_from_address(
            self.hass, address, connectable=True
        )

    def get_rssi(self) -> Optional[int]:
        """Return the last known RSSI from HA's Bluetooth registry."""
        address = self.config_entry.unique_id
        if address is None:
            return None
        service_info = bluetooth.async_last_service_info(
            self.hass, address, connectable=True
        )
        return service_info.rssi if service_info is not None else None
