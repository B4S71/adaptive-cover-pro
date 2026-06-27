"""Pure-function tests for the Building Profile overview / override views.

These read only ``entry.data`` / ``entry.options`` (never live HA state), so they
drive the builders with lightweight stub entries — no ``hass`` required.
"""

from __future__ import annotations

from custom_components.adaptive_cover_pro.building_overview import (
    build_building_overview,
    build_override_records,
    profile_value_breakdown,
)
from custom_components.adaptive_cover_pro.const import (
    CONF_CLIMATE_MODE,
    CONF_DELTA_POSITION,
    CONF_ENTITIES,
    CONF_LUX_ENTITY,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_PROFILE_SENSOR_OVERRIDES,
    CONF_SENSOR_TYPE,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_WIND_SPEED_SENSOR,
    DEFAULT_DELTA_POSITION,
    CoverType,
)


class _Entry:
    """Minimal ConfigEntry stand-in: entry_id + title + data + options."""

    def __init__(self, title, data, options, entry_id=None):
        self.title = title
        self.data = data
        self.options = options
        self.entry_id = entry_id or title.lower().replace(" ", "_")


def _profile(options=None):
    return _Entry(
        "My Building",
        {"name": "My Building", CONF_SENSOR_TYPE: CoverType.BUILDING_PROFILE},
        options or {},
        entry_id="profile_1",
    )


def _cover(name, sensor_type=CoverType.BLIND, options=None):
    opts = {CONF_ENTITIES: [f"cover.{name.lower()}"]}
    opts.update(options or {})
    return _Entry(name, {"name": name, CONF_SENSOR_TYPE: sensor_type}, opts)


def test_zero_linked_covers_renders_hint():
    text = build_building_overview(_profile({CONF_WEATHER_ENTITY: "weather.home"}), [])
    assert "No covers are linked to this profile yet" in text
    assert "Shared sensors" in text
    assert "weather.home" in text


def test_shared_sensors_only_lists_defined():
    profile = _profile(
        {CONF_WEATHER_ENTITY: "weather.home", CONF_OUTSIDETEMP_ENTITY: "sensor.out"}
    )
    cover = _cover("Living", options={CONF_WEATHER_ENTITY: "weather.home"})
    text = build_building_overview(profile, [cover])
    assert "Weather entity: weather.home" in text
    assert "Outside temperature: sensor.out" in text
    # Sensors the profile does NOT define are omitted entirely (no "(not set)").
    assert "(not set)" not in text
    assert "Illuminance (lux):" not in text


def test_shared_sensors_none_defined():
    profile = _profile({})
    cover = _cover("Living")
    text = build_building_overview(profile, [cover])
    assert "No shared sensors defined on this profile." in text


def test_local_override_note():
    """A cover that overrides a profile-defined sensor is flagged (no jargon)."""
    profile = _profile({CONF_WEATHER_ENTITY: "weather.home"})
    cover = _cover(
        "Bedroom",
        options={
            CONF_WEATHER_ENTITY: "weather.upstairs",
            CONF_PROFILE_SENSOR_OVERRIDES: [CONF_WEATHER_ENTITY],
        },
    )
    text = build_building_overview(profile, [cover])
    assert "local override of **Weather entity**" in text
    assert "weather.upstairs" in text
    assert "weather.home" in text
    assert "Q2" not in text


def test_local_sensor_note():
    """Profile blank but cover has its own value → a 'Local sensor' note."""
    profile = _profile({})
    cover = _cover("Office", options={CONF_LUX_ENTITY: "sensor.office_lux"})
    text = build_building_overview(profile, [cover])
    assert "local **Illuminance (lux)**" in text
    assert "sensor.office_lux" in text
    assert "profile: not set" in text


def test_fully_inherited_cover_has_no_notes():
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
    assert "ℹ" not in text


def test_roster_lists_type_label_and_entities():
    profile = _profile({})
    covers = [_cover("Living", CoverType.BLIND), _cover("Patio", CoverType.AWNING)]
    text = build_building_overview(profile, covers)
    assert "**Living** — Vertical Blind — cover.living" in text
    assert "**Patio** — Horizontal Awning — cover.patio" in text


def test_comparison_shows_only_differences_with_tail():
    profile = _profile({})
    living = _cover("Living", options={CONF_CLIMATE_MODE: True})
    bedroom = _cover("Bedroom", options={CONF_CLIMATE_MODE: False})
    text = build_building_overview(profile, [living, bedroom])
    lines = text.splitlines()
    assert any(
        "Climate mode" in line and "| on |" in line.replace(" ", " ") for line in lines
    )
    climate_row = next(line for line in lines if "Climate mode" in line)
    assert "on" in climate_row and "off" in climate_row
    # Behavioral-only: physical settings are never compared.
    assert "azimuth" not in text.lower()
    assert "Field of view" not in text
    assert "Geometry" not in text
    # Identical settings collapse into a tail count, not rows.
    assert "identical across all covers" in text


def test_comparison_all_identical():
    profile = _profile({})
    covers = [_cover("A"), _cover("B")]
    text = build_building_overview(profile, covers)
    assert "All comparable settings are identical" in text


def test_unset_equals_default_in_comparison():
    """A cover at the explicit default and an unset cover do not show as different."""
    profile = _profile({})
    a = _cover("A", options={CONF_DELTA_POSITION: DEFAULT_DELTA_POSITION})
    b = _cover("B")  # delta_position unset → normalizes to the same default
    text = build_building_overview(profile, [a, b])
    assert "Delta position" not in text
    assert "All comparable settings are identical" in text


def test_custom_positions_compared_as_count():
    profile = _profile({})
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
    assert "0 slot(s)" in custom_row


def test_many_covers_fall_back_to_bulleted_list():
    profile = _profile({})
    covers = [
        _cover(f"Cover{i}", options={CONF_CLIMATE_MODE: i % 2 == 0}) for i in range(6)
    ]
    text = build_building_overview(profile, covers)
    assert "| Setting |" not in text
    assert "**Cover0** (Vertical Blind)" in text
    assert "Climate mode:" in text


def test_profile_value_breakdown_statuses():
    profile = {
        CONF_WEATHER_ENTITY: "weather.home",
        CONF_OUTSIDETEMP_ENTITY: "sensor.out",
    }
    cover = {
        CONF_WEATHER_ENTITY: "weather.upstairs",
        CONF_PROFILE_SENSOR_OVERRIDES: [CONF_WEATHER_ENTITY],
        CONF_OUTSIDETEMP_ENTITY: "sensor.out",
        CONF_LUX_ENTITY: "sensor.bed_lux",
    }
    out = profile_value_breakdown(
        profile,
        cover,
        [CONF_WEATHER_ENTITY, CONF_OUTSIDETEMP_ENTITY, CONF_LUX_ENTITY],
        profile_title="My Building",
    )
    assert 'profile "My Building"' in out
    assert (
        "Weather entity: `weather.upstairs` — overridden (profile: `weather.home`)"
        in out
    )
    assert "Outside temperature: `sensor.out` (from profile)" in out
    assert "Illuminance (lux): `sensor.bed_lux` (profile not set — local)" in out


def test_profile_value_breakdown_empty_when_nothing_relevant():
    out = profile_value_breakdown({}, {}, [CONF_WEATHER_ENTITY], profile_title="X")
    assert out == ""


def test_build_override_records():
    profile = _profile({CONF_WEATHER_ENTITY: "weather.home"})
    bedroom = _cover(
        "Bedroom",
        options={
            CONF_WEATHER_ENTITY: "weather.upstairs",
            CONF_PROFILE_SENSOR_OVERRIDES: [CONF_WEATHER_ENTITY],
            CONF_LUX_ENTITY: "sensor.bed_lux",
        },
    )
    records = build_override_records(profile, [bedroom])
    by_key = {r.key: r for r in records}
    assert by_key[CONF_WEATHER_ENTITY].profile_sets_it is True
    assert by_key[CONF_WEATHER_ENTITY].local_text == "weather.upstairs"
    assert by_key[CONF_WEATHER_ENTITY].profile_text == "weather.home"
    assert by_key[CONF_LUX_ENTITY].profile_sets_it is False
    assert by_key[CONF_LUX_ENTITY].entry_id == "bedroom"
