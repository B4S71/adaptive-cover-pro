"""set_position service — moves a cover to a position, clamping to min-mode floors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from voluptuous.validators import Coerce, Range

if TYPE_CHECKING:
    from homeassistant.core import ServiceCall

_LOGGER = logging.getLogger(__name__)

SET_POSITION_SCHEMA = vol.Schema(
    {
        vol.Required("position"): vol.All(Coerce(int), Range(min=0, max=100)),
    },
    extra=vol.PREVENT_EXTRA,
)


def _resolve_targets(hass, call):
    """Thin re-export so tests can patch the local name."""
    from . import _resolve_targets as _rt  # noqa: PLC0415

    return _rt(hass, call)


async def async_handle_set_position(call: ServiceCall) -> None:
    """Handle the set_position service call.

    For each targeted coordinator:
    1. Read active min-mode custom-position floors.
    2. Clamp requested position to the highest active floor (if any).
    3. Build context with force=True to bypass the manual-override gate.
    4. Call apply_position for each targeted entity.
    """
    hass = call.hass
    requested: int = call.data["position"]

    targets = _resolve_targets(hass, call)

    for coord, entity_filter in targets.items():
        options = coord.config_entry.options

        # Collect active min-mode floors
        states = coord._read_custom_position_sensor_states(options)  # noqa: SLF001
        floors = [s.position for s in states if s.is_on and s.min_mode]
        effective_floor = max(floors) if floors else 0

        clamped = max(requested, effective_floor)

        if clamped != requested:
            _LOGGER.info(
                "set_position: requested %d clamped to %d (active min-mode floor)",
                requested,
                clamped,
            )
        else:
            _LOGGER.debug(
                "set_position: requested %d, floor %d — no clamping needed",
                requested,
                effective_floor,
            )

        # Determine which entities to command
        entity_ids: list[str] = (
            list(entity_filter) if entity_filter is not None else list(coord.entities)
        )

        for entity_id in entity_ids:
            ctx = coord._build_position_context(  # noqa: SLF001
                entity_id, options, force=True
            )
            await coord._cmd_svc.apply_position(  # noqa: SLF001
                entity_id, clamped, "set_position", ctx
            )
