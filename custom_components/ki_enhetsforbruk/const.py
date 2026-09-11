"""Konstanter for KI Enhetsforbruk."""

from typing import Final

DOMAIN: Final = "ki_enhetsforbruk"

# Hovedoppføring (options)
CONF_SPOT_PRICE: Final = "spot_price_entity"
CONF_NORGESPRIS: Final = "norgespris_entity"
CONF_ADD_SOURCES: Final = "add_sources"

# Enhet (subentry)
SUBENTRY_DEVICE: Final = "device"
CONF_SOURCE: Final = "source_entity"

DEFAULT_TITLE: Final = "KI Enhetsforbruk"
DEFAULT_SPOT_PRICE: Final = "sensor.totalpris_strompris_kroner"
DEFAULT_NORGESPRIS: Final = "sensor.norgespris_pris_na"

PERIOD_DAY: Final = "day"
PERIOD_MONTH: Final = "month"

PRICE_SPOT: Final = "spot"
PRICE_NORGESPRIS: Final = "norgespris"

# Faller kildemåleren til under 90 % av forrige verdi, tolkes det som at
# måleren er nullstilt. Mindre fall regnes som støy og ignoreres.
RESET_THRESHOLD: Final = 0.9

SERVICE_CALIBRATE: Final = "calibrate"
ATTR_VALUE: Final = "value"
