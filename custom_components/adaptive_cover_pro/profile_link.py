"""Shared Building Profile link helpers.

A neutral home for the profile/cover linkage helpers so both ``config_flow``
(link/unlink UI) and ``__init__`` (live propagation + deletion cleanup) can
reuse a single source. It must not live in ``helpers.py`` — that module is
imported by ``cover_types.base``, and these helpers need ``get_policy`` from
``cover_types``, which would create an import cycle.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    BUILDING_PROFILE_SENSOR_KEYS,
    CONF_BUILDING_PROFILE_ID,
    CONF_SENSOR_TYPE,
    DOMAIN,
)
from .cover_types import get_policy


def classify_profile_sensor_source(
    key: str, cover_options: dict, profile_options: dict
) -> tuple[str, Any]:
    """Return ``(source, effective_value)`` for one shared-sensor key.

    The single source of truth for "is this cover using the profile's value or
    its own?" — shared by the diagnostics sensor-source block and the Building
    Profile overview. A key is ``"profile"`` when the linked profile holds a
    NON-EMPTY value (it was copied into the cover on link), matching the same
    ``v not in (None, "", [])`` rule ``_copy_profile_to_cover`` uses; otherwise
    it is ``"local"`` and the cover keeps its own value (Q2 fallback).
    """
    profile_value = profile_options.get(key)
    if profile_value not in (None, "", []):
        return "profile", profile_value
    return "local", cover_options.get(key)


def _building_profile_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return all Building Profile config entries (controls_cover == False)."""
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if not get_policy(e.data.get(CONF_SENSOR_TYPE)).controls_cover
    ]


def _covers_linked_to(
    hass: HomeAssistant, profile_entry: ConfigEntry
) -> list[ConfigEntry]:
    """Return every ACP entry linked to ``profile_entry`` via its id."""
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.options.get(CONF_BUILDING_PROFILE_ID) == profile_entry.entry_id
    ]


def _copy_profile_to_cover(
    hass: HomeAssistant, profile_entry: ConfigEntry, cover_entry: ConfigEntry
) -> None:
    """Copy a profile's non-empty shared-sensor subset into a linked cover.

    Q2 per-key fallback: only overwrite a cover key when the profile holds a
    NON-EMPTY value for it, so a profile that leaves a field blank never wipes
    the cover's own locally-configured sensor. Stamps ``CONF_BUILDING_PROFILE_ID``
    and reuses the sync execution pattern (``async_update_entry`` merge) — the
    update fires the cover's existing self-reload listener. This is the single
    shared copier; the profile-change propagation listener reuses it.
    """
    subset = {
        k: v
        for k, v in profile_entry.options.items()
        if k in BUILDING_PROFILE_SENSOR_KEYS and v not in (None, "", [])
    }
    hass.config_entries.async_update_entry(
        cover_entry,
        options={
            **cover_entry.options,
            **subset,
            CONF_BUILDING_PROFILE_ID: profile_entry.entry_id,
        },
    )
