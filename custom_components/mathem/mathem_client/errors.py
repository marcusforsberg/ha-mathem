"""Exceptions raised by the Mathem client.

This module imports nothing from Home Assistant so the whole ``mathem_client``
subpackage stays publishable as a standalone library.
"""

from __future__ import annotations


class MathemError(Exception):
    """Base class for every error raised by the client."""


class MathemAuthError(MathemError):
    """Authentication failed or the session expired.

    Raised on a 401/403 from the API, which for the 30-day ``sessionid`` means
    the cookie has gone stale and the user must log in again.
    """


class MathemRequestError(MathemError):
    """A request returned a non-success status that is not an auth failure."""

    def __init__(self, status: int, method: str, path: str, body: str | None = None):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> HTTP {status}")


class MathemProtocolError(MathemError):
    """The response was well-formed HTTP but not the shape we expect.

    Used when a documented field is missing, so a silent API change surfaces
    loudly instead of being papered over with ``None``.
    """


class CheckoutForbiddenError(MathemError):
    """Raised if any code path ever tries to reach ``checkout/confirm``.

    The integration must never place an order. This exists as a tripwire: the
    session layer refuses the path, so a bug cannot silently check out.
    """
