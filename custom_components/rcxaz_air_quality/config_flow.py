"""Config flow for the RCXAZ Air Quality Detector integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import C760_SERVICE_UUID, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_name_from_discovery(discovery_info: BluetoothServiceInfoBleak) -> str:
    """Return a human-readable name for the discovered device."""
    return discovery_info.name or discovery_info.address


def _is_rcxaz_device(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Check if the discovered device is an RCXAZ Air Quality Detector.

    Matches by:
    1. Name starts with 'XS-' (case-insensitive)
    2. Service UUIDs include the C760 service
    """
    name_match = (
        discovery_info.name is not None
        and discovery_info.name.upper().startswith("XS-")
    )
    uuid_match = C760_SERVICE_UUID in (discovery_info.service_uuids or [])
    return name_match and uuid_match


class RCXAZAirQualityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual configuration of the RCXAZ Air Quality Detector."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}  # address → name

    # ── Bluetooth auto-discovery ───────────────────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery via HA's Bluetooth integration."""
        if not _is_rcxaz_device(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": _device_name_from_discovery(discovery_info),
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm the discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=_device_name_from_discovery(self._discovery_info),
                data={CONF_ADDRESS: self._discovery_info.address},
            )

        assert self._discovery_info is not None
        name = _device_name_from_discovery(self._discovery_info)
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    # ── Manual entry (fallback) ────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Scan for nearby RCXAZ devices and let the user pick one."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            name = self._discovered_devices.get(address, address)
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address},
            )

        # Scan for discovered devices
        discovered = async_discovered_service_info(self.hass)
        matches = [
            info for info in discovered if _is_rcxaz_device(info)
        ]

        if not matches:
            # No devices found — show a helpful message
            return self.async_show_form(
                step_id="user",
                errors={"base": "no_devices_found"},
                data_schema=vol.Schema({}),
            )

        # Store discovered names for lookup when user picks
        self._discovered_devices = {
            info.address: _device_name_from_discovery(info)
            for info in matches
        }

        if len(matches) == 1:
            # Only one device found — auto-select it
            info = matches[0]
            await self.async_set_unique_id(info.address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_device_name_from_discovery(info),
                data={CONF_ADDRESS: info.address},
            )

        # Multiple devices — let the user pick
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In({
                    info.address: f"{info.name} ({info.address})"
                    for info in matches
                }),
            }),
        )
