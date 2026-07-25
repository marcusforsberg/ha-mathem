"""Runtime data attached to the config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import MathemCoordinator
from .mathem_client import MathemClient, Resolver
from .mathem_client.profiles import Profile
from .pantry import Pantry

type MathemConfigEntry = ConfigEntry["MathemRuntime"]


@dataclass(slots=True)
class MathemRuntime:
    """Everything the platforms and services need, per config entry."""

    client: MathemClient
    coordinator: MathemCoordinator
    pantry: Pantry
    profiles: dict[str, Profile]
    default_profile: str | None
    delivery_address_id: int | None
    unattended: bool

    def resolver(self) -> Resolver:
        return self.client.resolver(
            self.pantry.aliases, self.profiles, default_profile=self.default_profile
        )
