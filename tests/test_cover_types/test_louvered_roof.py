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
    MODE_PARK,
)

from ..cover_helpers import make_cover_config

pytestmark = pytest.mark.unit

# Projected-overlap margin a shade pose must clear where the geometry can
# provide it (the engine's base target block fraction is 0.12).
_MIN_BLOCK_MARGIN = 0.10
# Hard no-leak floor asserted across every daytime angle. At high sun the full-
# overlap pose is capped by the slat chord/spacing ratio (here 21/20 ≈ 5 %
# overlap → ~7–10 % max margin), so the guaranteed floor is lower than the
# mid-range target — but still far above the old 0 % grazing boundary.
_HARD_MIN_BLOCK_MARGIN = 0.05


def _block_margin(cover, theta_deg: float) -> float:
    """Independent projection oracle: fractional slat-overlap minus the gap.

    ``>= 0`` means the direct beam is blocked; the value is how far past the
    grazing boundary the pose sits. Valid for near-side (un-mirrored) poses,
    where ``|θ − p|`` is the beam-relative slat rotation. Mirror cases pass
    ``sol_azi`` on the near side so ``theta`` is not negated.
    """
    from math import atan2, degrees, hypot, radians, sin

    lr = cover.lr_config
    r = hypot(lr.slat_chord, lr.slat_thickness)
    phi_t = degrees(atan2(lr.slat_thickness, lr.slat_chord))
    p = cover.profile_angle
    lhs = r * sin(radians(abs(theta_deg - p) + phi_t))
    rhs = lr.slat_spacing * sin(radians(p))
    return 999.0 if rhs <= 0 else (lhs - rhs) / rhs


def _signed_block_margin(cover, theta_deg: float) -> float:
    """Projection oracle using the SIGNED profile angle ``β``.

    Same fraction-past-grazing as :func:`_block_margin`, but keyed on the signed
    profile angle, so it is valid on BOTH sides of an axis end (``|γ| > 90``) —
    the far-side case the folded ``|p|`` version cannot judge. This is the oracle
    for the no-leak regression across a full day (including the ~270° crossover).
    """
    from math import atan2, degrees, hypot, radians, sin

    lr = cover.lr_config
    r = hypot(lr.slat_chord, lr.slat_thickness)
    phi_t = degrees(atan2(lr.slat_thickness, lr.slat_chord))
    beta = cover.signed_profile_angle
    lhs = r * sin(radians(abs(theta_deg - beta) + phi_t))
    rhs = lr.slat_spacing * sin(radians(abs(beta)))
    return 999.0 if rhs <= 0 else (lhs - rhs) / rhs


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
    park_at_default: bool = False,
    slat_chord: float = 21.0,
    slat_thickness: float = 3.0,
    slat_spacing: float = 20.0,
    tilt_calibration: tuple = (),
    shade_extensions: tuple = (),
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
        slat_chord=slat_chord,
        slat_thickness=slat_thickness,
        slat_spacing=slat_spacing,
        theta_min=theta_min,
        theta_max=theta_max,
        shade_airflow=shade_airflow,
        park_at_default=park_at_default,
        tilt_calibration=tilt_calibration,
        shade_extensions=shade_extensions,
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
    ("elev", "exp_p", "exp_delta", "exp_light"),
    [
        (65.0, 65, 51, 48),  # summer solstice
        (42.0, 42, 31, 31),  # equinox
        (18.0, 18, 9, 13),  # winter solstice
    ],
)
def test_reference_table(elev, exp_p, exp_delta, exp_light):
    """Profile angle, raw Δ and the max-light pose match the worked reference.

    The raw geometry primitives (``p``, ``Δ``, edge-on max-light) are unchanged;
    the two shade poses now carry a safety margin, so instead of the old grazing
    %-values they are asserted to actually BLOCK the beam with margin (below).
    """
    cover = _build(sol_elev=elev)
    assert round(cover.profile_angle) == exp_p
    assert round(cover.blocking_half_angle) == exp_delta
    assert cover.max_light_percentage() == pytest.approx(exp_light, abs=1)
    # Both shade flavors must block the direct beam with the safety margin — a
    # large footprint keeps shade mode active at every elevation (otherwise low
    # winter sun is side-lit → max-light), isolating the pose math.
    for airflow in (False, True):
        c = _build(sol_elev=elev, shade_airflow=airflow, footprint=30.0)
        theta = c.calculate_position()
        assert (
            _block_margin(c, theta) >= _MIN_BLOCK_MARGIN
        ), f"elev={elev} airflow={airflow} θ={theta:.1f} grazes/leaks"


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


def test_shade_extension_keeps_low_evening_sun_shaded():
    """A directional terrace extension keeps shade active for a low sun whose
    shadow lands on the arm — the reopening curve keeps running instead of
    parking. Low west sun (az ~284°) is side-lit for a small footprint; an arm
    extending east (~92°, where its shadow falls) puts it back in shade.
    """
    common = {
        "sol_elev": 17.5,
        "sol_azi": 283.7,
        "axis_azimuth": 92.0,
        "win_azi": 182,
        "fov_left": 90,
        "fov_right": 180,
    }
    base = _build(**common)
    base.calculate_position()
    assert base._last_calc_details["mode"] == MODE_MAX_LIGHT  # side-lit, no arm
    ext = _build(shade_extensions=((92.0, 12.0),), **common)
    ext.calculate_position()
    assert ext._last_calc_details["mode"] == MODE_MAX_SHADE  # arm catches the beam
    # An arm pointing the wrong way (west, away from the shadow) does nothing.
    away = _build(shade_extensions=((272.0, 12.0),), **common)
    away.calculate_position()
    assert away._last_calc_details["mode"] == MODE_MAX_LIGHT


def test_shade_extensions_built_from_options():
    """``lr_shade_ext_*`` slots build (azimuth, distance) arms; 0/blank drops."""
    from custom_components.adaptive_cover_pro.const import (
        CONF_LR_SHADE_EXT_AZIMUTH_1,
        CONF_LR_SHADE_EXT_DISTANCE_1,
        CONF_LR_SHADE_EXT_DISTANCE_2,
    )

    cfg = LouveredRoofConfig.from_options(
        {CONF_LR_SHADE_EXT_AZIMUTH_1: 92, CONF_LR_SHADE_EXT_DISTANCE_1: 8}
    )
    assert cfg.shade_extensions == ((92.0, 8.0),)
    # A zero-distance slot (and a fully blank config) yields no extensions.
    assert (
        LouveredRoofConfig.from_options(
            {CONF_LR_SHADE_EXT_DISTANCE_2: 0}
        ).shade_extensions
        == ()
    )
    assert LouveredRoofConfig.from_options({}).shade_extensions == ()


def test_airflow_drops_to_flat_block_when_steep_unreachable():
    """Very high near-side sun: the steep vent pose runs past the travel end, so
    airflow takes the *flat* blocking pose instead of pinning open.

    With β + Δ beyond θ_max, the reachable blocking pose is β − Δ (below
    vertical). The engine must land there — a real block — not clamp the steep
    pose to θ_max (which would sit inside the leak band |θ − β| < Δ and let the
    beam through). Regression for the "pinned at 100 %/max_pos and leaking" bug.
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
    theta = cover.calculate_position()
    details = cover._last_calc_details
    assert details["mode"] == MODE_MAX_SHADE
    assert details["far_side"] is False
    # Flat side (below the signed profile angle), and it actually blocks.
    assert theta < cover.signed_profile_angle
    assert _signed_block_margin(cover, theta) >= -0.02  # blocks (grazing or better)
    assert cover.calculate_percentage() < 50


def test_closed_flavor_blocks_when_vent_block_unreachable():
    """Same geometry, *closed* flavor: block always wins via the flat overlap.

    Where the airflow flavor opens (above), the closed flavor drives the flat /
    full-overlap pose (θ = 0), which blocks from every direction when
    chord ≥ spacing — a guaranteed shade for users who prioritise blocking.
    """
    cover = _build(
        sol_elev=80.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        theta_min=0.0,
        theta_max=135.0,
        shade_airflow=False,
        footprint=30.0,
    )
    theta = cover.calculate_position()
    assert cover._last_calc_details["mode"] == MODE_MAX_SHADE
    assert cover.calculate_percentage() < 20.0  # flat/overlap, closed end
    assert _block_margin(cover, theta) >= _HARD_MIN_BLOCK_MARGIN


def test_max_position_is_clamped_downstream_not_by_pose_switch():
    """The engine commands the vent pose; ``max_pos`` is a downstream clamp.

    ``max_pos`` is enforced once, centrally, by ``apply_limits`` on the final
    position — it is not a reason for the engine to switch shade poses. So the
    engine still commands the steep vent pose (which blocks with margin); the
    configured max position is applied to the resulting percentage downstream.
    """
    cover = _build(
        sol_elev=62.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        footprint=30.0,
        shade_airflow=True,
        theta_min=0.0,
        theta_max=135.0,
        max_pos=50,
    )
    theta = cover.calculate_position()
    assert cover.calculate_percentage() > 50  # vent pose, un-clamped at engine level
    assert _block_margin(cover, theta) >= _MIN_BLOCK_MARGIN


def test_airflow_uses_steep_vent_pose_when_reachable():
    """Moderate near-side sun: the airflow vent pose is reachable → high & venting.

    The vent (steep) pose sits well above the flat/closed pose, and still blocks
    the beam with the safety margin.
    """
    vent = _build(
        sol_elev=42.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        footprint=30.0,
        shade_airflow=True,
        theta_min=0.0,
        theta_max=135.0,
    )
    flat = _build(
        sol_elev=42.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        footprint=30.0,
        shade_airflow=False,
        theta_min=0.0,
        theta_max=135.0,
    )
    theta_vent = vent.calculate_position()
    vent.calculate_position()
    assert vent.calculate_percentage() > flat.calculate_percentage()  # steeper
    assert vent.calculate_percentage() > 50.0
    assert _block_margin(vent, theta_vent) >= _MIN_BLOCK_MARGIN


# ---------------------------------------------------------------------------
# High-sun steep-pose cushion (the noon "hairlines" fix). Real reporting-site
# geometry: chord 23, spacing 21, thickness 2.8, axis 92°, θ 0–135°.
# ---------------------------------------------------------------------------


def _reporting_site(
    sol_elev: float, *, sol_azi: float = 180.0, theta_max: float = 135.0, **kw
):
    # win_azi/FOV wide enough that the sun stays in-FOV across the afternoon
    # track (the louvered engine tracks all azimuths, but _is_shading gates on
    # in_fov); callers can override via kw.
    kw.setdefault("win_azi", 182)
    kw.setdefault("fov_left", 90)
    kw.setdefault("fov_right", 90)
    return _build(
        sol_elev=sol_elev,
        sol_azi=sol_azi,
        axis_azimuth=92.0,
        slat_chord=23.0,
        slat_spacing=21.0,
        slat_thickness=2.8,
        theta_min=0.0,
        theta_max=theta_max,
        footprint=40.0,  # keep shade mode active at every elevation
        **kw,
    )


# Reporting-site nonlinear tilt calibration (measured): 0%→0°, 75%→90°
# (vertical), 100%→135°. Stored as sorted (angle, pct) anchors.
_SITE_CAL = ((0.0, 0.0), (90.0, 75.0), (135.0, 100.0))


def test_tilt_calibration_maps_measured_points():
    """angle→% uses the piecewise calibration, not a linear θ/θmax."""
    c = _build(sol_elev=45.0, theta_max=135.0, tilt_calibration=_SITE_CAL)
    assert c._map_to_pct(0.0) == pytest.approx(0.0)
    assert c._map_to_pct(60.0) == pytest.approx(50.0)  # segment 1: 1.2°/%
    assert c._map_to_pct(90.0) == pytest.approx(75.0)  # vertical
    assert c._map_to_pct(112.5) == pytest.approx(87.5)  # segment 2: 1.8°/%
    assert c._map_to_pct(135.0) == pytest.approx(100.0)
    # Linear would have put 90° at 66.7 % and 60° at 44.4 % — this is the fix.
    lin = _build(sol_elev=45.0, theta_max=135.0)
    assert lin._map_to_pct(90.0) == pytest.approx(66.67, abs=0.1)


def test_tilt_calibration_inverse_round_trips():
    """%→angle inverts angle→% over the calibration (used by park/default)."""
    c = _build(sol_elev=45.0, theta_max=135.0, tilt_calibration=_SITE_CAL)
    assert c._pct_to_angle(75.0) == pytest.approx(90.0)
    assert c._pct_to_angle(50.0) == pytest.approx(60.0)
    assert c._pct_to_angle(100.0) == pytest.approx(135.0)
    for theta in (0.0, 30.0, 90.0, 110.0, 135.0):
        assert c._pct_to_angle(c._map_to_pct(theta)) == pytest.approx(theta, abs=1e-6)


def test_from_options_builds_vertical_calibration():
    """A ``lr_tilt_vertical_pct`` option anchors the two-segment calibration;
    blank falls back to linear (empty tuple).
    """
    from custom_components.adaptive_cover_pro.const import CONF_LR_TILT_VERTICAL_PCT

    cfg = LouveredRoofConfig.from_options({CONF_LR_TILT_VERTICAL_PCT: 75})
    assert cfg.tilt_calibration == ((0.0, 0.0), (90.0, 75.0), (135.0, 100.0))
    assert LouveredRoofConfig.from_options({}).tilt_calibration == ()


def test_tracking_side_noon_takes_far_side_vent():
    """High near-side sun: the most-open just-barely pose is the *far* side (past
    vertical) — it vents while blocking the high beam.

    The pose is ``β + Δ_eff`` (steep side, above vertical), the reachable grazing
    pose nearest vertical, and it blocks the beam with the fixed overlap margin.
    """
    c = _reporting_site(64.0, shade_airflow=True, tilt_calibration=_SITE_CAL)
    theta = c.calculate_position()
    assert c._last_calc_details["mode"] == MODE_MAX_SHADE
    beta = c.signed_profile_angle
    assert theta == pytest.approx(
        min(beta + c._delta_eff(), c.lr_config.theta_max), abs=0.05
    )
    assert theta > 90.0  # far side, past vertical
    assert c.calculate_percentage() > 75.0  # above the vertical %
    assert _block_margin(c, theta) >= _MIN_BLOCK_MARGIN


def test_closed_flavor_seals_flat_at_high_sun():
    """The closed flavor (airflow off) drives the flat overlap (near 0 %)."""
    c = _reporting_site(64.0, shade_airflow=False)
    theta = c.calculate_position()
    assert c._last_calc_details["mode"] == MODE_MAX_SHADE
    assert c.calculate_percentage() < 20.0
    assert _block_margin(c, theta) >= _HARD_MIN_BLOCK_MARGIN


def test_due_west_pinch_matches_measured_13pct():
    """At due-west (sun straight down the axis, γ = 90°) only the slat overlap
    blocks: the flat pinch lands on the site's measured safe pose (~13 %).

    This is the fixed ``_BLOCK_OVERLAP_MARGIN_CM`` tuned to the user's
    measurement — the anchor the whole margin is calibrated to.
    """
    c = _reporting_site(30.0, sol_azi=272.0, shade_airflow=True, fov_right=180,
                        tilt_calibration=_SITE_CAL)
    theta = c.calculate_position()
    assert c._last_calc_details["mode"] == MODE_MAX_SHADE
    assert c.calculate_percentage() == pytest.approx(13.0, abs=1.5)
    assert _block_margin(c, theta) >= 0.05


def test_off_axis_afternoon_far_side_rises_monotone():
    """Off-axis afternoon holds the far-side vent, rising monotonically to full
    close as the sun nears the axis end — a deep block, no downward dropout step.
    Reproduces the reporting site's real 15:00–16:15 sun track.
    """
    track = [
        (55.8, 231.2), (53.8, 236.1), (51.7, 240.7),
        (49.5, 244.8), (47.2, 248.7), (44.9, 252.4),
    ]
    pcts = []
    for elev, az in track:
        c = _reporting_site(elev, sol_azi=az, shade_airflow=True,
                            tilt_calibration=_SITE_CAL)
        theta = c.calculate_position()
        assert c._last_calc_details["mode"] == MODE_MAX_SHADE
        assert c._last_calc_details["far_side"] is False  # still tracking side
        assert theta > 90.0  # far side, past vertical
        assert _signed_block_margin(c, theta) >= 0.05  # blocks with room to spare
        pcts.append(c.calculate_percentage())
    assert min(pcts) >= 90.0, pcts  # no dropout
    assert all(b >= a - 0.01 for a, b in zip(pcts, pcts[1:])), pcts
    assert pcts[-1] == pytest.approx(99.8, abs=0.5)  # closed vent at the tail


def test_near_axis_tracking_side_pinches_to_flat_overlap():
    """Approaching an axis end on the tracking side (az ~269°, γ ~87°) the far
    vent runs off travel → the flat overlap side takes over: a near-flat seal
    that BLOCKS with margin, not the bare grazing edge (which leaks).
    """
    c = _reporting_site(31.0, sol_azi=269.0, shade_airflow=True,
                        tilt_calibration=_SITE_CAL)
    theta = c.calculate_position()
    assert c._last_calc_details["mode"] == MODE_MAX_SHADE
    beta = c.signed_profile_angle
    raw = c.blocking_half_angle
    assert beta + raw > c.lr_config.theta_max  # far/steep side off travel
    assert theta == pytest.approx(beta - c._delta_eff(), abs=0.05)  # flat + margin
    assert theta < (beta - raw) - 5.0  # well below the bare grazing edge
    assert c.calculate_percentage() < 20.0  # near-flat pinch
    assert _signed_block_margin(c, theta) >= 0.05


def test_evening_perpendicular_rises_to_vertical_never_above():
    """Past due-west the reopening tracks *perpendicular* to the sinking sun: a
    monotone rise toward vertical (75 %) as the sun sets, never above it, always
    blocking. The user's chosen "gradual to sunset" evening curve.
    """
    track = [(27, 273), (22, 278), (17, 284), (12, 289), (8, 294), (4, 300)]
    pcts = []
    for elev, az in track:
        c = _reporting_site(elev, sol_azi=az, shade_airflow=True, fov_right=180,
                            tilt_calibration=_SITE_CAL)
        theta = c.calculate_position()
        assert c._last_calc_details["far_side"] is True  # past-axis wing
        assert theta <= 90.0 + 1e-6  # NEVER past vertical (sun-from-below)
        assert _signed_block_margin(c, theta) >= -0.03  # perpendicular = deepest block
        pcts.append(c.calculate_percentage())
    assert pcts[-1] <= 75.0  # capped at vertical
    assert pcts[-1] > pcts[1] + 20.0  # it genuinely reopens toward vertical
    # Monotone after the near-flat pinch just past the axis end.
    assert all(b >= a - 0.01 for a, b in zip(pcts[1:], pcts[2:])), pcts


def test_shade_never_leaks_across_the_day():
    """No shade pose lets the beam through — on EITHER side of an axis end.

    Regression for two bugs: (a) the terrace-leak (poses used to sit exactly on
    the grazing boundary, 0 % margin), and (b) the far-side "pinned open" bug —
    once the sun crosses the axis end (``|γ| > 90``) the slats must come back down
    and block, not stay near 100 %. Swept near-side AND across the ~270° crossover
    (axis 92, the reporting site's config), both flavors. The oracle keys on the
    signed profile angle, so it is valid on both sides.
    """
    near = [(e, az, 180) for e in (15.0, 25.0, 40.0, 58.0, 65.0) for az in (150.0, 180.0, 210.0)]
    # Far side: window faces west so the crossover sun stays in FOV; elevations
    # roughly match Linz summer afternoon at each azimuth.
    far = [(45.0, 255.0, 270), (40.0, 262.0, 270), (35.0, 268.0, 270),
           (31.0, 272.0, 270), (28.0, 275.0, 270), (24.0, 280.0, 270)]
    for elev, az, win in near + far:
        for airflow in (False, True):
            c = _build(
                sol_elev=elev,
                sol_azi=az,
                axis_azimuth=92.0,
                footprint=40.0,
                shade_airflow=airflow,
                theta_min=0.0,
                theta_max=135.0,
                win_azi=win,
                fov_left=90,
                fov_right=90,
            )
            theta = c.calculate_position()
            if c._last_calc_details["mode"] != MODE_MAX_SHADE:
                continue  # side-lit → max-light is correct, nothing to block
            margin = _signed_block_margin(c, theta)
            assert margin >= -0.03, (
                f"leak: elev={elev} az={az} airflow={airflow} "
                f"β={c.signed_profile_angle:.1f} θ={theta:.1f} margin={margin:.3f}"
            )


def test_out_of_fov_is_max_sunlight():
    """Sun above the horizon but outside the FOV → max-sunlight, not max-shade.

    The user's window/FOV defines when the sun is in front of the terrace. Out
    of FOV the engine must not shade — regression for "shades all day even when
    the sun isn't on the area".
    """
    # make_cover_config default: win_azi=180, fov 45/45 → cone [135°, 225°].
    cover = _build(sol_elev=50.0, sol_azi=100.0, axis_azimuth=90.0, footprint=30.0)
    cover.calculate_position()
    assert cover._last_calc_details["in_fov"] is False
    assert cover._last_calc_details["mode"] == MODE_MAX_LIGHT


def test_in_fov_high_sun_shades():
    """Sun inside the FOV and high → max-shade (the FOV gate passes through)."""
    cover = _build(sol_elev=65.0, sol_azi=180.0, axis_azimuth=90.0, footprint=30.0)
    cover.calculate_position()
    assert cover._last_calc_details["in_fov"] is True
    assert cover._last_calc_details["mode"] == MODE_MAX_SHADE


def test_park_at_default_holds_default_position_when_not_shading():
    """With park_at_default, the not-shading case holds the default position (h_def %)."""
    # Out of FOV (sol_azi 100, win_azi 180) → not shading. h_def=60 → 60%.
    cover = _build(
        sol_elev=45.0, sol_azi=100.0, axis_azimuth=90.0, park_at_default=True, h_def=60
    )
    cover.calculate_position()
    assert cover._last_calc_details["mode"] == MODE_PARK
    assert cover.calculate_percentage() == pytest.approx(60, abs=1)


def test_park_at_default_still_shades_when_sun_hits():
    """park_at_default does not affect the max-shade case (sun in FOV + high)."""
    cover = _build(
        sol_elev=65.0,
        sol_azi=180.0,
        axis_azimuth=90.0,
        footprint=30.0,
        park_at_default=True,
        h_def=60,
    )
    cover.calculate_position()
    assert cover._last_calc_details["mode"] == MODE_MAX_SHADE


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


def test_max_sunlight_tracks_elevation():
    """Max-sunlight slat angle = sun elevation (peak at noon), not the profile angle.

    Off-axis the profile angle p is steeper than the elevation; the open mode must
    follow the elevation so the curve peaks at noon (the user's spec).
    """
    # Off-axis sun (ESE): elevation 40°, but p is much steeper.
    cover = _build(sol_elev=40.0, sol_azi=110.0, axis_azimuth=90.0, footprint=2.0)
    assert cover.profile_angle > 55.0  # p is amplified off-axis
    # max-light tracks the elevation (40°), not p → 40/135 ≈ 30 %.
    assert cover.max_light_percentage() == pytest.approx(
        round((40.0 / 135.0) * 100.0), abs=1
    )


def test_max_sunlight_equals_elevation_at_due_south():
    """At due-south, max-sunlight (elevation) and the profile angle coincide."""
    cover = _build(sol_elev=65.0, sol_azi=180.0, axis_azimuth=90.0)
    assert cover.profile_angle == pytest.approx(65.0, abs=0.5)
    assert cover.max_light_percentage() == pytest.approx(
        round((65.0 / 135.0) * 100.0), abs=1
    )


def test_far_side_shade_comes_down_to_block():
    """A far-side (|gamma|>90) sun drives the slats DOWN to a blocking pose.

    Once the sun crosses the axis end its in-plane projection flips, so the
    signed profile angle β exceeds 90°, the steep vent pose runs past the travel
    end, and the reachable blocking pose (β − Δ) sits well below vertical. The
    slats must come down there and block — the fix for the "pinned open past the
    axis end, sun shines in" report.
    """
    # In FOV (win_azi 30) but far side of the louvre axis (gamma_roof ≈ -150).
    cover = _build(
        sol_elev=60.0,
        sol_azi=30.0,
        axis_azimuth=90.0,
        theta_min=0.0,
        theta_max=135.0,
        footprint=30.0,
        win_azi=30,
    )
    theta = cover.calculate_position()
    assert cover._last_calc_details["far_side"] is True
    assert cover._last_calc_details["signed_profile_angle_deg"] > 90.0
    assert cover._last_calc_details["mode"] == MODE_MAX_SHADE
    # Came down below vertical (not pinned at ~100 %) and actually blocks.
    assert theta < 90.0
    assert _signed_block_margin(cover, theta) >= -0.02


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


@pytest.mark.parametrize(
    ("inside", "outside", "expect_airflow"),
    [
        (30.0, 25.0, True),  # terrace hotter than outside AND outside > 23 → vent
        (24.0, 25.0, False),  # terrace not hotter than outside → closed
        (30.0, 20.0, False),  # outside below 23 (cool evening) → closed, keep warmth
    ],
)
def test_airflow_by_temperature(inside, outside, expect_airflow):
    """lr_airflow_by_temp decides the flavor from the inside/outside temp sensors."""
    from unittest.mock import MagicMock

    hass = MagicMock()

    def _state(entity):
        s = MagicMock()
        s.state = str(inside) if entity == "sensor.terrace" else str(outside)
        return s

    hass.states.get.side_effect = _state
    policy = get_policy("cover_louvered_roof")
    cs = MagicMock()
    cs.hass = hass
    engine = policy.build_calc_engine(
        logger=MagicMock(),
        sol_azi=180.0,
        sol_elev=45.0,
        sun_data=MagicMock(timezone="UTC"),
        config=make_cover_config(),
        config_service=cs,
        options={
            "lr_airflow_by_temp": True,
            "outside_threshold": 23,
            "temp_entity": "sensor.terrace",
            "outside_temp": "sensor.outside",
        },
    )
    assert engine.lr_config.shade_airflow is expect_airflow


def test_louvered_roof_climate_does_not_control_position():
    """The climate handler defers for the louvered roof (climate steers flavor)."""
    from custom_components.adaptive_cover_pro.pipeline.handlers.climate import (
        ClimateHandler,
    )

    assert get_policy("cover_louvered_roof").climate_controls_position is False
    snap = MagicMock()
    snap.policy.climate_controls_position = False
    assert ClimateHandler().evaluate(snap) is None


@pytest.mark.parametrize("switch_on", [True, False])
def test_climate_mode_flavor_comes_from_switch_not_temp(switch_on):
    """With Climate Mode on, the vent flavor is the manual switch — temps ignored.

    Regression: Climate Mode no longer re-reads the temperature sensors for the
    airflow flavor (that secondary read was removed). Even with a "hot" outside
    reading well above the threshold, the flavor follows the ``Shade Airflow``
    switch; the temps only drive the climate strategy's own winter/summer
    position decision elsewhere.
    """
    hass = MagicMock()

    def _state(entity):
        s = MagicMock()
        s.state = "31.0" if entity == "sensor.outside" else "unavailable"
        return s

    hass.states.get.side_effect = _state
    cs = MagicMock()
    cs.hass = hass
    engine = get_policy("cover_louvered_roof").build_calc_engine(
        logger=MagicMock(),
        sol_azi=180.0,
        sol_elev=45.0,
        sun_data=MagicMock(timezone="UTC"),
        config=make_cover_config(),
        config_service=cs,
        options={
            "climate_mode": True,
            "outside_threshold": "20",  # 31 > 20 would have meant "hot" before
            "temp_high": "23",
            "outside_temp": "sensor.outside",
            "temp_entity": "sensor.terrace",
            "lr_shade_airflow": switch_on,
        },
    )
    assert engine.lr_config.shade_airflow is switch_on


@pytest.mark.parametrize(
    ("inside", "outside", "expect_airflow"),
    [
        (28.0, 24.0, True),  # terrace hotter than outside, outside > threshold → vent
        (22.0, 24.0, False),  # terrace cooler than outside → closed
    ],
)
def test_airflow_by_temp_without_climate_mode(inside, outside, expect_airflow):
    """The standalone 'Airflow by temperature' toggle still drives the flavor.

    Only when Climate Mode is OFF: vent when the terrace (inside) is hotter than
    outside AND outside exceeds ``outside_threshold``.
    """
    hass = MagicMock()

    def _state(entity):
        s = MagicMock()
        s.state = str(inside) if entity == "sensor.terrace" else str(outside)
        return s

    hass.states.get.side_effect = _state
    cs = MagicMock()
    cs.hass = hass
    engine = get_policy("cover_louvered_roof").build_calc_engine(
        logger=MagicMock(),
        sol_azi=180.0,
        sol_elev=45.0,
        sun_data=MagicMock(timezone="UTC"),
        config=make_cover_config(),
        config_service=cs,
        options={
            "climate_mode": False,
            "lr_airflow_by_temp": True,
            "outside_threshold": "20",
            "outside_temp": "sensor.outside",
            "temp_entity": "sensor.terrace",
            "lr_shade_airflow": not expect_airflow,  # temp override beats the switch
        },
    )
    assert engine.lr_config.shade_airflow is expect_airflow


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
    """Climate winter heating → follow-sun max-sunlight; summer → active shade."""
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

    # Summer → the roof's active max-shade / airflow track (block sun + vent),
    # NOT fully closed. High near-side sun → a steep vent pose, well above closed.
    summer = PipelineResult(
        position=50, control_method=ControlMethod.SUMMER, reason="climate"
    )
    out = policy.post_pipeline_resolve(summer, **kw)
    assert out.position == int(round(cover.calculate_percentage()))
    assert out.position > cover.closed_percentage()

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
    assert (
        not missing
    ), f"option-backed switch keys missing from FIELD_VALIDATORS: {missing}"
