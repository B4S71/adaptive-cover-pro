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

**Poses** (θ = slat angle from horizontal; θ=0 flat/overlapping/closed):

| Pose | θ |
| --- | --- |
| Max-sunlight (edge-on) | `θ = p` |
| Max-shade, *closed* flavor | `θ = p − Δ` |
| Max-shade, *airflow* flavor | `θ = p + Δ` |

**Side / mirror.** When the sun is on the far side of the axis (`|γ| > 90°`), the
trackable projection points to the non-lifting edge. **Mirror** the pose:
`θ → −θ`. Travel is **asymmetric bi-directional**: `θ ∈ [θ_min, θ_max]` (e.g.
`−45 … +135`). A pose past the reachable end is **clamped** (single-ended or
short-side mechanisms just can't fully mirror — expected).

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
- `CONF_LR_THETA_MIN` (deg, default −45), `CONF_LR_THETA_MAX` (deg, default 135)

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

(% column uses the single-ended `k = 135/100`; the bi-directional asymmetric
mapping in §3 reduces to the same on the primary side when `θ_min = 0`.)
