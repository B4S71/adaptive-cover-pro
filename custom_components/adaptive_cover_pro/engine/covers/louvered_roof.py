"""Louvered roof / bioclimatic pergola cover calculation.

Tiltable lamellas lying in a (near-)horizontal overhead plane, rotating about a
single horizontal axis. Unlike the venetian (tilted) engine — a slat pack in a
vertical plane parallel to a window, where ``higher sun ⇒ more closed`` — an
overhead louver tracks only ONE sun component (the projection into the plane
perpendicular to the rotation axis) and has a *max-light* pose (edge-on) with
shade poses on either side of it.

The control objective is **occupancy shading**, not slat-edge tracking: keep a
protected plane lifted ``h`` off the ground (e.g. 1.80 m) over the pergola
footprint in shade. Each cycle the engine decides between two modes:

* **Max-sunlight** — edge-on pose ``θ = p`` (only the slat thickness shades).
* **Max-shade** — slats rotated to close the gap against the beam:
  ``θ = p + Δ_eff`` (airflow flavor, keeps a vent gap) or ``θ = p − Δ_eff``
  (closed flavor, flat / no gap). ``Δ_eff`` is the blocking half-angle with an
  **angle-dependent safety margin** baked in (see ``_effective_block_angle``):
  the raw ``Δ`` grazes the boundary, so a margin — larger toward the horizon and
  toward an axis end — over-closes the slats so a real beam is blocked with room
  to spare rather than skimming through. When the geometry can't open that margin
  (near-axis sun), the flavors diverge: the *closed* flavor locks the flat
  overlap (``θ = 0``), while the *airflow* flavor keeps the steep vent pose but
  degrades to the raw grazing ``Δ`` — staying steep (shading + venting) rather
  than flipping edge-on to the sun or slamming shut off-axis.

Mode selection (per cycle):

1. Sun below the elevation gate → the cover is not ``direct_sun_valid`` so the
   pipeline parks it at the default position (night handling — done upstream).
2. Sun in the configured blind-spot (deadzone) → **max-sunlight** (an external
   object such as a house already shades the area).
3. Otherwise compare the horizontal shadow shift from the roof (``H``) down to
   the protected plane (``h``) against the footprint depth along the sun's
   azimuth: ``Δr = (H−h)/tanα`` vs ``D = Lx·|sinAz| + Ly·|cosAz|``.
   ``Δr ≥ D`` (sun too low, area side-lit, slats useless) → **max-sunlight**;
   ``Δr < D`` (beams come through the roof onto the protected area) →
   **max-shade**.

When the sun is on the far side of the axis (``|γ| > 90°``) and the mechanism is
bi-directional (``theta_min < 0``), the slats are mirrored (``θ → −θ``) onto the
other lean. A single-ended mechanism (``theta_min ≥ 0``, the default) can't lean
the other way, so it keeps the same-side pose. Travel is asymmetric
bi-directional: the chosen angle is clamped to ``[theta_min, theta_max]`` and
mapped linearly to 0–100 %.

Full model + worked reference: ``docs/LOUVERED_ROOF_DESIGN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, hypot, radians, sin, tan

from ...config_types import LouveredRoofConfig
from ...const import (
    TRACE_KEY_GAMMA_DEG,
    TRACE_KEY_POSITION_PCT,
    TRACE_KEY_SOL_ELEV_DEG,
)
from .base import AdaptiveGeneralCover

# Below this elevation a sun ray cannot reach the protected plane through the
# slats (it grazes in from the open side); treat as side-lit → max-sunlight.
_MIN_TRACK_ELEVATION_DEG = 1.0

# --- Enhanced geometric accuracy: shade safety margins ---------------------
# The raw shade pose θ = p ± Δ sits *exactly* on the grazing boundary: adjacent
# slat shadows just touch, so the projected overlap equals the gap and any
# real-world deviation (sun-position error, servo tolerance, slat play, the
# thin-slat idealisation) lets the direct beam slip through. Instead we over-
# close by a target *block fraction* baked into Δ, so the projected overlap
# exceeds the gap by that fraction. The fraction grows where the single-axis
# projection is least reliable — low sun elevation and high off-axis angle —
# mirroring the vertical cover's enhanced-accuracy margins (see the wiki page
# "Enhanced Geometric Accuracy").
_BLOCK_MARGIN_BASE = 0.12  # always-on projected-overlap margin (12 %)
_BLOCK_MARGIN_LOW_ELEV_KNEE_DEG = 15.0  # below this elevation, ramp extra margin
_BLOCK_MARGIN_LOW_ELEV = 0.25  # up to +25 % toward the horizon
_BLOCK_MARGIN_GAMMA_KNEE_DEG = 45.0  # beyond this off-axis angle, ramp extra
_BLOCK_MARGIN_GAMMA_SPAN_DEG = 45.0  # knee … 90° (axis end)
_BLOCK_MARGIN_GAMMA = 0.20  # up to +20 % near the axis end
# Below this elevation (but still above the tracking gate) the projection is
# unreliable → drive straight to the full-overlap (locked) pose.
_FULL_CLOSE_ELEV_DEG = 2.0

# Slat mode labels surfaced in the calc trace / diagnostics.
MODE_MAX_LIGHT = "max_sunlight"
MODE_MAX_SHADE = "max_shade"
MODE_PARK = "park_default"


def _wrap180(deg: float) -> float:
    """Wrap an angle (degrees) into ``(-180, 180]``."""
    return (deg + 180.0) % 360.0 - 180.0


@dataclass
class AdaptiveLouveredRoofCover(AdaptiveGeneralCover):
    """Calculate the slat angle (and tilt %) for a louvered pergola roof."""

    lr_config: LouveredRoofConfig = None  # type: ignore[assignment]

    # ---- validity ---------------------------------------------------------

    @property
    def direct_sun_valid(self) -> bool:
        """Track the sun across all azimuths whenever it is up.

        An overhead louver has no window-azimuth FOV: it can act on the sun from
        any direction. So validity reduces to "sun above the elevation gate and
        not in the sunset/park window". The blind-spot is deliberately NOT
        excluded here — it is handled inside :meth:`calculate_position` as a
        max-sunlight pose (deadzone), not as a park. When the sun drops below the
        elevation gate the cover becomes invalid and the pipeline parks it at the
        default position (night handling).
        """
        return self.valid_elevation and not self.sunset_valid

    # ---- geometry ---------------------------------------------------------

    @property
    def gamma_roof(self) -> float:
        """Sun azimuth relative to the plane perpendicular to the rotation axis.

        ``0`` when the sun lies in the trackable vertical plane on the primary
        side; ``±90`` toward the axis ends. For an East-West axis (azimuth 90)
        this is ``sol_azi − 180`` — the issue's ``g = Az − 180`` measured from
        south.
        """
        return _wrap180(self.sol_azi - (self.lr_config.axis_azimuth + 90.0))

    @property
    def profile_angle(self) -> float:
        """Profile angle ``p`` — sun projected into the perpendicular plane.

        ``p = atan2(sinα, |cosα·cosγ|) − β`` in degrees: equals the elevation at
        γ=0 and rises toward 90° as the sun nears an axis end. ``β`` (plane
        pitch) rotates the reference for a sloped roof.
        """
        a = radians(self.sol_elev)
        g = radians(self.gamma_roof)
        p = degrees(atan2(sin(a), abs(cos(a) * cos(g))))
        return p - self.lr_config.plane_pitch

    @property
    def blocking_half_angle(self) -> float:
        """Thickness-aware blocking half-angle ``Δ`` (degrees, clamped ≥ 0).

        The direct beam is blocked while ``|θ − p| ≥ Δ``. Derived from chord
        ``L``, thickness ``t`` and spacing ``S``: ``R = √(L²+t²)``,
        ``φ_t = atan(t/L)``, ``Δ = asin(min(1, S·sin p / R)) − φ_t``. A negative
        result (slats too sparse to ever close the gap) clamps to 0 so the shade
        pose collapses to edge-on.
        """
        lr = self.lr_config
        chord = lr.slat_chord
        thickness = lr.slat_thickness
        spacing = lr.slat_spacing
        if chord <= 0:
            return 0.0
        r = hypot(chord, thickness)
        phi_t = degrees(atan2(thickness, chord))
        arg = min(1.0, max(0.0, spacing * sin(radians(self.profile_angle)) / r))
        delta = degrees(asin(arg)) - phi_t
        return max(0.0, delta)

    def _needs_shade(self) -> bool:
        """Whether a direct beam reaches the protected footprint through the roof.

        ``True`` (→ max-shade) when the horizontal shadow shift from the roof
        plane down to the protected plane is smaller than the footprint depth
        along the sun's azimuth; ``False`` (→ max-sunlight) when the sun is too
        low and the area is side-lit instead.
        """
        if self.sol_elev <= _MIN_TRACK_ELEVATION_DEG:
            return False
        lr = self.lr_config
        drop = lr.roof_height - lr.protected_height
        if drop <= 0:
            return True  # protected plane at/above the slats — always through-roof
        shift = drop / tan(radians(self.sol_elev))
        az = radians(self.sol_azi)
        # Footprint depth measured along the horizontal projection of the sun
        # azimuth. TODO: extend to per-side (asymmetric) extents instead of a
        # centered rectangle — see LOUVERED_ROOF_DESIGN.md §7 A1.
        depth = lr.footprint_x * abs(sin(az)) + lr.footprint_y * abs(cos(az))
        return shift < depth

    # ---- pose → percentage -----------------------------------------------

    def _map_to_pct(self, theta: float) -> float:
        """Map a signed slat angle to 0–100 % over the configured travel range."""
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        if hi == lo:
            return 0.0
        pct = (theta - lo) / (hi - lo) * 100.0
        return max(0.0, min(100.0, pct))

    def _oriented(self, theta: float) -> float:
        """Mirror the pose onto the other lean when the sun is on the far side.

        Only bi-directional mechanisms (``theta_min < 0`` — slats can tilt past
        flat both ways) can actually lean the other way; there a far-side beam
        (``|γ| > 90``) is met by the mirrored pose ``θ → −θ``. A single-ended
        mechanism (``theta_min ≥ 0``, the default) cannot mirror: negating would
        just clamp every far-side pose to the flat/closed end and collapse the
        curve every morning and evening. There we keep the same-side pose — up to
        vertical the slats present the same geometry to a beam from either side.
        """
        if self.lr_config.theta_min < 0.0 and abs(self.gamma_roof) > 90.0:
            return -theta
        return theta

    def _max_light_angle(self) -> float:
        """Max-sunlight pose — slat angle tracks the sun's **elevation**.

        The open mode aligns the slats with the sun's apparent height, giving the
        intuitive peak-at-noon curve. This deliberately uses the raw elevation
        (minus the roof-plane pitch), NOT the in-plane profile angle ``p``: ``p``
        is required to *shade* (it is the angle at which a single-axis slat
        intercepts the beam), but off-axis it is steeper than the elevation and
        would make the open mode peak mid-morning/afternoon and dip at noon. For
        max-sunlight — where nothing is being blocked — the elevation is what the
        user expects, and it equals ``p`` at due-south. No far-side mirror: the
        elevation is azimuth-independent.
        """
        theta = self.sol_elev - self.lr_config.plane_pitch
        return max(self.lr_config.theta_min, min(self.lr_config.theta_max, theta))

    def _off_axis_severity(self) -> float:
        """``|γ|`` folded into ``[0, 90]``.

        ``0`` in the perpendicular (trackable) plane; ``90`` toward an axis end,
        where the single-axis projection degenerates (``p → 90``). The far side
        (``|γ| > 90``) mirrors back, so severity uses ``180 − |γ|`` there.
        """
        g = abs(self.gamma_roof)
        return g if g <= 90.0 else 180.0 - g

    def _target_block_fraction(self) -> float:
        """Fractional slat-overlap margin to hold past the grazing boundary.

        Larger where the projection is least reliable: toward the horizon (low
        elevation) and toward an axis end (high off-axis angle). Smoothstep on
        the off-axis ramp so the added margin is C¹ (no kink at the knee).
        """
        f = _BLOCK_MARGIN_BASE
        elev = self.sol_elev
        if elev < _BLOCK_MARGIN_LOW_ELEV_KNEE_DEG:
            t = (
                _BLOCK_MARGIN_LOW_ELEV_KNEE_DEG - elev
            ) / _BLOCK_MARGIN_LOW_ELEV_KNEE_DEG
            f += _BLOCK_MARGIN_LOW_ELEV * t
        sev = self._off_axis_severity()
        if sev > _BLOCK_MARGIN_GAMMA_KNEE_DEG:
            t = min(
                1.0, (sev - _BLOCK_MARGIN_GAMMA_KNEE_DEG) / _BLOCK_MARGIN_GAMMA_SPAN_DEG
            )
            f += _BLOCK_MARGIN_GAMMA * (t * t * (3.0 - 2.0 * t))
        return f

    def _effective_block_angle(self) -> float | None:
        """Blocking half-angle with the safety margin baked in.

        The raw ``Δ = asin(S·sin p / R) − φ_t`` grazes (``sin(Δ+φ_t) = S·sin p/R``
        — projected overlap *equals* the gap). Here we require the overlap to
        exceed the gap by ``f = _target_block_fraction()``::

            sin(Δ_eff + φ_t) = (S·sin p / R)·(1 + f)

        so the achieved projected-overlap margin is exactly ``f``. Returns
        ``None`` when the slats physically cannot close the gap *with a vent* at
        this profile angle — either the right-hand side reaches 1 (sun toward an
        axis end, ``p → 90``) or the resulting half-angle is ``≤ 0`` (sun too
        shallow / slats too sparse). Both signal the caller to fall back (the
        closed flavor locks the flat/overlapping pose, which blocks every angle
        when chord ≥ spacing; the airflow flavor stays open).

        Unlike :attr:`blocking_half_angle`, which clamps a negative raw ``Δ`` to
        ``0`` (edge-on), a *negative effective* half-angle must not silently
        become a small positive one: ``p + Δ_eff`` would then sit *below* the
        edge-on pose, i.e. the "shade" pose would open wider than max-sunlight.
        """
        lr = self.lr_config
        r = hypot(lr.slat_chord, lr.slat_thickness)
        if lr.slat_chord <= 0 or r <= 0:
            return None
        phi_t = degrees(atan2(lr.slat_thickness, lr.slat_chord))
        sin_gap = max(0.0, lr.slat_spacing * sin(radians(self.profile_angle)) / r)
        required = sin_gap * (1.0 + self._target_block_fraction())
        if required >= 1.0:
            return None
        delta = degrees(asin(required)) - phi_t
        return delta if delta > 0.0 else None

    def _full_close_angle(self) -> float:
        """Flat/overlapping (locked) max-shade pose: ``θ = 0`` clamped to travel.

        Slats horizontal; when the chord ≥ spacing their edges overlap, so this
        pose blocks the beam from every direction — the safe fallback whenever
        the vent (airflow) pose cannot block with margin, or the geometry cannot
        open a margin at all (very low sun / near an axis end).
        """
        lo, hi = self.lr_config.theta_min, self.lr_config.theta_max
        return max(lo, min(hi, 0.0))

    def _shade_angle(self) -> float:
        """Gap-closing shade pose with a safety margin, oriented and clamped.

        Two poses close the inter-slat gap against the beam with the configured
        overlap margin: the **flat** side ``θ = p − Δ_eff`` (toward
        horizontal/overlap — the *closed* flavor) and the **steep** side
        ``θ = p + Δ_eff`` (keeps a vertical vent gap — the *airflow* flavor). The
        pose is clamped to the travel range; ``max_pos`` is not consulted here —
        it is a *position* cap applied downstream by ``apply_limits``, not a
        reason to switch shade poses.

        **Fallback (margin can't be reached).** When ``Δ_eff`` is ``None`` — the
        sun is toward an axis end (``p → 90``) or below the full-close gate — the
        slats can't hold a vent gap that blocks *with the safety margin*. The two
        flavors then diverge by intent:

        * *airflow* → **degrade the margin, keep the vent**. Fall back to the raw
          grazing half-angle (:attr:`blocking_half_angle`) on the same steep vent
          side, so the slats stay steep — shading the trackable beam component
          and venting — instead of flipping edge-on to the sun (which would leave
          the occupant staring straight at it) or slamming closed. At very
          shallow sun the raw half-angle is ``0``, so the pose relaxes smoothly
          toward edge-on where a single-axis louver genuinely can't shade.
        * *closed* → **block wins**: the flat/overlapping pose (``θ = 0``), which
          blocks from every direction when chord ≥ spacing.
        """
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        p = self.profile_angle
        below_gate = self.sol_elev < _FULL_CLOSE_ELEV_DEG
        delta = None if below_gate else self._effective_block_angle()

        if self.lr_config.shade_airflow:
            step = (
                delta
                if delta is not None
                else (0.0 if below_gate else self.blocking_half_angle)
            )
            theta = self._oriented(p + step)
        elif delta is None:
            return self._full_close_angle()
        else:
            theta = self._oriented(p - delta)
        return max(lo, min(hi, theta))

    def _is_shading(self) -> bool:
        """Whether the sun is actually reaching the protected area this cycle.

        True only when the sun is in the configured field of view, NOT in a
        blind spot, AND high enough for a through-roof beam to land on the
        footprint at the protected height (the occupancy test). Everything else
        means "no sun on the protected plane" — the max-sunlight / park case.
        """
        return self.in_fov and not self.is_sun_in_blind_spot and self._needs_shade()

    def _park_angle(self) -> float:
        """Slat angle that maps to the configured default position (``h_def`` %).

        Used when ``park_at_default`` is on and nothing is being shaded: instead
        of the moving max-sunlight curve, hold a fixed position equal to the
        cover's default. ``h_def`` is a tilt-position %, so it is mapped back to
        the equivalent angle over the travel range.
        """
        lo, hi = self.lr_config.theta_min, self.lr_config.theta_max
        pct = max(0.0, min(100.0, float(self.h_def)))
        theta = lo + pct / 100.0 * (hi - lo)
        return max(lo, min(hi, theta))

    def _target(self) -> tuple[float, str]:
        """Return ``(slat_angle_deg, mode_label)`` for this cycle.

        When the sun is reaching the protected area (in FOV, not in a blind
        spot, high enough for the occupancy test) → the gap-closing max-shade
        pose. Otherwise no shading is needed, and the pose is either:

        * ``park_at_default`` on → a fixed position equal to the cover's default
          (``h_def`` %), or
        * off (default) → the max-sunlight pose tracking the sun's elevation.
        """
        if self._is_shading():
            return self._shade_angle(), MODE_MAX_SHADE
        if self.lr_config.park_at_default:
            return self._park_angle(), MODE_PARK
        return self._max_light_angle(), MODE_MAX_LIGHT

    # ---- public API used by the pipeline / climate path ------------------

    def calculate_position(self) -> float:
        """Return the commanded slat angle (degrees) and record the calc trace."""
        theta, mode = self._target()
        self._last_calc_details = {
            TRACE_KEY_SOL_ELEV_DEG: float(self.sol_elev),
            TRACE_KEY_GAMMA_DEG: float(self.gamma_roof),
            TRACE_KEY_POSITION_PCT: round(self._map_to_pct(theta), 1),
            "profile_angle_deg": round(self.profile_angle, 2),
            "blocking_half_angle_deg": round(self.blocking_half_angle, 2),
            "block_margin_fraction": round(self._target_block_fraction(), 3),
            "slat_angle_deg": round(theta, 2),
            "mode": mode,
            "needs_shade": mode == MODE_MAX_SHADE,
            "in_fov": bool(self.in_fov),
            "shade_airflow": bool(self.lr_config.shade_airflow),
            "park_at_default": bool(self.lr_config.park_at_default),
            "far_side": abs(self.gamma_roof) > 90.0,
        }
        return theta

    def calculate_percentage(self) -> float:
        """Convert the commanded slat angle to a tilt percentage (0–100)."""
        return self._map_to_pct(self.calculate_position())

    def max_light_percentage(self) -> int:
        """Tilt % for the edge-on max-sunlight pose (climate winter heating)."""
        return int(round(self._map_to_pct(self._max_light_angle())))

    def closed_percentage(self) -> int:
        """Tilt % for the fully-closed (θ=0, overlapping) pose (summer cooling)."""
        theta = max(self.lr_config.theta_min, min(self.lr_config.theta_max, 0.0))
        return int(round(self._map_to_pct(theta)))
