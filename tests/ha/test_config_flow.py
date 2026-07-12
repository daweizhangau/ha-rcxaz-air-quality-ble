"""Tests for the RCXAZ Air Quality Detector config flow.

These tests run entirely without a real Bluetooth device or HA instance by
using the ``hass`` fixture from ``pytest-homeassistant-custom-component`` and
mocking the Bluetooth layer.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType

from custom_components.rcxaz_air_quality.const import C760_SERVICE_UUID, DOMAIN
from tests.ha.conftest import (
    TEST_ADDRESS,
    TEST_NAME,
    flow_ctx,
    make_bluetooth_service_info,
)


# ---------------------------------------------------------------------------
# Bluetooth auto-discovery flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bluetooth_discovery_confirm(hass):
    """Discovery step followed by user confirmation creates a config entry."""
    discovery = make_bluetooth_service_info()

    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == TEST_NAME
    assert result2["data"]["address"] == TEST_ADDRESS


@pytest.mark.asyncio
async def test_bluetooth_discovery_aborts_if_already_configured(hass):
    """Second discovery for the same MAC is rejected."""
    discovery = make_bluetooth_service_info()

    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})

    # Second discovery should abort
    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_bluetooth_discovery_rejects_non_xs_device(hass):
    """Devices without XS- name or C760 service are rejected."""
    # Wrong name, correct service UUID
    discovery = make_bluetooth_service_info(name="OTHER-DEVICE")
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "not_supported"

    # Correct name, missing service UUID
    discovery = make_bluetooth_service_info(service_uuids=["0000abcd-..."])
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "bluetooth"},
            data=discovery,
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "not_supported"


# ---------------------------------------------------------------------------
# Manual user flow (scans for devices)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_flow_auto_selects_single_device(hass):
    """When one device is discovered, it's auto-selected."""
    discovery = make_bluetooth_service_info()

    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[discovery],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_NAME
    assert result["data"]["address"] == TEST_ADDRESS


@pytest.mark.asyncio
async def test_user_flow_shows_picker_for_multiple_devices(hass):
    """When multiple devices are discovered, user picks one."""
    dev1 = make_bluetooth_service_info(address="AA:BB:CC:DD:EE:01", name="XS-1111")
    dev2 = make_bluetooth_service_info(address="AA:BB:CC:DD:EE:02", name="XS-2222")

    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[dev1, dev2],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_ADDRESS in result["data_schema"].schema

    # Pick the first device
    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[dev1, dev2],
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": "AA:BB:CC:DD:EE:01"},
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "XS-1111"


@pytest.mark.asyncio
async def test_user_flow_shows_error_when_no_devices(hass):
    """When no devices are discovered, show a helpful error."""
    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "no_devices_found"


@pytest.mark.asyncio
async def test_user_flow_aborts_if_already_configured(hass):
    """Duplicate entry is rejected."""
    discovery = make_bluetooth_service_info()

    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[discovery],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Second attempt should abort
    with flow_ctx(hass), patch(
        "custom_components.rcxaz_air_quality.config_flow.async_discovered_service_info",
        return_value=[discovery],
    ):
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
