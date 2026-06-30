"""Tests for the Louvered Roof cover type (engine + policy).

Validates the occupancy-shading geometry against the worked reference table from
the feature design (Linz, solar noon ⇒ profile angle p = elevation), the
max-sunlight / max-shade mode trigger, the far-side mirror, and the policy
registration + climate winter/summer remap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from custom_components.adaptive_cover_pro.config_types import LouveredRoofConfig
from custom_components.adaptive_cover_pro.cover_types import get_policy
from custom_components.adaptive_cover_pro.cover_types.base import POLICY_REGISTRY
from custom_components.adaptive_cover_pro.engine.covers import (
    AdaptiveLouveredRoofCover,
)
from custom_components.adaptive_cover_pro.engine.covers.louvered_roof import (
    MODE_MAX_LIGHT,
    MODE_MAX_SHADE,
)

from ..cover_helpers import make_cover_config

pytestmark = pytest.mark.unit

LR_CLASS = "custom_components.adaptive_cover_pro.engine.covers.louvered_roof.AdaptiveLouveredRoofCover"


def _build(
    *,
    sol_elev: float,
    sol_azi: float = 180.0,
    theta_min: float = 0.0,
    theta_max: float = 135.0,
    shade_airflow: bool = True,
    roof_height: float = 3.0,
    protected_height: float = 1.8,
    footprint: float = 3.0,
    axis_azimuth: float = 90.0,
    plane_pitch: float = 0.0,
    blind_spot_on: bool = False,
    **cover_overrides,
) -> AdaptiveLouveredRoofCover:
    """Construct an AdaptiveLouveredRoofCover from flat kwargs."""
    lr = LouveredRoofConfig(
        axis_azimuth=axis_azimuth,
        plane_pitch=plane_pitch,
        roof_height=roof_height,
        protected_height=protected_height,
        footprint_x=footprint,
        footprint_y=footprint,
        slat_chord=21.0,
        slat_thickness=3.0,
        slat_spacing=20.0,
        theta_min=theta_min,
        theta_max=theta_max,
        shade_airflow=shade_airflow,
    )
    return AdaptiveLouveredRoofCover(
        logger=MagicMock(),
        sol_azi=sol_azi,
        sol_elev=sol_elev,
        sun_data=MagicMock(timezone="UTC"),
        config=make_cover_config(blind_spot_on=blind_spot_on, **cover_overrides),
        lr_config=lr,
    )


# ---------------------------------------------------------------------------
# Geometry — reference table (Linz, solar noon: gamma = 0 ⇒ p = elevation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("elev", "exp_p", "exp_delta", "exp_light", "exp_closed", "exp_airflow"),
    [
        (65.0, 65, 51, 48, 11, 86),  # summer solstice
        (42.0, 42, 31, 31, 8, 54),  # equinox
        (18.0, 18, 9, 13, 7, 20),  # winter solstice
    ],
)
def test_reference_table(elev, exp_p, exp_delta, exp_light, exp_closed, exp_airflow):
    """Profile angle, Δ and the three poses match the worked reference table."""
    cover = _build(sol_elev=elev)
    assert round(cover.profile_angle) == exp_p
    assert round(cover.blocking_half_angle) == exp_delta
    # Max-sunlight pose (edge-on θ=p).
    assert cover.max_light_percentage() == pytest.approx(exp_light, abs=1)
    # Shade poses — a large footprint keeps shade mode active at every elevation
    # (otherwise low winter sun is side-lit → max-light), isolating the pose math.
    assert _build(
        sol_elev=elev, shade_airflow=False, footprint=30.0
    ).calculate_percentage() == pytest.approx(exp_closed, abs=1)
    assert _build(
        sol_elev=elev, shade_airflow=True, footprint=30.0
    ).calculate_percentage() == pytest.approx(exp_airflow, abs=1)


def test_profile_angle_rises_toward_axis_end():
    """P → 90° as the sun nears an axis end (|gamma| → 90)."""
    # Axis E-W (90) → facing-perp south (180). Sun at azimuth 270 ⇒ gamma=90.
    cover = _build(sol_elev=30.0, sol_azi=265.0)
    assert cover.profile_angle > 60.0


def test_plane_pitch_offsets_profile_angle():
    """A sloped plane subtracts its pitch from the profile angle."""
    flat = _build(sol_elev=42.0)
    pitched = _build(sol_elev=42.0, plane_pitch=10.0)
    assert pytest.approx(flat.profile_angle - 10.0, abs=0.01) == pitched.profile_angle


# ---------------------------------------------------------------------------
# Mode trigger — occupancy shading
# ---------------------------------------------------------------------------


def test_high_sun_needs_shade():
    """Sun high over the footprint → max-shade (beams come through the roof)."""
    cover = _build(sol_elev=65.0)
    cover.calculate_position()
    assert cover._last_calc_details["mode"] == MODE_MAX_SHADE


def test_low_sun_is_side_lit_max_light():
    """Sun too low (Δr ≥ footprint depth) → max-sunlight (slats useless)."""
    # elev 10°, H-h=1.2 ⇒ Δr ≈ 6.8 m > 3 m footprint depth.
    cover = _build(sol_elev=10.0)
    cover.calculate_position()
    assert cover._last_calc_details["mode"] == MODE_MAX_LIGHT
    assert cover.calculate_percentage() == pytest.approx(
        cover.max_light_percentage(), abs=1
    )


def test_larger_footprint_stays_shadeable_lower():
    """A deeper footprint keeps shade mode at a lower sun than a small one."""
    small = _build(sol_elev=22.0, footprint=2.0)
    large = _build(sol_elev=22.0, footprint=8.0)
    small.calculate_position()
    large.calculate_position()
    assert small._last_calc_details["mode"] == MODE_MAX_LIGHT
    assert large._last_calc_details["mode"] == MODE_MAX_SHADE


def test_airflow_falls_back_to_flat_when_steep_unreachable():
    """High near-side sun: p+Δ exceeds θ_max, so airflow falls back to the flat pose.

    Regression for the "open at noon" bug: clamping the steep pose p+Δ down to
    θ_max left |θ_max − p| < Δ — the gap re-opened and the roof let sun in. The
    engine must instead use the flat pose (p−Δ), which shades.
    """
    cover = _build(
        sol_elev=80.0,
        sol_azi=180.0,
        axis_azimuth=90.0,  # E-W axis → noon sun is near-side
        theta_min=0.0,
        theta_max=135.0,
        shade_airflow=True,
        footprint=30.0,
    )
    cover.calculate_position()
    details = cover._last_calc_details
    assert details["mode"] == MODE_MAX_SHADE
    assert details["far_side"] is False
    p, delta = cover.profile_angle, cover.blocking_half_angle
    assert p + delta > 135.0, "precondition: steep airflow pose must be unreachable"
    # Falls back to the flat pose (p−Δ), a low/closed position — NOT ~100% open.
    assert details["slat_angle_deg"] == pytest.approx(p - delta, abs=0.5)
    assert cover.calculate_percentage() < 30.0


def test_airflow_uses_steep_vent_pose_when_reachable():
    """Moderate near-side sun: the airflow vent pose (p+Δ) is reachable and used."""
    cover = _build(
        sol_elev=42.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        theta_min=0.0,
        theta_max=135.0,
        shade_airflow=True,
        footprint=30.0,
    )
    cover.calculate_position()
    p, delta = cover.profile_angle, cover.blocking_half_angle
    assert p + delta <= 135.0
    assert cover._last_calc_details["slat_angle_deg"] == pytest.approx(p + delta, abs=0.5)


def test_blind_spot_deadzone_forces_max_light():
    """Sun in the configured blind-spot → max-sunlight (natural shade)."""
    cover = _build(sol_elev=65.0)
    with patch.object(
        AdaptiveLouveredRoofCover,
        "is_sun_in_blind_spot",
        new_callable=PropertyMock,
        return_value=True,
    ):
        cover.calculate_position()
        assert cover._last_calc_details["mode"] == MODE_MAX_LIGHT


# ---------------------------------------------------------------------------
# Far-side mirror + travel clamp
# ---------------------------------------------------------------------------


def test_far_side_mirrors_pose():
    """Sun on the far side of the axis (|gamma|>90) mirrors the slat angle."""
    # Axis E-W → gamma = Az-180. Az=30 ⇒ gamma=-150 ⇒ |gamma|>90 (far side).
    cover = _build(sol_elev=40.0, sol_azi=30.0, theta_min=-45.0, theta_max=135.0)
    cover.calculate_position()
    assert cover._last_calc_details["far_side"] is True
    # Mirrored max-light angle is negative → maps below the flat (θ=0 → 25%) point.
    assert cover.max_light_percentage() < 25


def test_position_clamped_to_travel_range():
    """Computed angle is clamped into [theta_min, theta_max] → percentage in 0..100."""
    cover = _build(sol_elev=80.0, theta_min=0.0, theta_max=90.0)
    pct = cover.calculate_percentage()
    assert 0.0 <= pct <= 100.0


def test_theta_mapping_endpoints():
    """θ_min maps to 0 %, θ_max to 100 %."""
    cover = _build(sol_elev=42.0, theta_min=-45.0, theta_max=135.0)
    assert cover._map_to_pct(-45.0) == 0.0
    assert cover._map_to_pct(135.0) == 100.0
    assert cover._map_to_pct(45.0) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Validity — night park vs tracking
# ---------------------------------------------------------------------------


def _daytime_sun_data() -> MagicMock:
    """Mock SunData whose sunset/sunrise bracket 'now' (not in the park window)."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    sd = MagicMock(timezone="UTC")
    sd.sunset.return_value = now + timedelta(hours=8)
    sd.sunrise.return_value = now - timedelta(hours=8)
    return sd


def test_valid_when_sun_up():
    """The cover tracks across all azimuths whenever the sun is above the horizon."""
    for azi in (95.0, 265.0):
        cover = _build(sol_elev=20.0, sol_azi=azi)
        cover.sun_data = _daytime_sun_data()
        assert cover.direct_sun_valid is True


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_policy_registered():
    """The policy auto-registers and drives the tilt axis."""
    assert "cover_louvered_roof" in POLICY_REGISTRY
    policy = get_policy("cover_louvered_roof")
    assert policy.controls_cover is True
    assert [a.name for a in policy.axes] == ["tilt"]
    assert "lr_shade_airflow" in policy.live_option_keys()


def test_policy_build_calc_engine():
    """The policy builds the louvered-roof engine from options."""
    policy = get_policy("cover_louvered_roof")
    engine = policy.build_calc_engine(
        logger=MagicMock(),
        sol_azi=180.0,
        sol_elev=45.0,
        sun_data=MagicMock(timezone="UTC"),
        config=make_cover_config(),
        config_service=MagicMock(),
        options={},
    )
    assert isinstance(engine, AdaptiveLouveredRoofCover)


def test_post_pipeline_winter_summer_remap():
    """Climate winter heating → max-sunlight; summer cooling → fully closed."""
    from custom_components.adaptive_cover_pro.const import ControlMethod
    from custom_components.adaptive_cover_pro.pipeline.types import PipelineResult

    policy = get_policy("cover_louvered_roof")
    cover = _build(sol_elev=65.0)
    kw = {
        "logger": MagicMock(),
        "sol_azi": 180.0,
        "sol_elev": 65.0,
        "sun_data": MagicMock(),
        "config": cover.config,
        "config_service": MagicMock(),
        "options": {},
        "cover": cover,
    }

    winter = PipelineResult(
        position=50, control_method=ControlMethod.WINTER, reason="climate"
    )
    out = policy.post_pipeline_resolve(winter, **kw)
    assert out.position == cover.max_light_percentage()

    summer = PipelineResult(
        position=50, control_method=ControlMethod.SUMMER, reason="climate"
    )
    out = policy.post_pipeline_resolve(summer, **kw)
    assert out.position == cover.closed_percentage()

    # Non-climate decisions pass through unchanged.
    solar = PipelineResult(
        position=42, control_method=ControlMethod.SOLAR, reason="sun"
    )
    assert policy.post_pipeline_resolve(solar, **kw).position == 42


# ---------------------------------------------------------------------------
# Options-service validation — the "Shade Airflow" switch persists an option,
# so its key (and the rest of the louvered-roof options) must validate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False])
def test_validate_accepts_shade_airflow(value):
    """Toggling the Shade Airflow switch validates (regression for the switch error)."""
    from custom_components.adaptive_cover_pro.const import CONF_LR_SHADE_AIRFLOW
    from custom_components.adaptive_cover_pro.services.options_service import (
        validate_options_patch,
    )

    patch = {CONF_LR_SHADE_AIRFLOW: value}
    assert validate_options_patch(patch, {}, "cover_louvered_roof") == patch


def test_validate_accepts_louvered_geometry():
    """Louvered-roof geometry keys are settable via the runtime options path."""
    from custom_components.adaptive_cover_pro.const import (
        CONF_LR_AXIS_AZIMUTH,
        CONF_LR_THETA_MAX,
    )
    from custom_components.adaptive_cover_pro.services.options_service import (
        validate_options_patch,
    )

    patch = {CONF_LR_AXIS_AZIMUTH: 90, CONF_LR_THETA_MAX: 135}
    assert validate_options_patch(patch, {}, "cover_louvered_roof") == patch


def test_every_option_backed_switch_key_is_settable():
    """Guard: every option-backed switch's key must be in FIELD_VALIDATORS.

    An option-backed switch persists its value through ``validate_options_patch``
    → ``_validate_fields`` → ``FIELD_VALIDATORS``; a missing entry makes the
    toggle raise "Option '<key>' is not supported by this service" (the bug this
    fixes). This guard catches the whole class for any future such switch.
    """
    from custom_components.adaptive_cover_pro.services.options_service import (
        FIELD_VALIDATORS,
    )
    from custom_components.adaptive_cover_pro.switch import _SWITCH_SPECS

    missing = [
        spec.option_key
        for spec in _SWITCH_SPECS
        if spec.option_key is not None and spec.option_key not in FIELD_VALIDATORS
    ]
    assert not missing, f"option-backed switch keys missing from FIELD_VALIDATORS: {missing}"
