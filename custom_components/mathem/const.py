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
CONF_DEFAULT_PROFILE = "default_profile"
CONF_AMBIGUITY = "ambiguity_behaviour"
CONF_FILTER_TOKENS = "filter_tokens"
CONF_PROFILES = "profiles"

# Ambiguity behaviours when the resolver cannot settle on one product.
AMBIGUITY_ASK = "ask"
AMBIGUITY_REJECT = "reject"

# Polling.
DEFAULT_POLL_MINUTES = 30
BASE_POLL_INTERVAL = timedelta(minutes=DEFAULT_POLL_MINUTES)
DELIVERY_DAY_POLL_INTERVAL = timedelta(minutes=2)

# Pantry alias storage.
STORAGE_KEY = "mathem_pantry"
STORAGE_VERSION = 1

# Broad queries used to discover the filter vocabulary at runtime. Chosen to
# span produce, staples and dairy so distinct filter tokens surface; only the
# tokens applicable to a result set come back per query.
FILTER_PROBE_QUERIES = ("mjölk", "bröd", "ris", "tomat")

PLATFORMS = ["sensor", "calendar"]
