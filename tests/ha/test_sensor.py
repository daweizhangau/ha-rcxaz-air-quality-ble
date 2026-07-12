"""Tests for HA sensor entities.

All tests use a mocked coordinator and client — no BLE hardware needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.rcxaz_air_quality.coordinator import RCXAZAirQualityCoordinator
from custom_components.rcxaz_air_quality.protocol import SensorReading
from custom_components.rcxaz_air_quality.sensor import (
    CO2Sensor,
    ConnectionStatusSensor,
    HCHOSensor,
    HumiditySensor,
    LastSeenSensor,
    PM10Sensor,
    PM1_0Sensor,
    PM2_5Sensor,
    RSSISensor,
    TVOCSensor,
    TemperatureSensor,
)
from tests.ha.conftest import (
    SAMPLE_MERGED_READING,
    TEST_ADDRESS,
    TEST_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(reading=SAMPLE_MERGED_READING, mock_client=None):
    coord = MagicMock(spec=RCXAZAirQualityCoordinator)
    coord.data = reading
    # The `client` property does `assert self._client is not None`, so
    # we patch both the property and the underlying `_client` attribute.
    type(coord).client = property(fget=lambda s: mock_client)
    coord._client = mock_client
    return coord


def _make_entry():
    entry = MagicMock()
    entry.unique_id = TEST_ADDRESS
    entry.title = TEST_NAME
    return entry


# ---------------------------------------------------------------------------
# TemperatureSensor
# ---------------------------------------------------------------------------

def test_temperature_sensor_value():
    coord = _make_coordinator()
    sensor = TemperatureSensor(coord, _make_entry())
    assert sensor.native_value == 22.5


def test_temperature_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = TemperatureSensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# HumiditySensor
# ---------------------------------------------------------------------------

def test_humidity_sensor_value():
    coord = _make_coordinator()
    sensor = HumiditySensor(coord, _make_entry())
    assert sensor.native_value == 60


def test_humidity_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = HumiditySensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# CO2Sensor
# ---------------------------------------------------------------------------

def test_co2_sensor_value():
    coord = _make_coordinator()
    sensor = CO2Sensor(coord, _make_entry())
    assert sensor.native_value == 400


def test_co2_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = CO2Sensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# TVOCSensor
# ---------------------------------------------------------------------------

def test_tvoc_sensor_value():
    coord = _make_coordinator()
    sensor = TVOCSensor(coord, _make_entry())
    assert sensor.native_value == 0.006


def test_tvoc_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = TVOCSensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# HCHOSensor
# ---------------------------------------------------------------------------

def test_hcho_sensor_value():
    coord = _make_coordinator()
    sensor = HCHOSensor(coord, _make_entry())
    assert sensor.native_value == 0.002


def test_hcho_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = HCHOSensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# PM1_0Sensor
# ---------------------------------------------------------------------------

def test_pm1_0_sensor_value():
    coord = _make_coordinator()
    sensor = PM1_0Sensor(coord, _make_entry())
    assert sensor.native_value == 5


def test_pm1_0_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = PM1_0Sensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# PM2_5Sensor
# ---------------------------------------------------------------------------

def test_pm2_5_sensor_value():
    coord = _make_coordinator()
    sensor = PM2_5Sensor(coord, _make_entry())
    assert sensor.native_value == 10


def test_pm2_5_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = PM2_5Sensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# PM10Sensor
# ---------------------------------------------------------------------------

def test_pm10_sensor_value():
    coord = _make_coordinator()
    sensor = PM10Sensor(coord, _make_entry())
    assert sensor.native_value == 15


def test_pm10_sensor_none_when_no_data():
    coord = _make_coordinator(reading=None)
    sensor = PM10Sensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# ConnectionStatusSensor
# ---------------------------------------------------------------------------

def test_connection_status_disconnected_when_no_client():
    coord = _make_coordinator(mock_client=None)
    sensor = ConnectionStatusSensor(coord, _make_entry())
    assert sensor.native_value == "Disconnected"


def test_connection_status_connected():
    mock_client = MagicMock()
    mock_client.connection_status = "Connected"
    coord = _make_coordinator(mock_client=mock_client)
    sensor = ConnectionStatusSensor(coord, _make_entry())
    assert sensor.native_value == "Connected"


# ---------------------------------------------------------------------------
# RSSISensor
# ---------------------------------------------------------------------------

def test_rssi_returns_value():
    coord = _make_coordinator()
    coord.get_rssi = MagicMock(return_value=-72)
    sensor = RSSISensor(coord, _make_entry())
    assert sensor.native_value == -72


def test_rssi_none_when_no_service_info():
    coord = _make_coordinator()
    coord.get_rssi = MagicMock(return_value=None)
    sensor = RSSISensor(coord, _make_entry())
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# LastSeenSensor
# ---------------------------------------------------------------------------

def test_last_seen_none_when_no_client():
    coord = _make_coordinator(mock_client=None)
    sensor = LastSeenSensor(coord, _make_entry())
    assert sensor.native_value is None


def test_last_seen_returns_value():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    mock_client = MagicMock()
    mock_client.last_seen_at = now
    coord = _make_coordinator(mock_client=mock_client)
    sensor = LastSeenSensor(coord, _make_entry())
    assert sensor.native_value == now
