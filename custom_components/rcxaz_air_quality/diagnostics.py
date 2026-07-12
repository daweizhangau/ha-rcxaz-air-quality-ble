"""Diagnostics support for the RCXAZ Air Quality Detector integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_REDACT = {"address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    client = coordinator._client if coordinator else None

    reading_dict: dict[str, Any] | None = None
    if coordinator is not None and coordinator.data is not None:
        reading = coordinator.data
        reading_dict = {
            "temperature_c": reading.temperature_c,
            "humidity_pct": reading.humidity_pct,
            "co2_ppm": reading.co2_ppm,
            "tvoc_mgm3": reading.tvoc_mgm3,
            "hcho_mgm3": reading.hcho_mgm3,
            "pm1_0": reading.pm1_0,
            "pm2_5": reading.pm2_5,
            "pm10": reading.pm10,
            "timestamp_counter": reading.timestamp_counter,
            "page_id": reading.page_id,
        }

    data = {
        "address": entry.unique_id,
        "title": entry.title,
        "entry_id": entry.entry_id,
        "connection_status": client.connection_status if client is not None else None,
        "is_connected": client.is_connected if client is not None else None,
        "last_seen_at": client.last_seen_at.isoformat() if (client is not None and client.last_seen_at is not None) else None,
        "rssi": coordinator.get_rssi() if coordinator is not None else None,
        "last_reading": reading_dict,
    }

    return async_redact_data(data, _REDACT)
