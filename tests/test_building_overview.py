"""Pure-function tests for the Building Profile overview markdown builder.

The builder reads only ``entry.data`` / ``entry.options`` (never live HA state),
so these tests drive it with lightweight stub entries — no ``hass`` required.
"""

from __future__ import annotations

from custom_components.adaptive_cover_pro.building_overview import (
    build_building_overview,
)
from custom_components.adaptive_cover_pro.const import (
    CONF_AZIMUTH,
    CONF_CLIMATE_MODE,
    CONF_ENTITIES,
    CONF_LUX_ENTITY,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_SENSOR_TYPE,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_WIND_SPEED_SENSOR,
    CoverType,
)


class _Entry:
    """Minimal ConfigEntry stand-in: title + data + options."""

    def __init__(self, title, data, options):
        self.title = title
        self.data = data
        self.options = options


def _profile(options=None):
    return _Entry(
        "My Building",
        {"name": "My Building", CONF_SENSOR_TYPE: CoverType.BUILDING_PROFILE},
        options or {},
    )


def _cover(name, sensor_type=CoverType.BLIND, options=None):
    opts = {CONF_ENTITIES: [f"cover.{name.lower()}"]}
    opts.update(options or {})
    return _Entry(name, {"name": name, CONF_SENSOR_TYPE: sensor_type}, opts)


def test_zero_linked_covers_renders_hint():
    text = build_building_overview(_profile({CONF_WEATHER_ENTITY: "weather.home"}), [])
    assert "No covers are linked to this profile yet" in text
    # Shared sensors still listed so the profile is reviewable on its own.
    assert "Shared sensors" in text
    assert "weather.home" in text


def test_shared_sensors_set_and_not_set():
    profile = _profile(
        {CONF_WEATHER_ENTITY: "weather.home", CONF_OUTSIDETEMP_ENTITY: "sensor.out"}
    )
    cover = _cover("Living", options={CONF_WEATHER_ENTITY: "weather.home"})
    text = build_building_overview(profile, [cover])
    assert "Weather entity: weather.home" in text
    assert "Outside temperature: sensor.out" in text
    # A key the profile leaves blank shows "(not set)".
    assert "Illuminance (lux): (not set)" in text


def test_divergence_local_override_warns():
    """A linked cover whose value differs from a profile-defined key is flagged."""
    profile = _profile({CONF_WEATHER_ENTITY: "weather.home"})
    cover = _cover("Bedroom", options={CONF_WEATHER_ENTITY: "weather.upstairs"})
    text = build_building_overview(profile, [cover])
    assert "Bedroom overrides shared **Weather entity**" in text
    assert "weather.upstairs" in text
    assert "weather.home" in text


def test_divergence_q2_fallback_warns():
    """Profile blank but cover holds a local value → informational Q2 note."""
    profile = _profile({})  # no lux on the profile
    cover = _cover("Office", options={CONF_LUX_ENTITY: "sensor.office_lux"})
    text = build_building_overview(profile, [cover])
    assert "Office keeps a local **Illuminance (lux)**" in text
    assert "sensor.office_lux" in text


def test_fully_inherited_cover_has_no_warnings():
    profile = _profile(
        {
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_WEATHER_WIND_SPEED_SENSOR: "sensor.wind",
        }
    )
    cover = _cover(
        "Living",
        options={
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_WEATHER_WIND_SPEED_SENSOR: "sensor.wind",
        },
    )
    text = build_building_overview(profile, [cover])
    assert "⚠" not in text
    assert "Q2 fallback" not in text


def test_roster_lists_type_label_and_entities():
    profile = _profile({})
    covers = [
        _cover("Living", CoverType.BLIND),
        _cover("Patio", CoverType.AWNING),
    ]
    text = build_building_overview(profile, covers)
    assert "**Living** — Vertical Blind — cover.living" in text
    assert "**Patio** — Horizontal Awning — cover.patio" in text


def test_matrix_marks_identical_and_differing_rows():
    profile = _profile({})
    living = _cover("Living", options={CONF_AZIMUTH: 180, CONF_CLIMATE_MODE: "summer"})
    bedroom = _cover("Bedroom", options={CONF_AZIMUTH: 90, CONF_CLIMATE_MODE: "summer"})
    text = build_building_overview(profile, [living, bedroom])
    lines = text.splitlines()
    azimuth_row = next(line for line in lines if "Window azimuth" in line)
    climate_row = next(line for line in lines if "Climate mode" in line)
    assert azimuth_row.startswith("| ≠")  # azimuth differs
    assert climate_row.startswith("| =")  # climate mode identical
    assert "180°" in azimuth_row and "90°" in azimuth_row


def test_custom_positions_render_as_count_cell():
    profile = _profile({})
    # Slot 1 fully configured (a trigger sensor + a position).
    living = _cover(
        "Living",
        options={
            "custom_position_sensors_1": ["binary_sensor.x"],
            "custom_position_1": 50,
        },
    )
    bedroom = _cover("Bedroom")
    text = build_building_overview(profile, [living, bedroom])
    custom_row = next(line for line in text.splitlines() if "Custom positions" in line)
    assert "1 slot(s)" in custom_row
    assert "—" in custom_row  # bedroom has none


def test_many_covers_fall_back_to_bulleted_list():
    """Above the matrix cover-limit, render a per-cover list, flagging differences."""
    profile = _profile({})
    covers = [
        _cover(f"Cover{i}", options={CONF_AZIMUTH: 90 + i * 10}) for i in range(6)
    ]
    text = build_building_overview(profile, covers)
    # No markdown table header row in list mode.
    assert "| Setting |" not in text
    assert "**Cover0** (Vertical Blind)" in text
    # Azimuth differs across covers, so each cover's azimuth line is flagged.
    assert "Window azimuth: 90° ≠" in text
