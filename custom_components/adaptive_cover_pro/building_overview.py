"""Render a read-only Building Profile overview (markdown).

A Building Profile is a virtual config entry that holds shared sensor IDs and
copies them into every linked cover (see ``profile_link``). This module builds
the human-readable overview shown in the profile's options flow, scoped to the
covers linked to one profile. Three sections:

1. **Shared sensors** — what the profile defines, plus warnings where a linked
   cover's effective value diverges from the profile (local override, or the Q2
   fallback where the profile leaves a key blank).
2. **Linked covers** — a roster of name, cover-type label, controlled entities.
3. **Settings comparison** — every configured per-cover setting, with rows that
   are identical across all covers marked ``=`` and rows that differ marked
   ``≠`` so differences stand out within the full picture.

English-only by design (a maintenance/diagnostic view, mirroring the
English-deferred ``summary_geometry_lines``); the markdown body is authored
through the ``_LABELS`` dict so a later ``acp-translate`` pass can lift it into
``summary_i18n`` without restructuring. Only the option keys / values are read —
this never branches on cover-type strings (uses ``get_policy``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    BUILDING_PROFILE_SENSOR_KEYS,
    CONF_AZIMUTH,
    CONF_CLIMATE_MODE,
    CONF_CLOUD_COVERAGE_ENTITY,
    CONF_CLOUD_COVERAGE_THRESHOLD,
    CONF_DAYTIME_GATE_SENSORS,
    CONF_DAYTIME_GATE_TEMPLATE,
    CONF_DEFAULT_HEIGHT,
    CONF_DELTA_POSITION,
    CONF_DELTA_TIME,
    CONF_ENABLE_GLARE_ZONES,
    CONF_ENTITIES,
    CONF_FOV_LEFT,
    CONF_FOV_RIGHT,
    CONF_IRRADIANCE_ENTITY,
    CONF_IRRADIANCE_THRESHOLD,
    CONF_IS_SUNNY_SENSOR,
    CONF_IS_SUNNY_TEMPLATE,
    CONF_LUX_ENTITY,
    CONF_LUX_THRESHOLD,
    CONF_MANUAL_OVERRIDE_DURATION,
    CONF_MANUAL_THRESHOLD,
    CONF_MAX_ELEVATION,
    CONF_MAX_POSITION,
    CONF_MIN_ELEVATION,
    CONF_MIN_POSITION,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_SENSOR_TYPE,
    CONF_SUNRISE_TIME_ENTITY,
    CONF_SUNSET_POS,
    CONF_SUNSET_TIME_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_IS_RAINING_SENSOR,
    CONF_WEATHER_IS_WINDY_SENSOR,
    CONF_WEATHER_RAIN_SENSOR,
    CONF_WEATHER_SEVERE_SENSORS,
    CONF_WEATHER_WIND_DIRECTION_SENSOR,
    CONF_WEATHER_WIND_SPEED_SENSOR,
    CUSTOM_POSITION_SLOTS,
)
from .cover_types import get_policy
from .helpers import (
    custom_position_slot_configured,
    is_template_string,
    motion_entities,
)
from .profile_link import classify_profile_sensor_source

_NOT_SET = "(not set)"
_NONE = "—"
# Above this many covers a wide markdown table wraps badly in the HA form, so
# fall back to a per-cover bulleted list with the differing keys flagged.
_MATRIX_COVER_LIMIT = 4

# English labels for the markdown body. Keyed by dotted name so a future
# acp-translate pass can lift the whole block into summary_i18n unchanged.
_LABELS: dict[str, str] = {
    "title": "**Building Profile — Overview**",
    "linked_count": "{n} cover(s) linked to this profile.",
    "no_covers": (
        "No covers are linked to this profile yet. Link a cover from its own "
        "options (**Building Profile** step) to share these sensors."
    ),
    "shared_header": "**Shared sensors**",
    "shared_hint": "Sensors this profile defines and copies into each linked cover.",
    "diverge_override": (
        "⚠ {cover} overrides shared **{label}** locally "
        "(uses `{cover_value}`, profile defines `{profile_value}`)."
    ),
    "diverge_local": (
        "ℹ {cover} keeps a local **{label}** (`{cover_value}`) — "
        "the profile does not define it (Q2 fallback)."
    ),
    "roster_header": "**Linked covers**",
    "matrix_header": "**Settings comparison**",
    "matrix_hint": "All configured settings. `=` identical across covers, `≠` differs.",
    "col_setting": "Setting",
}

# Friendly labels for the shared-sensor keys. Falls back to a humanized key.
_SENSOR_LABELS: dict[str, str] = {
    CONF_WEATHER_ENTITY: "Weather entity",
    CONF_OUTSIDETEMP_ENTITY: "Outside temperature",
    CONF_LUX_ENTITY: "Illuminance (lux)",
    CONF_IRRADIANCE_ENTITY: "Irradiance",
    CONF_CLOUD_COVERAGE_ENTITY: "Cloud coverage",
    CONF_IS_SUNNY_SENSOR: "Is-sunny sensor",
    CONF_IS_SUNNY_TEMPLATE: "Is-sunny template",
    CONF_WEATHER_WIND_SPEED_SENSOR: "Wind speed",
    CONF_WEATHER_WIND_DIRECTION_SENSOR: "Wind direction",
    CONF_WEATHER_RAIN_SENSOR: "Rain rate",
    CONF_WEATHER_IS_RAINING_SENSOR: "Is-raining sensor",
    CONF_WEATHER_IS_WINDY_SENSOR: "Is-windy sensor",
    CONF_WEATHER_SEVERE_SENSORS: "Severe-weather sensors",
    CONF_DAYTIME_GATE_SENSORS: "Daytime gate sensors",
    CONF_DAYTIME_GATE_TEMPLATE: "Daytime gate template",
    CONF_SUNSET_TIME_ENTITY: "Sunset time entity",
    CONF_SUNRISE_TIME_ENTITY: "Sunrise time entity",
}

# Shared-sensor keys shown in the "Shared sensors" listing, in display order.
# The four *_template_mode combine-mode keys live in BUILDING_PROFILE_SENSOR_KEYS
# but are toggles, not sensors — they are excluded from the listing while still
# covered by the divergence scan below (which walks the full key set).
_SHARED_DISPLAY_KEYS: tuple[str, ...] = (
    CONF_WEATHER_ENTITY,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_LUX_ENTITY,
    CONF_IRRADIANCE_ENTITY,
    CONF_CLOUD_COVERAGE_ENTITY,
    CONF_IS_SUNNY_SENSOR,
    CONF_IS_SUNNY_TEMPLATE,
    CONF_WEATHER_WIND_SPEED_SENSOR,
    CONF_WEATHER_WIND_DIRECTION_SENSOR,
    CONF_WEATHER_RAIN_SENSOR,
    CONF_WEATHER_IS_RAINING_SENSOR,
    CONF_WEATHER_IS_WINDY_SENSOR,
    CONF_WEATHER_SEVERE_SENSORS,
    CONF_DAYTIME_GATE_SENSORS,
    CONF_DAYTIME_GATE_TEMPLATE,
    CONF_SUNSET_TIME_ENTITY,
    CONF_SUNRISE_TIME_ENTITY,
)


@dataclass(frozen=True)
class _CoverRecord:
    """A linked cover's identity + options, decoupled from ConfigEntry for tests."""

    name: str
    sensor_type: str | None
    options: dict
    entities: list[str] = field(default_factory=list)

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> _CoverRecord:
        data = entry.data or {}
        options = dict(entry.options or {})
        return cls(
            name=entry.title or data.get("name") or "Cover",
            sensor_type=data.get(CONF_SENSOR_TYPE),
            options=options,
            entities=list(options.get(CONF_ENTITIES, []) or []),
        )


@dataclass(frozen=True)
class _DiffSpec:
    """One comparable setting: a label, a bucket, and a per-cover formatter."""

    label: str
    bucket: str
    extract: Callable[[_CoverRecord], str]


def _fmt(value: Any, suffix: str = "") -> str:
    """Format a scalar option value as a compact cell, or the em-dash for empty."""
    if value in (None, "", []):
        return _NONE
    return f"{value}{suffix}"


def _sensor_label(key: str) -> str:
    return _SENSOR_LABELS.get(key) or key.replace("_", " ").capitalize()


def _entity_repr(value: Any) -> str:
    """Render a sensor value (entity id, template, or list) for a warning line."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if is_template_string(value):
        return "[template]"
    return str(value)


def _count_custom_slots(options: Mapping) -> int:
    return sum(
        custom_position_slot_configured(options, slot_keys)
        for slot_keys in CUSTOM_POSITION_SLOTS.values()
    )


def _geometry_cell(record: _CoverRecord) -> str:
    if not record.sensor_type:
        return _NONE
    lines = get_policy(record.sensor_type).summary_geometry_lines(record.options)
    return "; ".join(lines) if lines else _NONE


_COMPARISON_SPECS: tuple[_DiffSpec, ...] = (
    _DiffSpec(
        "Cover type",
        "Type",
        lambda r: get_policy(r.sensor_type).display_label() if r.sensor_type else _NONE,
    ),
    _DiffSpec(
        "Window azimuth", "Geometry", lambda r: _fmt(r.options.get(CONF_AZIMUTH), "°")
    ),
    _DiffSpec(
        "Field of view",
        "Geometry",
        lambda r: f"{_fmt(r.options.get(CONF_FOV_LEFT))}/{_fmt(r.options.get(CONF_FOV_RIGHT))}°",
    ),
    _DiffSpec(
        "Elevation limits",
        "Geometry",
        lambda r: f"{_fmt(r.options.get(CONF_MIN_ELEVATION))}–{_fmt(r.options.get(CONF_MAX_ELEVATION))}°",
    ),
    _DiffSpec("Geometry", "Geometry", _geometry_cell),
    _DiffSpec(
        "Climate mode", "Climate", lambda r: _fmt(r.options.get(CONF_CLIMATE_MODE))
    ),
    _DiffSpec(
        "Lux threshold", "Light", lambda r: _fmt(r.options.get(CONF_LUX_THRESHOLD))
    ),
    _DiffSpec(
        "Irradiance threshold",
        "Light",
        lambda r: _fmt(r.options.get(CONF_IRRADIANCE_THRESHOLD)),
    ),
    _DiffSpec(
        "Cloud coverage threshold",
        "Light",
        lambda r: _fmt(r.options.get(CONF_CLOUD_COVERAGE_THRESHOLD), "%"),
    ),
    _DiffSpec(
        "Position limits",
        "Position",
        lambda r: f"{_fmt(r.options.get(CONF_MIN_POSITION))}–{_fmt(r.options.get(CONF_MAX_POSITION))}",
    ),
    _DiffSpec(
        "Default position",
        "Position",
        lambda r: _fmt(r.options.get(CONF_DEFAULT_HEIGHT)),
    ),
    _DiffSpec(
        "Sunset position", "Position", lambda r: _fmt(r.options.get(CONF_SUNSET_POS))
    ),
    _DiffSpec(
        "Custom positions",
        "Custom",
        lambda r: (
            f"{_count_custom_slots(r.options)} slot(s)"
            if _count_custom_slots(r.options)
            else _NONE
        ),
    ),
    _DiffSpec(
        "Glare zones",
        "Glare",
        lambda r: "enabled" if r.options.get(CONF_ENABLE_GLARE_ZONES) else _NONE,
    ),
    _DiffSpec(
        "Motion",
        "Motion",
        lambda r: "enabled" if motion_entities(r.options) else _NONE,
    ),
    _DiffSpec(
        "Manual override",
        "Manual",
        lambda r: f"{_fmt(r.options.get(CONF_MANUAL_OVERRIDE_DURATION))} min / "
        f"{_fmt(r.options.get(CONF_MANUAL_THRESHOLD))}%",
    ),
    _DiffSpec(
        "Delta position / time",
        "Automation",
        lambda r: f"{_fmt(r.options.get(CONF_DELTA_POSITION))}% / {_fmt(r.options.get(CONF_DELTA_TIME))} min",
    ),
)


def build_building_overview(
    profile_entry: ConfigEntry,
    linked_cover_entries: list[ConfigEntry],
    hass: HomeAssistant | None = None,  # noqa: ARG001 — reserved for future live state
) -> str:
    """Build the markdown overview for one Building Profile and its linked covers."""
    profile_options = dict(profile_entry.options or {})
    records = [_CoverRecord.from_entry(e) for e in linked_cover_entries]

    blocks: list[str] = [_LABELS["title"]]
    if not records:
        blocks.append(_LABELS["no_covers"])
        blocks.append("\n".join(_build_shared_sensors_section(profile_options, [])))
        return "\n\n".join(blocks)

    blocks.append(_LABELS["linked_count"].format(n=len(records)))
    blocks.append("\n".join(_build_shared_sensors_section(profile_options, records)))
    blocks.append("\n".join(_build_linked_covers_section(records)))
    blocks.append("\n".join(_build_comparison_section(records)))
    return "\n\n".join(blocks)


def _build_shared_sensors_section(
    profile_options: dict, records: list[_CoverRecord]
) -> list[str]:
    lines = [_LABELS["shared_header"], "", _LABELS["shared_hint"], ""]
    for key in _SHARED_DISPLAY_KEYS:
        value = profile_options.get(key)
        rendered = _entity_repr(value) if value not in (None, "", []) else _NOT_SET
        lines.append(f"- {_sensor_label(key)}: {rendered}")

    warnings = _divergence_warnings(profile_options, records)
    if warnings:
        lines.append("")
        lines.extend(warnings)
    return lines


def _divergence_warnings(
    profile_options: dict, records: list[_CoverRecord]
) -> list[str]:
    """Flag linked covers whose effective sensor value diverges from the profile."""
    warnings: list[str] = []
    for record in records:
        for key in sorted(BUILDING_PROFILE_SENSOR_KEYS):
            source, _ = classify_profile_sensor_source(
                key, record.options, profile_options
            )
            profile_value = profile_options.get(key)
            cover_value = record.options.get(key)
            if source == "profile":
                if cover_value != profile_value:
                    warnings.append(
                        _LABELS["diverge_override"].format(
                            cover=record.name,
                            label=_sensor_label(key),
                            cover_value=_entity_repr(cover_value),
                            profile_value=_entity_repr(profile_value),
                        )
                    )
            elif cover_value not in (None, "", []):
                warnings.append(
                    _LABELS["diverge_local"].format(
                        cover=record.name,
                        label=_sensor_label(key),
                        cover_value=_entity_repr(cover_value),
                    )
                )
    return warnings


def _build_linked_covers_section(records: list[_CoverRecord]) -> list[str]:
    lines = [_LABELS["roster_header"], ""]
    for record in records:
        type_label = (
            get_policy(record.sensor_type).display_label()
            if record.sensor_type
            else _NONE
        )
        entities = ", ".join(record.entities) if record.entities else _NONE
        lines.append(f"- **{record.name}** — {type_label} — {entities}")
    return lines


def _build_comparison_section(records: list[_CoverRecord]) -> list[str]:
    rows = []
    for spec in _COMPARISON_SPECS:
        values = [spec.extract(r) for r in records]
        differs = len(set(values)) > 1
        rows.append((spec, values, differs))

    lines = [_LABELS["matrix_header"], "", _LABELS["matrix_hint"], ""]
    if len(records) > _MATRIX_COVER_LIMIT:
        lines.extend(_comparison_as_list(records, rows))
    else:
        lines.extend(_comparison_as_table(records, rows))
    return lines


def _comparison_as_table(records: list[_CoverRecord], rows: list) -> list[str]:
    header = (
        f"| | {_LABELS['col_setting']} | " + " | ".join(r.name for r in records) + " |"
    )
    sep = "|" + "---|" * (len(records) + 2)
    lines = [header, sep]
    for spec, values, differs in rows:
        marker = "≠" if differs else "="
        cells = " | ".join(values)
        lines.append(f"| {marker} | {spec.label} | {cells} |")
    return lines


def _comparison_as_list(records: list[_CoverRecord], rows: list) -> list[str]:
    """Per-cover bulleted fallback for many covers; flag keys that differ."""
    lines: list[str] = []
    for idx, record in enumerate(records):
        type_label = (
            get_policy(record.sensor_type).display_label()
            if record.sensor_type
            else _NONE
        )
        lines.append(f"**{record.name}** ({type_label})")
        for spec, values, differs in rows:
            marker = " ≠" if differs else ""
            lines.append(f"- {spec.label}: {values[idx]}{marker}")
        lines.append("")
    return lines
