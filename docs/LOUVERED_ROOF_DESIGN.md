# Design: Louvered Roof cover type (`cover_louvered_roof`)

A new ACP cover type for **bioclimatic / louvered pergolas** — tiltable lamellas
in a (near-)horizontal overhead plane, rotating about one horizontal axis. Unlike
the Venetian (Tilted) type, which models a slat pack hanging in a vertical plane
parallel to a window, this type lays the slats overhead and **decides the slat
mode from whether direct sun reaches the occupied area under the roof**.

---

## 1. Control objective (the key departure from the issue)

Keep a **protected plane** under the pergola in shade. The slat mode is chosen by
geometry each cycle, not by tracking the slat edge:

- Roof slats sit at height **H** above the ground.
- Protected plane at height **h** (e.g. 1.80 m) over the **pergola footprint**
  (a centered rectangle in v1).
- Two slat modes:
  - **Max-sunlight** — edge-on pose (θ = p): only slat thickness shades; lets the
    most light/sky through.
  - **Max-shade** — slats rotated to close the gap against the beam.
- The mode is selected automatically (see §4).

Within max-shade there is a **flavor**, exposed as a runtime **switch** entity
(hand toggle), default *airflow*:
- *airflow* → steeper pose θ = p + Δ (keeps a vertical vent gap),
- *closed* → flatter pose θ = p − Δ (no gap, watertight-ish).

Night, rain, overrides, glare, the card, etc. all reuse existing ACP machinery.

---

## 2. Coordinate frame & sun vector

Right-handed frame: **x = East, y = North, z = up**; origin at the centre of the
footprint on the ground.

Sun azimuth `Az` (from North, clockwise), elevation `α`. Beam **travel** direction
(downward, away from the sun):

```
d = ( −cosα·sinAz , −cosα·cosAz , −sinα )
```

Rotation axis azimuth `A` (E-W ⇒ A = 90). The **trackable plane** is the vertical
plane perpendicular to the axis; the controllable sun component is the projection
into that plane. Define the horizontal **facing** direction `f = A − 90` and the
sun's in-plane offset:

```
γ = wrap180( Az − 180 − (A − 90) )      # 0 at solar-noon-equivalent, ±90 toward axis ends
```

For an E-W axis (A = 90): `γ = wrap180(Az − 180)` = azimuth measured from South,
matching the issue's `g = Az − 180`.

---

## 3. Slat geometry & poses

Slat chord `L`, thickness `t`, axis spacing `S`. Plane pitch `β` (0 = flat).

```
R    = √(L² + t²)
φ_t  = arctan(t / L)
```

**Profile angle** (sun projected into the plane perpendicular to the axis,
measured against the plane normal; `β` rotates the reference):

```
p_flat = arctan( tanα / |cosγ| )          # issue's formula, p∈[0,90]; p→90 as |γ|→90
p      = p_flat − β                        # pitched-plane correction
```

**Blocking half-angle** (thickness-aware; direct beam blocked while |θ − p| ≥ Δ):

```
Δ = arcsin( min(1, S·sin(p) / R) ) − φ_t
```

`Δ` is the *grazing* boundary — the projected slat overlap exactly equals the
gap, so a pose at `p ± Δ` leaves **zero safety margin** and any real-world
deviation (sun-position error, servo tolerance, slat play, the thin-slat
idealisation) lets the beam skim through. **Enhanced geometric accuracy** bakes a
target *block fraction* `f` into an effective half-angle so the overlap exceeds
the gap by `f`:

```
sin(Δ_eff + φ_t) = ( S·sin(p) / R )·(1 + f)          # achieved overlap margin = f
```

`f` grows where the single-axis projection is least reliable — low elevation and
high off-axis angle |γ| (mirroring the vertical cover's enhanced-accuracy
margins): `f = 0.12` base, up to `+0.25` toward the horizon (< 15°) and `+0.20`
(smoothstep) toward an axis end (|γ| > 45°). `Δ_eff` is `None` when the slats
physically can't hold a vent gap *and* block at that angle — either the RHS
reaches 1 (`p → 90`, sun toward an axis end) or the resulting half-angle is `≤ 0`
(sun too shallow). The two flavors then diverge (see fallback below).

**Poses** (θ = slat angle from horizontal; θ=0 flat/overlapping/closed):

| Pose | θ |
| --- | --- |
| Max-sunlight (edge-on) | `θ = p` |
| Max-shade, *closed* flavor | `θ = p − Δ_eff` |
| Max-shade, *airflow* flavor | `θ = p + Δ_eff` (keeps a vertical vent gap) |

**Fallback when `Δ_eff` is `None`** (single-axis louver can't vent-and-block):

- *closed* flavor → **block wins**: the flat overlap `θ = 0` (blocks every
  direction when chord ≥ spacing — the overlap "lock").
- *airflow* flavor → **degrade the margin, keep the vent**: stay on the steep
  vent side but fall back from `Δ_eff` to the raw grazing `Δ`, so the slats stay
  steep (shading the trackable beam component + venting) instead of flipping
  edge-on to the sun (glare) or slamming closed. At shallow sun the raw `Δ` is 0
  and the pose relaxes smoothly toward edge-on, where a single-axis louver
  genuinely can't shade. A single-axis louver can only fully (margin-)block near
  the perpendicular plane; off-plane it grazes at the geometric limit — a N-S
  axis tracks E/W sun far better. Users who want a guaranteed *margin* block use
  the *closed* flavor.

**Side / mirror.** When the sun is on the far side of the axis (`|γ| > 90°`) and
the mechanism is **bi-directional** (`θ_min < 0` — slats tilt past flat both
ways), the pose is **mirrored** onto the other lean: `θ → −θ`. A **single-ended**
mechanism (`θ_min ≥ 0`, the default) can't lean the other way, so it keeps the
same-side pose (up to vertical the slats present the same geometry to a beam from
either side); mirroring there would just clamp every far-side pose to the closed
end and collapse the curve each morning and evening. Travel is
`θ ∈ [θ_min, θ_max]`; a pose past the reachable end is **clamped**. `max_pos` is
applied once, downstream, as a *position* clamp (`apply_limits`) — not a reason
to switch shade poses.

**Position mapping** (linear over the signed travel range):

```
P% = clamp( (θ − θ_min) / (θ_max − θ_min) · 100 , 0, 100 )
```

---

## 4. Mode-selection algorithm (per cycle)

Runs inside the engine's `calculate_percentage()` (the SolarHandler path). The sun
is "up & valid" whenever `α > 0` and not in the blind-spot; otherwise the cover
falls through to the existing **default/park** position (night handling — free).

```
if α ≤ 0:                      → not valid → DefaultHandler parks at default pos
if sun in configured blind-spot (deadzone):   → MAX-SUNLIGHT   (house already shades)
compute γ, p, Δ
shadeable_side = |γ| < 90       (else plan to mirror to the other side)

# Occupancy-shading test — does a direct beam pass THROUGH the roof onto the
# protected footprint? Horizontal shadow shift from roof (H) to plane (h):
Δr = (H − h) / tanα                      # large when sun low
D  = 2·( a_x·|sinAz| + a_y·|cosAz| )     # footprint depth along the sun azimuth
                                         # (a_x, a_y = footprint half-extents E/N)

if Δr ≥ D:                     → MAX-SUNLIGHT   (sun too low: area side-lit, slats useless)
else:                          → MAX-SHADE      (beams come through the roof → block them)
                                 mirror pose if not shadeable_side
```

- **Max-sunlight** → `θ = p` (mirror if needed), clamp, map to %.
- **Max-shade** → `θ = p ± Δ` per the airflow/closed switch (mirror if needed),
  clamp, map to %.

**Winter max-light (climate).** When ACP's Climate mode winter-heating strategy is
the active pipeline decision, the policy's `post_pipeline_resolve` overrides the
position to the **max-sunlight** pose for solar gain (localized to the policy; the
climate slat-rules module is untouched).

**Rain.** No new code: the existing weather-override / custom-position slot drives
a flat watertight position (recommend a low % = θ near 0 / overlap).

---

## 5. Config fields (new `CONF_*` in `const.py`)

Roof-orientation block:
- `CONF_LR_AXIS_AZIMUTH` (deg, default 90 = E-W)
- `CONF_LR_PLANE_PITCH` (deg, default 0 = flat)
- `CONF_LR_ROOF_HEIGHT` H (m, e.g. 3.0)
- `CONF_LR_PROTECTED_HEIGHT` h (m, default 1.8)
- `CONF_LR_FOOTPRINT_X`, `CONF_LR_FOOTPRINT_Y` (m, full extents E-W / N-S)
  *(TODO in code: allow asymmetric per-side extents instead of a centered rect.)*

Slat block:
- `CONF_LR_SLAT_CHORD` L (cm), `CONF_LR_SLAT_THICKNESS` t (cm), `CONF_LR_SLAT_SPACING` S (cm)
- `CONF_LR_THETA_MIN` (deg, default **0** = single-ended: flat is fully closed,
  θ=0 → 0 %; set `< 0` for a bi-directional mechanism), `CONF_LR_THETA_MAX`
  (deg, default 135)

Runtime:
- Shade flavor → **switch** entity (`shade_airflow`), not a config field.
- Blind-spot (deadzone) → reuse the existing ACP blind-spot config.

---

## 6. File-by-file plan

| File | Change |
| --- | --- |
| `const.py` | `CoverType.LOUVERED_ROOF = "cover_louvered_roof"` + display_name; `CONF_LR_*`, `DEFAULT_LR_*`, ranges; `ShadeFlavor` enum |
| `config_types.py` | `LouveredRoofConfig` dataclass + `from_options()` |
| `services/configuration_service.py` | `get_louvered_roof_data(options)` |
| `engine/covers/louvered_roof.py` | `AdaptiveLouveredRoofCover` — §2–4 geometry, `calculate_position`/`calculate_percentage`, `max_light_percentage()`, validity override (track when `α>0`) |
| `engine/covers/__init__.py` | export the new engine |
| `cover_types/louvered_roof.py` | `LouveredRoofPolicy(register=True)`, `axes=(TILT_AXIS,)`, geometry schema, `build_calc_engine`, `post_pipeline_resolve` (winter max-light), summary lines, capability warning (needs `set_tilt_position`), wiki anchor, label |
| `cover_types/__init__.py` | import so `register=True` fires |
| `switch.py` | add `shade_airflow` switch spec + coordinator toggle prop |
| `cover_types/_summary_labels.py` | `cover_types.louvered_roof` + `geometry.louvered_roof.*` labels |
| `translations/en.json` | `mode` selector option, section/field strings, switch name (de/fr via `acp-translate`) |
| `tests/test_cover_types/` + `tests/test_engine/` | engine geometry table (Linz reference), mode-selection thresholds, position mapping, mirror/clamp, policy registration |

No edits to the pipeline, registry, type-picker menu, or coordinator update loop —
the type picker is driven by `POLICY_REGISTRY` filtered on `controls_cover`.

---

## 7. Assumptions (confidence)

| # | Assumption | Conf. |
| --- | --- | --- |
| A1 | Roof footprint ⊇ protected footprint; v1 uses one centered rectangle for both. | med |
| A2 | Pergola is open-sided (no walls) — low sun side-lights the area, slats can't help → max-sunlight. | high |
| A3 | `θ=0` = flat/overlapping/closed; θ increases toward vertical; edge-on for high sun ≈ θ→90. | high |
| A4 | Mode trigger `Δr ≥ D ⇒ max-sunlight` is an acceptable first-order occupancy test. | **needs confirm** |
| A5 | Mirror = negate θ then clamp to `[θ_min,θ_max]`; asymmetric range supported. | high |
| A6 | Winter max-light via `post_pipeline_resolve`, leaving climate slat-rules untouched. | med |

---

*Worked reference to validate against (Linz, solar noon ⇒ p = α), from the issue:*

| Date | p | Δ | Max-light θ=p | Shade (p−Δ) | Shade+air (p+Δ) |
| --- | --- | --- | --- | --- | --- |
| Summer solstice | 65 | 51 | 65 / 48% | 14 / 11% | 116 / 86% |
| Equinox | 42 | 31 | 42 / 31% | 11 / 8% | 72 / 54% |
| Winter solstice | 18 | 9 | 18 / 13% | 9 / 7% | 27 / 20% |

(% column uses `k = 135/100` — the default single-ended `θ_min = 0, θ_max = 135`
mapping. Δ here is the **raw** grazing half-angle; the engine's `Δ_eff` bakes in
the `f ≥ 0.12` safety margin, so the actual airflow pose is a few degrees steeper
— e.g. summer `p+Δ_eff ≈ 130°/96 %` rather than the raw `116°/86 %`. Off-plane,
where the margin vent pose is unreachable, the airflow flavor degrades to the raw
grazing `Δ` on the same steep side — it stays steep/venting, it does not open.)
