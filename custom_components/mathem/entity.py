"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MathemCoordinator


class MathemEntity(CoordinatorEntity[MathemCoordinator]):
    """Base for all Mathem entities; groups them under one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MathemCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Mathem",
            manufacturer="Mathem",
            entry_type=None,
        )
