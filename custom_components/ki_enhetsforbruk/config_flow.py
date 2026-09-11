"""Config flow for KI Enhetsforbruk."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

from .const import (
    CONF_ADD_SOURCES,
    CONF_NORGESPRIS,
    CONF_SOURCE,
    CONF_SPOT_PRICE,
    DEFAULT_NORGESPRIS,
    DEFAULT_SPOT_PRICE,
    DEFAULT_TITLE,
    DOMAIN,
    SUBENTRY_DEVICE,
)

PRICE_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
ENERGY_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="energy")
)
ENERGY_MULTI_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
)

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SOURCE): ENERGY_SELECTOR,
        vol.Optional(CONF_NAME): TextSelector(),
    }
)

_NAME_SUFFIXES = (
    " energy usage",
    " energiforbruk",
    " energy",
    " energi",
)


def default_name(hass: HomeAssistant, entity_id: str) -> str:
    """Lag et fornuftig enhetsnavn fra energisensorens navn."""
    state = hass.states.get(entity_id)
    name = state.name if state else entity_id.split(".", 1)[-1].replace("_", " ")
    for suffix in _NAME_SUFFIXES:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip() or entity_id


def sources_in_use(entry: ConfigEntry, exclude: str | None = None) -> set[str]:
    """Energisensorer som allerede er brukt av en enhet i denne oppføringen."""
    return {
        sub.data[CONF_SOURCE]
        for sub_id, sub in entry.subentries.items()
        if sub.subentry_type == SUBENTRY_DEVICE and sub_id != exclude
    }


def _price_suggestions(hass: HomeAssistant) -> dict[str, str]:
    """Foreslå prissensorene fra den gamle YAML-pakken hvis de finnes."""
    suggestions: dict[str, str] = {}
    if hass.states.get(DEFAULT_SPOT_PRICE):
        suggestions[CONF_SPOT_PRICE] = DEFAULT_SPOT_PRICE
    if hass.states.get(DEFAULT_NORGESPRIS):
        suggestions[CONF_NORGESPRIS] = DEFAULT_NORGESPRIS
    return suggestions


def _price_options(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_SPOT_PRICE: user_input[CONF_SPOT_PRICE],
        CONF_NORGESPRIS: user_input.get(CONF_NORGESPRIS) or None,
    }


class KIEnhetsforbrukConfigFlow(ConfigFlow, domain=DOMAIN):
    """Oppsett av hovedoppføringen (prissensorer + første enheter)."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KIEnhetsforbrukOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_DEVICE: DeviceSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            subentries: list[ConfigSubentryData] = []
            seen: set[str] = set()
            for entity_id in user_input.get(CONF_ADD_SOURCES) or []:
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                subentries.append(
                    ConfigSubentryData(
                        data={CONF_SOURCE: entity_id},
                        subentry_type=SUBENTRY_DEVICE,
                        title=default_name(self.hass, entity_id),
                        unique_id=None,
                    )
                )
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={},
                options=_price_options(user_input),
                subentries=subentries,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_TITLE): TextSelector(),
                vol.Required(CONF_SPOT_PRICE): PRICE_SELECTOR,
                vol.Optional(CONF_NORGESPRIS): PRICE_SELECTOR,
                vol.Optional(CONF_ADD_SOURCES): ENERGY_MULTI_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema, _price_suggestions(self.hass)
            ),
        )


class KIEnhetsforbrukOptionsFlow(OptionsFlow):
    """Endre prissensorer og legge til mange enheter på en gang."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry

        if user_input is not None:
            in_use = sources_in_use(entry)
            for entity_id in user_input.get(CONF_ADD_SOURCES) or []:
                if entity_id in in_use:
                    continue
                in_use.add(entity_id)
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType({CONF_SOURCE: entity_id}),
                        subentry_type=SUBENTRY_DEVICE,
                        title=default_name(self.hass, entity_id),
                        unique_id=None,
                    ),
                )
            return self.async_create_entry(data=_price_options(user_input))

        schema = vol.Schema(
            {
                vol.Required(CONF_SPOT_PRICE): PRICE_SELECTOR,
                vol.Optional(CONF_NORGESPRIS): PRICE_SELECTOR,
                vol.Optional(CONF_ADD_SOURCES): ENERGY_MULTI_SELECTOR,
            }
        )
        suggested = {k: v for k, v in entry.options.items() if v is not None}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )


class DeviceSubentryFlow(ConfigSubentryFlow):
    """Legg til eller rediger én enhet."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            source = user_input[CONF_SOURCE]
            if source in sources_in_use(entry):
                errors[CONF_SOURCE] = "source_in_use"
            else:
                name = (user_input.get(CONF_NAME) or "").strip()
                return self.async_create_entry(
                    title=name or default_name(self.hass, source),
                    data={CONF_SOURCE: source},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                DEVICE_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            source = user_input[CONF_SOURCE]
            if source in sources_in_use(entry, exclude=subentry.subentry_id):
                errors[CONF_SOURCE] = "source_in_use"
            else:
                name = (user_input.get(CONF_NAME) or "").strip()
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=name or default_name(self.hass, source),
                    data={CONF_SOURCE: source},
                )

        current = user_input or {
            CONF_SOURCE: subentry.data[CONF_SOURCE],
            CONF_NAME: subentry.title,
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(DEVICE_SCHEMA, current),
            errors=errors,
        )
