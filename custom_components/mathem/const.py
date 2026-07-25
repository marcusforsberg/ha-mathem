"""Constants for the Mathem integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "mathem"

# Config entry data (secret-ish, set once at config time).
CONF_USERNAME = "username"
CONF_PASSWORD = "password"  # noqa: S105 - config key name, not a secret value

# Config entry options (tunable via the options flow).
CONF_DELIVERY_ADDRESS_ID = "delivery_address_id"
CONF_UNATTENDED = "unattended_delivery"
CONF_POLL_MINUTES = "poll_minutes"
CONF_DELIVERY_DAY_POLL_MINUTES = "delivery_day_poll_minutes"
CONF_DEFAULT_PROFILE = "default_profile"
CONF_AMBIGUITY = "ambiguity_behaviour"
CONF_FILTER_TOKENS = "filter_tokens"
CONF_PROFILES = "profiles"

# Ambiguity behaviours when the resolver cannot settle on one product.
AMBIGUITY_ASK = "ask"
AMBIGUITY_REJECT = "reject"

# Polling. The base interval is used normally; the shorter delivery-day
# interval kicks in while an order is inside its delivery window or being live
# tracked. Both are configurable; these are the defaults.
DEFAULT_POLL_MINUTES = 30
DEFAULT_DELIVERY_DAY_POLL_MINUTES = 2
BASE_POLL_INTERVAL = timedelta(minutes=DEFAULT_POLL_MINUTES)
DELIVERY_DAY_POLL_INTERVAL = timedelta(minutes=DEFAULT_DELIVERY_DAY_POLL_MINUTES)

# Pantry alias storage.
STORAGE_KEY = "mathem_pantry"
STORAGE_VERSION = 1

# Broad queries used to discover the filter vocabulary at runtime. Chosen to
# span produce, staples and dairy so distinct filter tokens surface; only the
# tokens applicable to a result set come back per query.
FILTER_PROBE_QUERIES = ("mjölk", "bröd", "ris", "tomat")

PLATFORMS = ["sensor", "calendar", "button"]
