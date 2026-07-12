"""Sensor entities for the RCXAZ Air Quality Detector."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONN_STATUS_CONNECTED,
    CONN_STATUS_CONNECTING,
    CONN_STATUS_DISCONNECTED,
    DOMAIN,
    SUFFIX_CO2,
    SUFFIX_CONNECTION_STATUS,
    SUFFIX_HCHO,
    SUFFIX_HUMIDITY,
    SUFFIX_LAST_SEEN,
    SUFFIX_PM10,
    SUFFIX_PM1_0,
    SUFFIX_PM2_5,
    SUFFIX_RSSI,
    SUFFIX_TEMPERATURE,
    SUFFIX_TVOC,
)
from .coordinator import RCXAZAirQualityCoordinator
from .protocol import SensorReading


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RCXAZ Air Quality sensor entities."""
    coordinator: RCXAZAirQualityCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TemperatureSensor(coordinator, entry),
        HumiditySensor(coordinator, entry),
        CO2Sensor(coordinator, entry),
        TVOCSensor(coordinator, entry),
        HCHOSensor(coordinator, entry),
        PM1_0Sensor(coordinator, entry),
        PM2_5Sensor(coordinator, entry),
        PM10Sensor(coordinator, entry),
        ConnectionStatusSensor(coordinator, entry),
        RSSISensor(coordinator, entry),
        LastSeenSensor(coordinator, entry),
    ])


# ── Base class ─────────────────────────────────────────────────────────────────

class RCXAZAirQualitySensor(CoordinatorEntity[RCXAZAirQualityCoordinator], SensorEntity):
    """Base sensor for the RCXAZ Air Quality Detector."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RCXAZAirQualityCoordinator,
        entry: ConfigEntry,
        suffix: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, entry.unique_id)},
            manufacturer="Nobito (Shenzhen) Technology Co., LTD",
            model="2CO11",
            name=entry.title,
            sw_version="1.0",
        )

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data."""
        return self.coordinator.data is not None


# ── Sensor implementations ─────────────────────────────────────────────────────

class TemperatureSensor(RCXAZAirQualitySensor):
    """Temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_TEMPERATURE)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.temperature_c


class HumiditySensor(RCXAZAirQualitySensor):
    """Humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_HUMIDITY)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.humidity_pct


class CO2Sensor(RCXAZAirQualitySensor):
    """CO₂ sensor."""

    _attr_device_class = SensorDeviceClass.CO2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_CO2)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.co2_ppm


class TVOCSensor(RCXAZAirQualitySensor):
    """TVOC sensor (Total Volatile Organic Compounds)."""

    _attr_device_class = SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_TVOC)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.tvoc_mgm3


class HCHOSensor(RCXAZAirQualitySensor):
    """HCHO (formaldehyde) sensor."""

    _attr_device_class = SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_HCHO)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.hcho_mgm3


class PM1_0Sensor(RCXAZAirQualitySensor):
    """PM1.0 particulate sensor."""

    _attr_device_class = SensorDeviceClass.PM1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_PM1_0)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pm1_0


class PM2_5Sensor(RCXAZAirQualitySensor):
    """PM2.5 particulate sensor."""

    _attr_device_class = SensorDeviceClass.PM25
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_PM2_5)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pm2_5


class PM10Sensor(RCXAZAirQualitySensor):
    """PM10 particulate sensor."""

    _attr_device_class = SensorDeviceClass.PM10
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_PM10)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pm10


# ── Diagnostic sensors ─────────────────────────────────────────────────────────

class ConnectionStatusSensor(RCXAZAirQualitySensor):
    """BLE connection state: Connected / Connecting / Disconnected."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        CONN_STATUS_CONNECTED,
        CONN_STATUS_CONNECTING,
        CONN_STATUS_DISCONNECTED,
    ]

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_CONNECTION_STATUS)

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return CONN_STATUS_DISCONNECTED
        if self.coordinator._client is None:
            return CONN_STATUS_DISCONNECTED
        return self.coordinator._client.connection_status


class RSSISensor(RCXAZAirQualitySensor):
    """Last known Bluetooth signal strength in dBm."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_RSSI)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.get_rssi()


class LastSeenSensor(RCXAZAirQualitySensor):
    """UTC timestamp of the most recent successful reading."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: RCXAZAirQualityCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, SUFFIX_LAST_SEEN)

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator._client is None:
            return None
        return self.coordinator._client.last_seen_at
