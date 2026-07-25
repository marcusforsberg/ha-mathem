"""HTTP session: base URL, header injection, CSRF, login, checkout tripwire.

Wraps an ``aiohttp.ClientSession``. Home Assistant injects its shared session
(``async_get_clientsession``); standalone use creates one. Nothing here imports
Home Assistant.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

import aiohttp
from yarl import URL

from .errors import (
    CheckoutForbiddenError,
    MathemAuthError,
    MathemProtocolError,
    MathemRequestError,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.mathem.se/api/v1"
ORIGIN = "https://www.mathem.se"
# GET this first to seed the ``csrftoken`` cookie before POSTing the login.
LOGIN_PAGE_URL = "https://www.mathem.se/se/user/login/"

# A real desktop Chrome UA. Overridable via the constructor; the live client
# also sends sec-ch-ua* client hints but requests succeed without them.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Substring that must never appear in any URL this client requests. Structural
# guarantee that no code path can place an order.
FORBIDDEN_PATH = "checkout/confirm"


class MathemSession:
    """Authenticated transport for the Mathem API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        base_url: str = BASE_URL,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    # -- headers -----------------------------------------------------------

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "x-client-app": "tienda-web",
            "x-requested-case": "camel",
            "x-language": "sv",
            "x-country": "se",
            "origin": ORIGIN,
            "referer": "https://www.mathem.se/se/",
            "user-agent": self._user_agent,
        }

    def _csrf_token(self) -> str | None:
        """Read the ``csrftoken`` cookie from the shared cookie jar."""
        cookies = self._session.cookie_jar.filter_cookies(URL(ORIGIN))
        morsel = cookies.get("csrftoken")
        return morsel.value if morsel else None

    def has_session_cookie(self) -> bool:
        cookies = self._session.cookie_jar.filter_cookies(URL(ORIGIN))
        return "sessionid" in cookies

    # -- core request ------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        absolute: bool = False,
    ) -> Any:
        """Perform a request and return parsed JSON.

        ``path`` is appended to the API base unless ``absolute`` is set. POSTs
        get the ``x-csrftoken`` header. Any URL containing ``checkout/confirm``
        is refused before it leaves the process.
        """
        url = path if absolute else f"{self._base_url}/{path.lstrip('/')}"
        if FORBIDDEN_PATH in url:
            raise CheckoutForbiddenError(
                f"Refusing to request a checkout path: {url}"
            )

        headers = self._base_headers()
        if method.upper() == "POST":
            token = self._csrf_token()
            if token:
                headers["x-csrftoken"] = token

        _LOGGER.debug("%s %s params=%s", method, url, params)
        async with self._session.request(
            method, url, params=params, json=json, headers=headers
        ) as resp:
            body_text: str | None = None
            if resp.status in (401, 403):
                raise MathemAuthError(
                    f"{method} {url} -> HTTP {resp.status}; sessionid likely expired"
                )
            if resp.status >= 400:
                body_text = await resp.text()
                raise MathemRequestError(resp.status, method, url, body_text[:500])
            if resp.status == 204 or resp.content_length == 0:
                return None
            try:
                return await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError) as err:
                raise MathemProtocolError(
                    f"{method} {url} returned non-JSON body"
                ) from err

    async def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        return await self.request("POST", path, params=params, json=json)

    # -- login -------------------------------------------------------------

    async def login(self, username: str, password: str) -> Any:
        """Log in and populate the ``sessionid`` cookie.

        Sequence: GET the login page to seed ``csrftoken``, then POST the
        credentials as JSON, which is what the web client sends. The
        ``x-csrftoken`` header added to the POST must match the seeded cookie.
        """
        # Seed csrftoken. Browser-style Accept so we get the HTML page + cookie.
        async with self._session.get(
            LOGIN_PAGE_URL,
            headers={"user-agent": self._user_agent, "accept": "text/html"},
        ) as resp:
            if resp.status >= 400:
                raise MathemRequestError(resp.status, "GET", LOGIN_PAGE_URL)

        if self._csrf_token() is None:
            raise MathemProtocolError("csrftoken cookie was not set by the login page")

        return await self.post(
            "/user/login/", json={"username": username, "password": password}
        )

    async def verify_authenticated(self) -> bool:
        """Cheap authenticated probe. Doubles as keep-alive / 403 detector."""
        try:
            await self.get("/cart/", params={"group-by": "recipes"})
        except MathemAuthError:
            return False
        return True
