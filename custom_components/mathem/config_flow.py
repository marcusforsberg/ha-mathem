"""Config and options flow.

The user step validates credentials by performing the login handshake. The
options flow reads the delivery address live from the cart and
builds filter-token checkboxes from the runtime-discovered vocabulary, so a
public release offers whatever Mathem supports without a code change.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_AMBIGUITY,
    CONF_DEFAULT_PROFILE,
    CONF_DELIVERY_ADDRESS_ID,
    CONF_DELIVERY_DAY_POLL_MINUTES,
    CONF_FILTER_TOKENS,
    CONF_PASSWORD,
    CONF_POLL_MINUTES,
    CONF_PROFILES,
    CONF_UNATTENDED,
    CONF_USERNAME,
    AMBIGUITY_ASK,
    AMBIGUITY_REJECT,
    DEFAULT_DELIVERY_DAY_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    FILTER_PROBE_QUERIES,
)
from .config_helpers import extract_addresses
from .mathem_client import MathemAuthError, MathemClient, MathemError, MathemSession
from .mathem_client.profiles import build_profiles

_LOGGER = logging.getLogger(__name__)


async def _validate_login(hass, username: str, password: str) -> MathemClient:
    """Log in and return a client, or raise MathemError."""
    session = MathemSession(async_get_clientsession(hass))
    await session.login(username, password)
    if not await session.verify_authenticated():
        raise MathemError("login did not establish an authenticated session")
    return MathemClient(session)


class MathemConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial credential setup and reauth."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].casefold())
            self._abort_if_unique_id_configured()
            try:
                await _validate_login(
                    self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except MathemAuthError as err:
                _LOGGER.warning("Mathem rejected the credentials: %s", err)
                errors["base"] = "invalid_auth"
            except MathemError as err:
                _LOGGER.warning("Mathem login failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=user_input,
                    options={CONF_UNATTENDED: True, CONF_POLL_MINUTES: DEFAULT_POLL_MINUTES},
                )

        schema = vol.Schema(
            {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_username = entry_data[CONF_USERNAME]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_login(self.hass, self._reauth_username, user_input[CONF_PASSWORD])
            except MathemAuthError as err:
                _LOGGER.warning("Mathem rejected the new password: %s", err)
                errors["base"] = "invalid_auth"
            except MathemError as err:
                _LOGGER.warning("Mathem re-authentication failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                assert entry is not None
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> MathemOptionsFlow:
        return MathemOptionsFlow()


class MathemOptionsFlow(OptionsFlow):
    """Delivery address, unattended toggle, poll interval, profiles, filters."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            profiles_text = user_input.pop("profiles_json", "").strip()
            profiles: dict[str, Any] = options.get(CONF_PROFILES, {})
            if profiles_text:
                try:
                    parsed = json.loads(profiles_text)
                    build_profiles(parsed)  # validate inheritance and shapes
                    profiles = parsed
                except (ValueError, TypeError) as err:
                    _LOGGER.warning("invalid profiles JSON: %s", err)
                    errors["base"] = "invalid_profiles"
            if not errors:
                # The dropdown submits a string; store an int so consumers do
                # not have to care which widget produced the value.
                raw_address = user_input.get(CONF_DELIVERY_ADDRESS_ID)
                try:
                    address_id = int(raw_address) if raw_address not in (None, "") else None
                except (TypeError, ValueError):
                    address_id = None
                new_options = {
                    CONF_DELIVERY_ADDRESS_ID: address_id,
                    CONF_UNATTENDED: user_input.get(CONF_UNATTENDED, True),
                    CONF_POLL_MINUTES: user_input.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES),
                    CONF_DELIVERY_DAY_POLL_MINUTES: user_input.get(
                        CONF_DELIVERY_DAY_POLL_MINUTES, DEFAULT_DELIVERY_DAY_POLL_MINUTES
                    ),
                    CONF_DEFAULT_PROFILE: user_input.get(CONF_DEFAULT_PROFILE) or None,
                    CONF_AMBIGUITY: user_input.get(CONF_AMBIGUITY, AMBIGUITY_ASK),
                    CONF_FILTER_TOKENS: user_input.get(CONF_FILTER_TOKENS, []),
                    CONF_PROFILES: profiles,
                }
                return self.async_create_entry(title="", data=new_options)

        # Live lookups for the form: addresses and the filter vocabulary.
        address_options, filter_vocab = await self._live_choices()
        profile_names = list((options.get(CONF_PROFILES) or {}).keys())

        schema_dict: dict[Any, Any] = {}
        if address_options:
            # Option values are strings: the frontend round-trips a selection as
            # a string, so int keys would never match the stored value and the
            # dropdown would reopen with nothing selected. Saving coerces back.
            schema_dict[vol.Optional(CONF_DELIVERY_ADDRESS_ID)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=str(addr_id), label=label)
                        for addr_id, label in address_options.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            schema_dict[
                vol.Optional(CONF_DELIVERY_ADDRESS_ID, default=options.get(CONF_DELIVERY_ADDRESS_ID))
            ] = vol.Coerce(int)

        schema_dict[vol.Optional(CONF_UNATTENDED, default=options.get(CONF_UNATTENDED, True))] = bool
        schema_dict[
            vol.Optional(CONF_POLL_MINUTES, default=options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES))
        ] = vol.All(int, vol.Range(min=1, max=180))
        schema_dict[
            vol.Optional(
                CONF_DELIVERY_DAY_POLL_MINUTES,
                default=options.get(CONF_DELIVERY_DAY_POLL_MINUTES, DEFAULT_DELIVERY_DAY_POLL_MINUTES),
            )
        ] = vol.All(int, vol.Range(min=1, max=60))
        schema_dict[
            vol.Optional(CONF_AMBIGUITY, default=options.get(CONF_AMBIGUITY, AMBIGUITY_ASK))
        ] = vol.In({AMBIGUITY_ASK: "Ask", AMBIGUITY_REJECT: "Reject"})
        if profile_names:
            schema_dict[
                vol.Optional(CONF_DEFAULT_PROFILE, default=options.get(CONF_DEFAULT_PROFILE) or profile_names[0])
            ] = vol.In(profile_names)
        if filter_vocab:
            schema_dict[
                vol.Optional(CONF_FILTER_TOKENS, default=options.get(CONF_FILTER_TOKENS, []))
            ] = cv_multi_select(filter_vocab)
        # Prefilled with what is stored, so the rules can be read back and
        # edited rather than retyped. Submitting it empty keeps them; an empty
        # JSON object clears them.
        current_profiles = options.get(CONF_PROFILES) or {}
        schema_dict[
            vol.Optional(
                "profiles_json",
                default=(
                    json.dumps(current_profiles, indent=2, ensure_ascii=False)
                    if current_profiles
                    else ""
                ),
            )
        ] = str

        schema = vol.Schema(schema_dict)
        if address_options:
            # Preselect the saved address, else the primary one (listed first).
            current = options.get(CONF_DELIVERY_ADDRESS_ID)
            selected = current if current in address_options else next(iter(address_options))
            schema = self.add_suggested_values_to_schema(
                schema, {CONF_DELIVERY_ADDRESS_ID: str(selected)}
            )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _live_choices(self) -> tuple[dict[int, str], dict[str, str]]:
        """Fetch address options and the filter vocabulary; empty on failure.

        Addresses are read from the slot picker (which lists the account's
        delivery addresses) and the cart, so the address field is a populated
        picker with no manual lookup required.
        """
        session = MathemSession(async_get_clientsession(self.hass))
        client = MathemClient(session)
        addresses: dict[int, str] = {}
        vocab: dict[str, str] = {}
        # The slot picker lists every address on the account; the cart only
        # exposes the active one, so it is a fallback rather than a second call.
        for path, params in (
            ("/slot-picker/slots/", {"num-days": 3, "from-index": 0}),
            ("/cart/", {"group-by": "recipes"}),
        ):
            try:
                raw = await session.get(path, params=params)
            except MathemError as err:
                _LOGGER.warning("Mathem: could not read addresses from %s: %s", path, err)
                continue
            addresses.update(extract_addresses(raw))
            if addresses:
                break
        if not addresses:
            # Without this the address field silently degrades to manual id entry.
            _LOGGER.warning(
                "Mathem: no delivery addresses could be read from the account; "
                "the delivery address must be entered manually"
            )
        try:
            vocab = await client.products.discover_filters(FILTER_PROBE_QUERIES)
        except MathemError as err:
            _LOGGER.debug("could not discover filters: %s", err)
        return addresses, vocab


def cv_multi_select(options: dict[str, str]):
    """Multi-select validator (thin wrapper to keep imports local)."""
    from homeassistant.helpers import config_validation as cv

    return cv.multi_select(options)
