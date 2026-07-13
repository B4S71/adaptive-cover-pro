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
* **Max-shade** — the **minimal-block ("just barely") pose**: block the beam
  with a small fixed overlap and no more, so airflow is maximised. A beam at
  signed profile angle ``β`` is blocked by any pose ``|θ − β| ≥ Δ_eff``, where
  ``Δ_eff`` (see :meth:`_delta_eff`) is the grazing half-angle inflated so the
  shadow lands a fixed ``_BLOCK_OVERLAP_MARGIN_CM`` onto the next slat. The pose
  depends on which side of an axis end the sun is on:

  * **Tracking side** (``|γ| ≤ 90``): the reachable grazing pose nearest vertical
    (most open). Around solar noon the steep/far side (past vertical) is nearest
    vertical and vents while blocking the high sun; near an axis end the steep
    side runs off travel, so the flat overlap side takes over (the axis-end
    pinch). ``shade_airflow`` off restricts this to the flat side only.
  * **Past-axis wing** (``|γ| > 90``, the morning/evening reopening): the same
    most-open just-barely pose, capped at vertical — ``min(β − Δ_eff, vertical)``.
    The flat grazing edge rises as the sun sets; once it passes vertical, vertical
    is the most-open pose that still blocks (going past would imply the sun from
    below). The near-flat axis-end pinch reopens toward vertical.

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

When the sun crosses an axis end (``|γ| > 90°``) the pose switches from the
tracking-side just-barely rule to the past-axis perpendicular rule, so the slats
come back down from the far-side vent to track the crossed-over beam to vertical
at sunset instead of staying pinned open. The chosen angle is clamped to
``[theta_min, theta_max]`` and mapped to 0–100 % through the (optionally
nonlinear) tilt calibration.

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

# --- Shade safety margin ---------------------------------------------------
# The raw grazing pose ``θ = β ± Δ`` sits *exactly* on the boundary: adjacent
# slat shadows just touch, so the projected overlap equals the gap and any real-
# world deviation (sun-position error, servo tolerance, slat play, the thin-slat
# idealisation) lets the direct beam slip through. Instead we require the shadow
# to fall a fixed distance PAST the next slat's edge — a constant projected
# overlap in centimetres (the user's "1 cm of shadow on the next slat"), tuned so
# the flat pinch at an axis end lands on the measured safe pose (≈13 % at due
# west for the reporting site). A fixed-cm margin (not a fraction) matches the
# physical mental model and stays safe where the gap is largest.
_BLOCK_OVERLAP_MARGIN_CM = 1.9

# Extra safety angle for the past-axis (morning/evening reopening) wing only:
# sit this many degrees FLATTER than the bare grazing edge. There the sun is low
# and oblique, so long shadows magnify a grazing gap into a visible sun-line and
# the reopening needs more than a hair of overlap. A constant angle closes the
# curve uniformly (no blow-up near the axis end) and reaches the vertical cap a
# touch later (less steep). Tuned to the reporting site's evening (≈56 % at 19:00
# vs the grazing 60 %); the due-west pinch (13 %) is on the tracking side and the
# midday far-vent (92 %) is untouched.
_PAST_AXIS_SAFETY_DEG = 5.0

# Below this elevation the single-axis projection is unreliable → drive straight
# to the full-overlap (locked) pose.
_FULL_CLOSE_ELEV_DEG = 2.0

# Vertical slats — perpendicular to a horizontal (sunset) beam, the maximum-open
# pose that still blocks. The pose never travels past this on a past-axis wing
# (past vertical would imply the sun shining from below).
_VERTICAL_ANGLE_DEG = 90.0

# Slat mode labels surfaced in the calc trace / diagnostics.
MODE_MAX_LIGHT = "max_sunlight"
MODE_MAX_SHADE = "max_shade"
MODE_PARK = "park_default"


def _wrap180(deg: float) -> float:
    """Wrap an angle (degrees) into ``(-180, 180]``."""
    return (deg + 180.0) % 360.0 - 180.0


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear interpolate ``x`` over monotonic-increasing ``xs`` → ``ys``.

    Clamps to the end values outside ``[xs[0], xs[-1]]``. ``xs`` must be sorted
    ascending (the tilt calibration guarantees this for both directions).
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


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
    def signed_profile_angle(self) -> float:
        """Signed profile angle ``β`` — like ``p`` but keeps the near/far sign.

        ``β = atan2(sinα, cosα·cosγ) − pitch`` (no ``abs``): ``0…90`` while the
        sun is on the primary side of the plane, ``90…180`` once it has crossed an
        axis end (``|γ| > 90``) and its in-plane projection flips to the other
        side. The shade pose is placed relative to ``β`` so a crossed-over beam is
        met by a pose on the *correct* side (which lands below vertical for a
        single-ended mechanism) rather than by mirroring the folded magnitude.
        """
        a = radians(self.sol_elev)
        g = radians(self.gamma_roof)
        beta = degrees(atan2(sin(a), cos(a) * cos(g)))
        return beta - self.lr_config.plane_pitch

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
        # azimuth (centred rectangle).
        depth = lr.footprint_x * abs(sin(az)) + lr.footprint_y * abs(cos(az))
        # Directional extensions: the beam that comes through the roof lands
        # down-sun (azimuth + 180°). Any protected-area arm reaching that way
        # adds effective depth, so shade stays active while the beam still falls
        # on the terrace. Reach = its length projected onto the down-sun
        # direction; take the deepest (the arms and footprint are a union).
        if lr.shade_extensions:
            shift_az = self.sol_azi + 180.0
            for ext_az, ext_dist in lr.shade_extensions:
                reach = ext_dist * cos(radians(ext_az - shift_az))
                if reach > depth:
                    depth = reach
        return shift < depth

    # ---- pose ↔ percentage (calibrated) ----------------------------------

    def _map_to_pct(self, theta: float) -> float:
        """Map a signed slat angle to 0–100 % tilt.

        Uses the config's :attr:`tilt_calibration` anchor points when present
        (piecewise-linear angle→%, e.g. a nonlinear crank linkage), else the
        plain linear ``theta_min↔0 % … theta_max↔100 %`` map.
        """
        cal = self.lr_config.tilt_calibration
        if cal:
            angles = [p[0] for p in cal]
            pcts = [p[1] for p in cal]
            return max(0.0, min(100.0, _interp(theta, angles, pcts)))
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        if hi == lo:
            return 0.0
        return max(0.0, min(100.0, (theta - lo) / (hi - lo) * 100.0))

    def _pct_to_angle(self, pct: float) -> float:
        """Inverse of :meth:`_map_to_pct`: 0–100 % tilt → signed slat angle."""
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        cal = self.lr_config.tilt_calibration
        if cal:
            angles = [p[0] for p in cal]
            pcts = [p[1] for p in cal]
            return max(lo, min(hi, _interp(pct, pcts, angles)))
        return lo + max(0.0, min(100.0, pct)) / 100.0 * (hi - lo)

    def _max_light_angle(self) -> float:
        """Max-sunlight pose — opening pointed at the sun's height, on its side.

        Fully axis-relative (no hardcoded compass): the rotation-axis azimuth the
        user configures defines the two sides. The slat opening sweeps the plane
        perpendicular to the axis — ``θ = 0`` opens toward the ``axis+90`` side
        ("near"), ``θ = 90`` (vertical) straight up, ``θ = 135`` tips the opening
        over toward the ``axis−90`` side ("far"). Admitting the most light means
        aiming that opening at the sun's apparent height on the side the sun is
        on, keyed on the signed off-axis angle ``γ`` (relative to the configured
        axis):

        * **Near side** (``|γ| ≤ 90`` — sun within the trackable arc between the
          axis ends): opening faces the ``axis+90`` side at the sun's elevation →
          ``θ = elevation`` (the 0–75 % range).
        * **Far side** (``|γ| > 90`` — sun past an axis end): opening faces the
          ``axis−90`` side at the sun's elevation → ``θ = 180 − elevation`` (the
          75–100 % range). A low far-side sun pins near ``θ_max`` — the lowest
          far-side opening the single-ended travel reaches.

        Uses the elevation, NOT the in-plane profile angle: off-axis the profile
        angle balloons toward vertical even for a low sun, which mis-aimed the
        opening. The regime flips at the axis ends (``|γ| = 90``), a deliberate
        step. (For the reporting site, axis 92° → near = the south arc 92–272°,
        far = the NE/NW wings.) Pitch-corrected; clamped to travel.
        """
        elev = self.sol_elev - self.lr_config.plane_pitch
        theta = elev if abs(self.gamma_roof) <= 90.0 else 180.0 - elev
        return max(self.lr_config.theta_min, min(self.lr_config.theta_max, theta))

    def _delta_eff(self) -> float:
        """Grazing half-angle ``Δ`` inflated by the fixed overlap safety margin.

        The bare ``Δ`` grazes: ``R·sin(Δ + φ_t) = S·sin p`` (projected coverage
        equals the gap). Here we require the coverage to exceed the gap by a fixed
        :data:`_BLOCK_OVERLAP_MARGIN_CM` — the shadow lands that many centimetres
        onto the next slat::

            R·sin(Δ_eff + φ_t) = S·sin p + margin_cm

        A fixed-cm margin (vs the old elevation/off-axis fraction) matches the
        physical "1 cm of shadow on the next slat" model and is tuned so the flat
        pinch at an axis end lands on the measured safe pose. Clamped to the
        ``asin`` domain and to ``≥ 0``.
        """
        lr = self.lr_config
        r = hypot(lr.slat_chord, lr.slat_thickness)
        if lr.slat_chord <= 0 or r <= 0:
            return 0.0
        phi_t = degrees(atan2(lr.slat_thickness, lr.slat_chord))
        gap = lr.slat_spacing * sin(radians(self.profile_angle))
        arg = min(0.999999, max(0.0, (gap + _BLOCK_OVERLAP_MARGIN_CM) / r))
        return max(0.0, degrees(asin(arg)) - phi_t)

    def _perpendicular_angle(self) -> float:
        """Slat perpendicular to the in-plane beam: ``θ = 90 − p`` (max block).

        The face-on pose casts the deepest shadow (the maximum-block reference).
        Diagnostic only — surfaced in the calc trace; the shade pose uses the
        most-open *just-barely* rule, not this deepest block, which over-closes.
        """
        return _VERTICAL_ANGLE_DEG - self.profile_angle

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
        """Minimal-block ("just barely") shade pose, tracking the sun's side.

        A beam at signed profile angle ``β`` is blocked by any pose at least the
        margin-enhanced half-angle ``Δ_eff`` (:meth:`_delta_eff`) away from
        edge-on: the **flat** side ``θ = β − Δ_eff`` (toward horizontal/overlap)
        and the **steep** side ``θ = β + Δ_eff`` (past vertical). The pose is
        chosen by which side of an axis end the sun is on:

        * **Tracking side** (``|γ| ≤ 90`` — sun on the trackable side of the
          plane): the most-open *just-barely* blocking pose = whichever reachable
          grazing pose sits closest to vertical (maximum airflow). Around solar
          noon the steep/far side (past vertical) is nearest vertical and gives a
          real vent while blocking the high sun; near an axis end the steep side
          runs past ``θ_max`` (would leak if clamped there), so the flat overlap
          side takes over — the pinch to a near-flat seal. Vertical itself is
          offered when it already blocks with margin.

        * **Past-axis wing** (``|γ| > 90`` — sun beyond an axis end, the
          morning/evening reopening): the slats track *perpendicular* to the sun
          (:meth:`_perpendicular_angle`), never past vertical. This rises from the
          near-flat axis-end pinch to exactly vertical at sunset (horizontal
          beam), the gradual reopening curve — the deepest block, so it never
          leaks the crossed-over beam. Past vertical is refused: it would imply
          the sun shining from below.

        With ``shade_airflow`` off the tracking side uses the flat overlap side
        only (no vent, closed flavor). ``max_pos`` is *not* consulted here — it is
        a position cap applied downstream by ``apply_limits``, not a reason to
        switch shade poses. The downstream sun-tracking min-position floor lifts a
        near-flat seal into a slight vent that still blocks via chord ≥ spacing.
        """
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        if self.sol_elev < _FULL_CLOSE_ELEV_DEG:
            return self._full_close_angle()

        beta = self.signed_profile_angle
        d_eff = self._delta_eff()
        raw = self.blocking_half_angle
        vertical = _VERTICAL_ANGLE_DEG

        # Past-axis wing (morning/evening reopening): the most-open just-barely
        # pose, but never past vertical. The flat/overlap grazing edge
        # ``β − Δ_eff`` is the most-open pose that still blocks the crossed-over
        # beam; as the sun sets it rises past vertical, and there vertical itself
        # is the most-open blocking pose ``≤`` vertical (going past would imply the
        # sun from below). ``min(β − Δ_eff, vertical)`` captures both. Sits an
        # extra ``_PAST_AXIS_SAFETY_DEG`` flatter than the bare grazing edge (low
        # oblique sun magnifies a grazing gap into a visible line): the reopening
        # is a little more closed (≈56 % vs 60 % at 19:00 on the reporting site)
        # and reaches the vertical cap slightly later (less steep).
        if abs(self.gamma_roof) > 90.0:
            theta = min(beta - d_eff - _PAST_AXIS_SAFETY_DEG, vertical)
            return max(lo, min(hi, theta))

        flat = beta - d_eff
        if not self.lr_config.shade_airflow:
            # Closed flavor: flattest just-barely block (overlap side), no vent.
            return max(lo, min(hi, flat))

        # Tracking side, airflow: pick the reachable grazing pose closest to
        # vertical (most open). The steep side is only usable while its *grazing*
        # edge fits the travel range — past that, clamping to θ_max would sit
        # inside the leak band and let the beam through, so fall to the flat side.
        options = [flat]
        if beta + raw <= hi:
            options.append(min(beta + d_eff, hi))
        if abs(vertical - beta) >= d_eff:
            options.append(vertical)
        theta = min(options, key=lambda t: abs(t - vertical))
        return max(lo, min(hi, theta))

    def _is_shading(self) -> bool:
        """Whether the sun is actually reaching the protected area this cycle.

        True only when the sun is in the configured field of view, NOT in a
        blind spot, AND high enough for a through-roof beam to land on the
        footprint at the protected height (the occupancy test). Everything else
        means "no sun on the protected plane" — the max-sunlight / park case.
        """
        return self.in_fov and not self.is_sun_in_blind_spot and self._needs_shade()

    def _fixed_light_angle(self) -> float:
        """Slat angle for the configured fixed no-shade position (``max_light_position``).

        Used when ``max_light_position`` is set and nothing is being shaded:
        instead of the moving max-sunlight curve, hold that fixed tilt %. The % is
        mapped back to the equivalent angle over the (optionally nonlinear) travel
        range.
        """
        lo, hi = self.lr_config.theta_min, self.lr_config.theta_max
        pct = max(0.0, min(100.0, float(self.lr_config.max_light_position)))
        return max(lo, min(hi, self._pct_to_angle(pct)))

    def _target(self) -> tuple[float, str]:
        """Return ``(slat_angle_deg, mode_label)`` for this cycle.

        When the sun is reaching the protected area (in FOV, not in a blind
        spot, high enough for the occupancy test) → the gap-closing max-shade
        pose. Otherwise no shading is needed, and the pose is either:

        * ``max_light_position`` set → a fixed tilt % held instead of the sun
          curve (``MODE_PARK``), or
        * unset (default) → the max-sunlight pose (``_max_light_angle``).
        """
        if self._is_shading():
            return self._shade_angle(), MODE_MAX_SHADE
        if self.lr_config.max_light_position is not None:
            return self._fixed_light_angle(), MODE_PARK
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
            "signed_profile_angle_deg": round(self.signed_profile_angle, 2),
            "blocking_half_angle_deg": round(self.blocking_half_angle, 2),
            "delta_eff_deg": round(self._delta_eff(), 2),
            "perpendicular_deg": round(self._perpendicular_angle(), 2),
            "overlap_margin_cm": _BLOCK_OVERLAP_MARGIN_CM,
            "slat_angle_deg": round(theta, 2),
            "mode": mode,
            "needs_shade": mode == MODE_MAX_SHADE,
            "in_fov": bool(self.in_fov),
            "shade_airflow": bool(self.lr_config.shade_airflow),
            "max_light_position": self.lr_config.max_light_position,
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
