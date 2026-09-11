"""KI Enhetsforbruk - forbruk og strømkostnad per enhet."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sett opp integrasjonen fra en config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Last inn på nytt når prissensorer endres eller enheter legges til,
    # redigeres eller slettes.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Last ut en config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
