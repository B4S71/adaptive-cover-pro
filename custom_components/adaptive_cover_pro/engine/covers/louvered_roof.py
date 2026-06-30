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
  ``θ = p + Δ`` (airflow flavor, keeps a vent gap) or ``θ = p − Δ`` (closed
  flavor, flat / no gap).

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

When the sun is on the far side of the axis (``|γ| > 90°``) the slats are
mirrored (``θ → −θ``) onto the other lean. Travel is asymmetric bi-directional:
the chosen angle is clamped to ``[theta_min, theta_max]`` and mapped linearly to
0–100 %. Single-ended or short-side mechanisms just clamp.

Full model + worked reference: ``codebase-analysis-docs/LOUVERED_ROOF_DESIGN.md``.
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

# Slat mode labels surfaced in the calc trace / diagnostics.
MODE_MAX_LIGHT = "max_sunlight"
MODE_MAX_SHADE = "max_shade"


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
        """Mirror the pose onto the other lean when the sun is on the far side."""
        if abs(self.gamma_roof) > 90.0:
            return -theta
        return theta

    def _max_light_angle(self) -> float:
        """Edge-on pose ``θ = p`` (oriented), clamped to travel."""
        theta = self._oriented(self.profile_angle)
        return max(self.lr_config.theta_min, min(self.lr_config.theta_max, theta))

    def _shade_angle(self) -> float:
        """Gap-closing shade pose, oriented and clamped.

        Two poses close the inter-slat gap against the beam: the **flat** side
        ``θ = p − Δ`` (toward horizontal/closed) and the **steep** side
        ``θ = p + Δ`` (keeps a vertical vent gap — the airflow flavor).

        The steep/airflow pose is used only when it lands on the closing side
        *within travel*. Past ``θ_max`` the louver re-opens to the sky: simply
        clamping ``p + Δ`` down to ``θ_max`` leaves ``|θ_max − p| < Δ``, so the
        direct beam is no longer blocked — at high sun that turned "shade with
        airflow" into a wide-open roof. When the steep pose is unreachable we
        fall back to the flat pose, which always shades. Matches the design
        spec: the +Δ pose is used "when it stays ≤ θ_max".
        """
        p = self.profile_angle
        delta = self.blocking_half_angle
        lo = self.lr_config.theta_min
        hi = self.lr_config.theta_max
        flat = self._oriented(p - delta)
        steep = self._oriented(p + delta)
        if self.lr_config.shade_airflow and lo <= steep <= hi:
            theta = steep
        else:
            theta = flat
        return max(lo, min(hi, theta))

    def _target(self) -> tuple[float, str]:
        """Return ``(slat_angle_deg, mode_label)`` for this cycle.

        Max-sunlight (edge-on) whenever the sun is not actually reaching the
        protected area, in priority order:

        1. Outside the configured field of view — the user's window/FOV defines
           when the sun is in front of the terrace. Out of FOV = no shading
           needed, so hold the edge-on pose (the sun still tracks for the next
           in-FOV moment) instead of pointlessly closing.
        2. Inside a blind spot (e.g. shaded by the house) — same idea.
        3. Sun too low for a through-roof beam to land on the footprint
           (occupancy test).

        Otherwise the gap-closing max-shade pose. Honouring the FOV/blind-spot
        here makes the louvered roof obey the same "sun in front of window"
        gate as every other cover type, rather than shading the whole day.
        """
        if not self.in_fov or self.is_sun_in_blind_spot:
            return self._max_light_angle(), MODE_MAX_LIGHT
        if not self._needs_shade():
            return self._max_light_angle(), MODE_MAX_LIGHT
        return self._shade_angle(), MODE_MAX_SHADE

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
            "slat_angle_deg": round(theta, 2),
            "mode": mode,
            "needs_shade": mode == MODE_MAX_SHADE,
            "in_fov": bool(self.in_fov),
            "shade_airflow": bool(self.lr_config.shade_airflow),
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
