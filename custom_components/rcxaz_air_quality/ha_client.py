"""HA-native BLE client for the RCXAZ Air Quality Detector.

Uses Home Assistant's Bluetooth integration APIs so that both the built-in
Bluetooth adapter and ESPHome Bluetooth proxies are transparently supported.

The device **pushes** sensor data autonomously at ~1 Hz after an activation
byte is written — no polling needed.  The client keeps the BLE connection
alive and fires ``on_data_updated`` whenever a new reading (possibly partial)
arrives.  The coordinator pushes each partial update to HA entities immediately.

Design:
  - Connection is **always-alive** — connect once, stay connected.
  - ``on_data_updated`` fires per-page (not batched) — temp/humidity sensors
    update immediately even if CO₂/PM pages haven't arrived yet.
  - ``_on_disconnect()`` fires ``on_status_changed`` so the coordinator can
    schedule a reconnect on the next health-check interval.
  - Non-fatal GATT writes for activation & clock sync.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from .const import (
    C761_NOTIFY_UUID,
    C762_WRITE_UUID,
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
)
from .protocol import (
    ACTIVATION_BYTE,
    SensorReading,
    make_datetime_payload,
    parse_frame,
)

_LOGGER = logging.getLogger(__name__)


class DeviceNotAvailableError(Exception):
    """Raised when the device is not in HA's Bluetooth registry."""


class RCXAZAirQualityHAClient:
    """Always-alive BLE client for the RCXAZ Air Quality Detector.

    The device pushes sensor data autonomously.  This client subscribes to
    notifications, merges multi-page readings, and fires ``on_data_updated``
    immediately for each page (even partial ones).

    Usage (from the coordinator)::

        # Setup
        client = RCXAZAirQualityHAClient(
            ble_device,
            on_data_updated=coordinator._on_reading,
            on_status_changed=coordinator.async_update_listeners,
        )
        await client.connect()

        # Health-check (called every ~30 s by DataUpdateCoordinator)
        if not client.is_connected:
            await client.connect()
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        ble_device_callback: Callable[[], Optional[BLEDevice]] | None = None,
        on_data_updated: Callable[[SensorReading], None] | None = None,
        on_status_changed: Callable[[], None] | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._ble_device_callback = ble_device_callback
        self._on_data_updated = on_data_updated
        self._on_status_changed = on_status_changed

        self._client: Optional[BleakClient] = None
        self._connecting: bool = False
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._disconnect_time: float = 0.0
        self._connect_finish_time: float = 0.0
        self._notify_char = None
        self._write_char = None

        # Latest merged reading (accumulates fields from multiple pages)
        self._last_reading: Optional[SensorReading] = None
        self._last_seen_at: Optional[datetime] = None

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """True when an active BLE connection exists."""
        return self._client is not None and self._client.is_connected

    @property
    def connection_status(self) -> str:
        """Human-readable connection state for the diagnostic sensor."""
        if self._connecting:
            return CONN_STATUS_CONNECTING
        if self.is_connected:
            return CONN_STATUS_CONNECTED
        return CONN_STATUS_DISCONNECTED

    @property
    def last_reading(self) -> Optional[SensorReading]:
        """The most recently merged SensorReading."""
        return self._last_reading

    @property
    def last_seen_at(self) -> Optional[datetime]:
        """UTC datetime of the last successful reading, or None."""
        return self._last_seen_at

    # ── Connection ─────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish a BLE connection, subscribe, and activate the stream.

        Idempotent — returns immediately if already connected.  If a
        connection attempt is in progress, waits for it to finish.
        """
        if self.is_connected:
            return

        if self._ble_device_callback is not None:
            fresh = self._ble_device_callback()
            if fresh is None:
                raise DeviceNotAvailableError(
                    f"Device {self._ble_device.address} not in Bluetooth registry"
                )
            self._ble_device = fresh

        if self._connect_lock.locked():
            _LOGGER.debug("Connection already in progress — waiting for it")
            async with self._connect_lock:
                return

        async with self._connect_lock:
            if self.is_connected:
                return

            _LOGGER.debug(
                "Connecting to %s (%s)",
                self._ble_device.name,
                self._ble_device.address,
            )
            _t = time.monotonic()
            self._connecting = True
            self._notify_status_changed()
            try:
                self._client = await asyncio.wait_for(
                    establish_connection(
                        BleakClientWithServiceCache,
                        self._ble_device,
                        self._ble_device.name or self._ble_device.address,
                        self._on_disconnect,
                        max_attempts=1,
                    ),
                    timeout=30.0,
                )
            finally:
                self._connecting = False
                self._notify_status_changed()
            _LOGGER.debug(
                "BLE connection established in %.2fs",
                time.monotonic() - _t,
            )

        await asyncio.sleep(0.5)

        notify_char = self._client.services.get_characteristic(C761_NOTIFY_UUID)
        write_char = self._client.services.get_characteristic(C762_WRITE_UUID)
        if notify_char is None or write_char is None:
            raise RuntimeError("Required GATT characteristics not found")
        self._notify_char = notify_char
        self._write_char = write_char

        # Clear stale subscription
        try:
            await self._client.stop_notify(notify_char)
            await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001
            pass

        await self._client.start_notify(notify_char, self._on_notification)
        await asyncio.sleep(0.3)
        _LOGGER.debug("Subscribed to notifications on C761")

        self._connect_finish_time = time.monotonic()

        # Activation write — non-fatal (device may already push from prev session)
        try:
            await self._client.write_gatt_char(
                write_char, ACTIVATION_BYTE, response=False
            )
            _LOGGER.debug("Sent activation byte (0x1E)")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Activation write failed (non-fatal)", exc_info=True)

        # Clock sync — non-fatal
        try:
            payload = make_datetime_payload()
            await self._client.write_gatt_char(write_char, payload, response=False)
            _LOGGER.debug("Clock synced")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Clock sync failed (non-fatal)", exc_info=True)

    async def disconnect(self) -> None:
        """Gracefully stop notifications and disconnect."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                if client.is_connected:
                    try:
                        if self._notify_char is not None:
                            await client.stop_notify(self._notify_char)
                    except Exception:  # noqa: BLE001
                        pass
                    await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.debug("Disconnected")

    def _on_disconnect(self, client: BleakClient) -> None:
        """Called by bleak when the device disconnects unexpectedly."""
        if self._connecting:
            _LOGGER.debug(
                "Disconnect during connect phase — establish_connection will retry"
            )
            return

        self._disconnect_time = time.monotonic()
        _LOGGER.warning(
            "Device disconnected unexpectedly (up for %.0fs) — "
            "coordinator will reconnect on next health check",
            time.monotonic() - self._connect_finish_time,
        )
        self._client = None
        self._notify_status_changed()

    # ── Notification handler ───────────────────────────────────────────────

    def _on_notification(self, sender: object, data: bytearray) -> None:
        """Handle an incoming BLE notification (runs in Bleak thread).

        Parses the frame, merges with the previous reading so each page
        arrival carries all previous-page values, then fires the callback
        **immediately** — HA entities for the current page update right away.
        """
        reading = parse_frame(bytes(data))
        if reading is None:
            return

        if reading.page_id == 0x0401:  # ACK — ignore
            return

        _LOGGER.debug("Ntf: page=0x%04x %s", reading.page_id, reading)

        # Merge: keep old values for fields not in this page
        merged = reading
        if self._last_reading is not None and reading.page_id is not None:
            merged = self._merge_readings(self._last_reading, reading)

        self._last_reading = merged
        self._last_seen_at = datetime.now(timezone.utc)

        # Fire callback IMMEDIATELY — entities update per-page
        if self._on_data_updated is not None:
            try:
                self._on_data_updated(merged)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Exception in on_data_updated callback", exc_info=True
                )

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _merge_readings(
        base: SensorReading, update: SensorReading
    ) -> SensorReading:
        """Merge two readings, keeping base values for fields not in update."""
        return SensorReading(
            temperature_c=(
                update.temperature_c
                if update.temperature_c is not None
                else base.temperature_c
            ),
            humidity_pct=(
                update.humidity_pct
                if update.humidity_pct is not None
                else base.humidity_pct
            ),
            co2_ppm=(
                update.co2_ppm if update.co2_ppm is not None else base.co2_ppm
            ),
            tvoc_mgm3=(
                update.tvoc_mgm3
                if update.tvoc_mgm3 is not None
                else base.tvoc_mgm3
            ),
            hcho_mgm3=(
                update.hcho_mgm3
                if update.hcho_mgm3 is not None
                else base.hcho_mgm3
            ),
            pm1_0=update.pm1_0 if update.pm1_0 is not None else base.pm1_0,
            pm2_5=update.pm2_5 if update.pm2_5 is not None else base.pm2_5,
            pm10=update.pm10 if update.pm10 is not None else base.pm10,
            timestamp_counter=(
                update.timestamp_counter
                if update.timestamp_counter is not None
                else base.timestamp_counter
            ),
            page_id=update.page_id,
        )

    def _notify_status_changed(self) -> None:
        if self._on_status_changed is not None:
            try:
                self._on_status_changed()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Exception in on_status_changed callback", exc_info=True
                )

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the underlying BLEDevice reference."""
        self._ble_device = ble_device
