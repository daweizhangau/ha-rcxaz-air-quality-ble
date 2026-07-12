"""Tests for the RCXAZ Air Quality Detector config flow.

These tests run entirely without a real Bluetooth device or HA instance by
using the ``hass`` fixture from ``pytest-homeassistant-custom-component`` and
mocking the Bluetooth layer.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
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
# Manual user flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_flow_manual_address(hass):
    """User can configure the integration by typing a MAC address."""
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == f"RCXAZ Air Quality ({TEST_ADDRESS})"
    assert result2["data"]["address"] == TEST_ADDRESS


@pytest.mark.asyncio
async def test_user_flow_aborts_if_already_configured(hass):
    """Duplicate manual entry is rejected."""
    with flow_ctx(hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )

    with flow_ctx(hass):
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input={"address": TEST_ADDRESS},
        )
    assert result3["type"] == FlowResultType.ABORT
    assert result3["reason"] == "already_configured"
