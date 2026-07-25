"""The Mathem integration.

A custom integration that creates entities and registers services. Services are
registered with a response, so their result is available to scripts and
automations via ``response_variable`` and to conversation agents that can call
services.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEFAULT_PROFILE,
    CONF_DELIVERY_ADDRESS_ID,
    CONF_DELIVERY_DAY_POLL_MINUTES,
    CONF_PASSWORD,
    CONF_POLL_MINUTES,
    CONF_PROFILES,
    CONF_UNATTENDED,
    CONF_USERNAME,
    DEFAULT_DELIVERY_DAY_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import MathemCoordinator
from .data import MathemConfigEntry, MathemRuntime
from .mathem_client import MathemAuthError, MathemClient, MathemError, MathemSession
from .mathem_client.profiles import build_profiles, default_profile_name
from .pantry import Pantry
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: MathemConfigEntry) -> bool:
    """Set up Mathem from a config entry."""
    session = MathemSession(async_get_clientsession(hass))
    client = MathemClient(session)

    # The 30-day sessionid lives only in the in-memory cookie jar, so log in on
    # every HA start.
    try:
        if not await session.verify_authenticated():
            await session.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
            if not await session.verify_authenticated():
                raise ConfigEntryAuthFailed("login did not establish a session")
    except MathemAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except MathemError as err:
        raise ConfigEntryNotReady(f"could not reach Mathem: {err}") from err

    pantry = Pantry(hass)
    await pantry.async_load()

    profiles = build_profiles(entry.options.get(CONF_PROFILES, {}))
    default_profile = entry.options.get(CONF_DEFAULT_PROFILE) or default_profile_name(profiles)

    base_interval = timedelta(
        minutes=entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES)
    )
    delivery_interval = timedelta(
        minutes=entry.options.get(
            CONF_DELIVERY_DAY_POLL_MINUTES, DEFAULT_DELIVERY_DAY_POLL_MINUTES
        )
    )
    coordinator = MathemCoordinator(
        hass, entry, client, base_interval=base_interval, delivery_interval=delivery_interval
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = MathemRuntime(
        client=client,
        coordinator=coordinator,
        pantry=pantry,
        profiles=profiles,
        default_profile=default_profile,
        delivery_address_id=entry.options.get(CONF_DELIVERY_ADDRESS_ID),
        unattended=entry.options.get(CONF_UNATTENDED, True),
    )

    async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MathemConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and len(hass.config_entries.async_loaded_entries(DOMAIN)) <= 1:
        # This entry is the last one still counted as loaded during unload.
        async_unregister_services(hass)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: MathemConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
