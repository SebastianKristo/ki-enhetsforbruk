"""Sensorer for KI Enhetsforbruk.

Hver enhet får inntil seks sensorer: energi og kostnad (spotpris og
Norgespris) for i dag og denne måneden.

Kostnaden regnes ut fortløpende: hver gang energisensoren oppdateres,
ganges økningen i kWh med prisen som gjelder akkurat da. Det gir riktig
resultat også med 15-minutters spotpriser og negative priser.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    ATTR_VALUE,
    CONF_NORGESPRIS,
    CONF_SOURCE,
    CONF_SPOT_PRICE,
    DOMAIN,
    PERIOD_DAY,
    PERIOD_MONTH,
    PRICE_NORGESPRIS,
    PRICE_SPOT,
    RESET_THRESHOLD,
    SERVICE_CALIBRATE,
    SUBENTRY_DEVICE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KISensorDescription(SensorEntityDescription):
    """Beskrivelse av en forbruks-/kostnadssensor."""

    period: str
    price: str | None = None  # None = energisensor


def _energy(key: str, period: str) -> KISensorDescription:
    return KISensorDescription(
        key=key,
        translation_key=key,
        period=period,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
    )


def _cost(key: str, period: str, price: str) -> KISensorDescription:
    return KISensorDescription(
        key=key,
        translation_key=key,
        period=period,
        price=price,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
    )


SENSOR_DESCRIPTIONS: tuple[KISensorDescription, ...] = (
    _energy("energy_day", PERIOD_DAY),
    _energy("energy_month", PERIOD_MONTH),
    _cost("cost_spot_day", PERIOD_DAY, PRICE_SPOT),
    _cost("cost_spot_month", PERIOD_MONTH, PRICE_SPOT),
    _cost("cost_norgespris_day", PERIOD_DAY, PRICE_NORGESPRIS),
    _cost("cost_norgespris_month", PERIOD_MONTH, PRICE_NORGESPRIS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Opprett sensorer for alle enheter (subentries)."""
    price_entities = {
        None: None,
        PRICE_SPOT: entry.options.get(CONF_SPOT_PRICE),
        PRICE_NORGESPRIS: entry.options.get(CONF_NORGESPRIS),
    }

    expected_unique_ids: set[str] = set()
    per_subentry: dict[str, list[KIForbrukSensor]] = {}

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_DEVICE:
            continue
        entities: list[KIForbrukSensor] = []
        for description in SENSOR_DESCRIPTIONS:
            price_entity = price_entities[description.price]
            if description.price is not None and not price_entity:
                continue  # f.eks. Norgespris ikke valgt
            entity = KIForbrukSensor(hass, subentry, description, price_entity)
            entities.append(entity)
            expected_unique_ids.add(entity.unique_id)
        per_subentry[subentry_id] = entities

    # Rydd bort sensorer som ikke lenger skal finnes (f.eks. hvis
    # Norgespris-sensoren er fjernet i innstillingene).
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id not in expected_unique_ids:
            registry.async_remove(reg_entry.entity_id)

    for subentry_id, entities in per_subentry.items():
        async_add_entities(entities, config_subentry_id=subentry_id)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_CALIBRATE,
        {vol.Required(ATTR_VALUE): vol.Coerce(float)},
        "async_calibrate",
    )


# --------------------------------------------------------------------------
# Hjelpefunksjoner
# --------------------------------------------------------------------------


def _period_start(when: datetime, period: str) -> datetime:
    """Starten på dagen/måneden (lokal tid) som `when` ligger i."""
    day = dt_util.as_local(when).date()
    if period == PERIOD_MONTH:
        day = day.replace(day=1)
    return dt_util.start_of_local_day(day)


def _as_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _read_energy_kwh(state: State | None) -> float | None:
    """Les energisensoren og konverter til kWh."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    value = _as_float(state.state)
    if value is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if unit and unit != UnitOfEnergy.KILO_WATT_HOUR and unit in EnergyConverter.VALID_UNITS:
        value = EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)
    return value


def _read_price(state: State | None) -> float | None:
    """Les prissensoren i kr/kWh (øre/kWh konverteres automatisk)."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    price = _as_float(state.state)
    if price is None:
        return None
    unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "").lower()
    if "øre" in unit or "ore/" in unit:
        price /= 100
    return price


@dataclass
class KIStoredData(ExtraStoredData):
    """Data som lagres mellom omstarter."""

    value: float
    last_period: float | None
    last_reset: datetime | None
    last_source: float | None
    source_entity: str | None
    last_price: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "last_period": self.last_period,
            "last_reset": self.last_reset.isoformat() if self.last_reset else None,
            "last_source": self.last_source,
            "source_entity": self.source_entity,
            "last_price": self.last_price,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KIStoredData | None:
        value = _as_float(data.get("value"))
        if value is None:
            return None
        raw_reset = data.get("last_reset")
        return cls(
            value=value,
            last_period=_as_float(data.get("last_period")),
            last_reset=dt_util.parse_datetime(raw_reset) if raw_reset else None,
            last_source=_as_float(data.get("last_source")),
            source_entity=data.get("source_entity"),
            last_price=_as_float(data.get("last_price")),
        )


# --------------------------------------------------------------------------
# Sensor
# --------------------------------------------------------------------------


class KIForbrukSensor(SensorEntity, RestoreEntity):
    """Energi eller kostnad for én enhet i én periode."""

    entity_description: KISensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL
    _unrecorded_attributes = frozenset({"source_entity", "price_entity"})

    def __init__(
        self,
        hass: HomeAssistant,
        subentry: ConfigSubentry,
        description: KISensorDescription,
        price_entity: str | None,
    ) -> None:
        self.entity_description = description
        self._source: str = subentry.data[CONF_SOURCE]
        self._price_entity = price_entity
        self._attr_unique_id = f"{subentry.subentry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="KI Enhetsforbruk",
            model="Forbruk og kostnad",
            entry_type=DeviceEntryType.SERVICE,
        )
        if description.price is not None:
            self._attr_native_unit_of_measurement = hass.config.currency

        self._value: float = 0.0
        self._last_period: float | None = None
        self._last_source: float | None = None
        self._last_price: float | None = None
        self._attr_last_reset = _period_start(dt_util.now(), description.period)

    # ---- tilstand ----

    @property
    def native_value(self) -> float:
        return round(self._value, 6)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "last_period": (
                round(self._last_period, 6) if self._last_period is not None else None
            ),
            "source_entity": self._source,
        }
        if self._price_entity:
            attrs["price_entity"] = self._price_entity
        return attrs

    @property
    def extra_restore_state_data(self) -> KIStoredData:
        return KIStoredData(
            value=self._value,
            last_period=self._last_period,
            last_reset=self._attr_last_reset,
            last_source=self._last_source,
            source_entity=self._source,
            last_price=self._last_price,
        )

    # ---- livssyklus ----

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (extra := await self.async_get_last_extra_data()) and (
            stored := KIStoredData.from_dict(extra.as_dict())
        ):
            self._value = stored.value
            self._last_period = stored.last_period
            self._last_price = stored.last_price
            if stored.last_reset is not None:
                self._attr_last_reset = stored.last_reset
            # Bytt av energisensor: behold opptalt verdi, men start ny baseline
            if stored.source_entity == self._source:
                self._last_source = stored.last_source

        # Nullstill hvis dag/måned har skiftet mens HA var avslått
        self._check_period(dt_util.now())

        # Ta med forbruk som skjedde mens HA var avslått
        self._process_source(self.hass.states.get(self._source))

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._async_source_changed
            )
        )
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_midnight, hour=0, minute=0, second=0
            )
        )

    @callback
    def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        changed = self._check_period(dt_util.now())
        if self._process_source(event.data["new_state"]):
            changed = True
        if changed:
            self.async_write_ha_state()

    @callback
    def _async_midnight(self, now: datetime) -> None:
        if self._check_period(now):
            self.async_write_ha_state()

    # ---- logikk ----

    def _check_period(self, now: datetime) -> bool:
        """Nullstill ved ny dag/måned. Returnerer True hvis nullstilt."""
        period = self.entity_description.period
        start = _period_start(now, period)
        if self._attr_last_reset is not None and self._attr_last_reset >= start:
            return False
        previous_start = _period_start(start - timedelta(days=1), period)
        if self._attr_last_reset is not None and self._attr_last_reset >= previous_start:
            self._last_period = self._value
        else:
            self._last_period = 0.0  # mer enn én periode siden sist
        self._value = 0.0
        self._attr_last_reset = start
        return True

    def _current_price(self) -> float | None:
        price = _read_price(self.hass.states.get(self._price_entity))
        if price is not None:
            self._last_price = price
        return self._last_price

    def _process_source(self, state: State | None) -> bool:
        """Legg til økningen siden forrige avlesning. True hvis verdien endret seg."""
        reading = _read_energy_kwh(state)
        if reading is None:
            return False
        if self._last_source is None:
            self._last_source = reading  # første avlesning = baseline
            return False

        if reading >= self._last_source:
            delta = reading - self._last_source
        elif reading < self._last_source * RESET_THRESHOLD:
            delta = reading  # kildemåleren er nullstilt
        else:
            return False  # lite fall = støy, behold forrige baseline
        self._last_source = reading

        if delta <= 0:
            return False

        if self.entity_description.price is None:
            self._value += delta
            return True

        price = self._current_price()
        if price is None:
            _LOGGER.debug(
                "%s: ingen gyldig pris fra %s, hopper over %.4f kWh",
                self.entity_id,
                self._price_entity,
                delta,
            )
            return False
        self._value += delta * price
        return True

    # ---- handling ----

    async def async_calibrate(self, value: float) -> None:
        """Sett verdien manuelt (f.eks. for å rette opp en feilmåling)."""
        self._value = value
        self.async_write_ha_state()
