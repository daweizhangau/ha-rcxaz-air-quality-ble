"""HA-native BLE client for the XS Air Quality Detector.

Uses Home Assistant's Bluetooth integration APIs so that both the built-in
Bluetooth adapter and ESPHome Bluetooth proxies are transparently supported.

The device **pushes** sensor data autonomously at ~1 Hz after activation —
no polling is needed. The client subscribes to notifications, parses frames
as they arrive, and fires a callback so the coordinator can push data to HA
entities in real time.
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
    CLOCK_SYNC_INTERVAL,
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
    """Raised when the device is not in HA's Bluetooth registry.

    This is expected while the device is off or out of range — callers
    should treat it as a transient condition and retry on the next poll.
    """


class XSAirQualityHAClient:
    """Notification-driven BLE client for the XS Air Quality Detector.

    The device pushes sensor data autonomously after activation. This client
    subscribes to notifications, parses incoming frames, and notifies HA via
    the ``on_data_updated`` callback.

    Parameters
    ----------
    ble_device:
        The ``BLEDevice`` obtained from HA's Bluetooth registry.
    ble_device_callback:
        Optional callback to refresh the BLEDevice before connecting.
    on_data_updated:
        Called whenever a new SensorReading is parsed from a notification.
    on_status_changed:
        Called when connection status changes.
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

        # Latest merged reading (accumulates fields from multiple pages)
        self._last_reading: Optional[SensorReading] = None
        self._last_seen_at: Optional[datetime] = None
        self._last_time_sync: float = 0.0  # monotonic clock

        # Background task for hourly clock sync
        self._sync_task: Optional[asyncio.Task] = None

    # ── Properties ─────────────────────────────────────────────────────────────

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
        """The most recently parsed SensorReading."""
        return self._last_reading

    @property
    def last_seen_at(self) -> Optional[datetime]:
        """UTC datetime of the last successful reading, or None."""
        return self._last_seen_at

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Establish a BLE connection and subscribe to notifications.

        After connecting:
        1. Subscribes to C761 notifications
        2. Sends activation byte (0x1E) to C762
        3. Sends datetime sync to C762
        4. Starts hourly clock sync background task
        """
        if self._ble_device_callback is not None:
            fresh = self._ble_device_callback()
            if fresh is None:
                raise DeviceNotAvailableError(
                    f"Device {self._ble_device.address} not in Bluetooth registry — "
                    "waiting for advertisement"
                )
            self._ble_device = fresh

        if self._connect_lock.locked():
            raise RuntimeError("Connection attempt already in progress")

        async with self._connect_lock:
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
            _LOGGER.debug("establish_connection took %.2fs", time.monotonic() - _t)

        # Give BlueZ time to fully publish GATT characteristic objects on DBus
        await asyncio.sleep(0.5)

        # Clear any stale notification subscription
        try:
            await self._client.stop_notify(C761_NOTIFY_UUID)
            await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001
            pass

        await self._client.start_notify(C761_NOTIFY_UUID, self._on_notification)
        await asyncio.sleep(0.3)
        _LOGGER.debug("Subscribed to notifications on C761")

        # Activate the data stream
        await self._write(C762_WRITE_UUID, ACTIVATION_BYTE)
        _LOGGER.debug("Sent activation byte")

        # Sync device clock
        await self._sync_clock()

        # Start hourly clock sync background task
        self._sync_task = asyncio.create_task(self._hourly_sync_loop())

    async def disconnect(self) -> None:
        """Gracefully stop notifications and disconnect."""
        if self._sync_task is not None:
            self._sync_task.cancel()
            self._sync_task = None
        if self._client is not None:
            try:
                if self._client.is_connected:
                    await self._client.stop_notify(C761_NOTIFY_UUID)
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        _LOGGER.debug("Disconnected")

    def _on_disconnect(self, client: BleakClient) -> None:
        """Called by bleak when the device disconnects unexpectedly."""
        if self._connecting:
            _LOGGER.debug("Disconnect during connect phase — establish_connection will retry")
            return
        self._disconnect_time = time.monotonic()
        _LOGGER.warning("XS Air Quality disconnected unexpectedly — coordinator will reconnect")
        self._client = None
        self._notify_status_changed()

    # ── Notification handler ───────────────────────────────────────────────────

    def _on_notification(self, sender: object, data: bytearray) -> None:
        """Handle an incoming BLE notification on C761."""
        reading = parse_frame(bytes(data))
        if reading is None:
            _LOGGER.debug("Unrecognised notification: %s", data.hex())
            return

        _LOGGER.debug("Parsed frame: page=0x%04x %s", reading.page_id, reading)

        # Handle acknowledgment page (0x0401) — confirms a command was received
        if reading.page_id == 0x0401:
            _LOGGER.debug("Received acknowledgment from device")
            return

        # Merge with the last reading: keep previous values for fields not
        # present in the current frame (since pages arrive separately).
        if self._last_reading is not None and reading.page_id is not None:
            merged = self._merge_readings(self._last_reading, reading)
        else:
            merged = reading

        self._last_reading = merged
        self._last_seen_at = datetime.now(timezone.utc)

        if self._on_data_updated is not None:
            try:
                self._on_data_updated(merged)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Exception in on_data_updated callback", exc_info=True)

    @staticmethod
    def _merge_readings(base: SensorReading, update: SensorReading) -> SensorReading:
        """Merge two readings, keeping base values for fields not in update."""
        return SensorReading(
            temperature_c=update.temperature_c if update.temperature_c is not None else base.temperature_c,
            humidity_pct=update.humidity_pct if update.humidity_pct is not None else base.humidity_pct,
            co2_ppm=update.co2_ppm if update.co2_ppm is not None else base.co2_ppm,
            tvoc_mgm3=update.tvoc_mgm3 if update.tvoc_mgm3 is not None else base.tvoc_mgm3,
            hcho_mgm3=update.hcho_mgm3 if update.hcho_mgm3 is not None else base.hcho_mgm3,
            pm1_0=update.pm1_0 if update.pm1_0 is not None else base.pm1_0,
            pm2_5=update.pm2_5 if update.pm2_5 is not None else base.pm2_5,
            pm10=update.pm10 if update.pm10 is not None else base.pm10,
            timestamp_counter=update.timestamp_counter if update.timestamp_counter is not None else base.timestamp_counter,
            page_id=update.page_id,
        )

    # ── Clock sync ─────────────────────────────────────────────────────────────

    async def _sync_clock(self) -> None:
        """Send the current datetime to the device."""
        try:
            payload = make_datetime_payload()
            await self._write(C762_WRITE_UUID, payload)
            self._last_time_sync = time.monotonic()
            _LOGGER.debug("Clock synced")
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Clock sync failed", exc_info=True)

    async def _hourly_sync_loop(self) -> None:
        """Background task: re-sync the device clock every hour."""
        try:
            while True:
                await asyncio.sleep(CLOCK_SYNC_INTERVAL)
                if self.is_connected:
                    await self._sync_clock()
        except asyncio.CancelledError:
            pass

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _write(self, uuid: str, data: bytes) -> None:
        """Write data to a GATT characteristic (write-without-response)."""
        if self._client is None:
            raise RuntimeError("Not connected")
        await self._client.write_gatt_char(uuid, data, response=False)

    def _notify_status_changed(self) -> None:
        """Fire the status-changed callback, swallowing any exception."""
        if self._on_status_changed is not None:
            try:
                self._on_status_changed()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Exception in on_status_changed callback", exc_info=True)

    def update_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the underlying BLEDevice reference."""
        self._ble_device = ble_device
