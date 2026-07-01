"""Louvered roof / bioclimatic pergola cover policy.

Tiltable lamellas in a (near-)horizontal overhead plane rotating about a single
horizontal axis. Like the tilt-only policy its primary (and only) axis is tilt,
so commands route to ``set_cover_tilt_position``. The calc engine
(:class:`AdaptiveLouveredRoofCover`) owns the occupancy-shading geometry; this
policy wires the config-flow geometry block, builds the engine, and remaps the
climate winter/summer decisions onto the roof's own max-sunlight / closed poses
(``post_pipeline_resolve``) so the venetian slat-climate rules are not misused
for an overhead plane.

Design: ``codebase-analysis-docs/LOUVERED_ROOF_DESIGN.md``.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, ClassVar

import voluptuous as vol
from homeassistant.helpers import selector

from ..config_types import LouveredRoofConfig
from ..const import (
    CONF_CLIMATE_MODE,
    CONF_LR_AIRFLOW_BY_TEMP,
    CONF_LR_AXIS_AZIMUTH,
    CONF_LR_FOOTPRINT_X,
    CONF_LR_FOOTPRINT_Y,
    CONF_LR_PARK_AT_DEFAULT,
    CONF_LR_PLANE_PITCH,
    CONF_LR_PROTECTED_HEIGHT,
    CONF_LR_ROOF_HEIGHT,
    CONF_LR_SHADE_AIRFLOW,
    CONF_LR_SLAT_CHORD,
    CONF_LR_SLAT_SPACING,
    CONF_LR_SLAT_THICKNESS,
    CONF_LR_THETA_MAX,
    CONF_LR_THETA_MIN,
    CONF_OUTSIDE_THRESHOLD,
    CONF_OUTSIDETEMP_ENTITY,
    CONF_TEMP_ENTITY,
    CONF_TEMP_HIGH,
    DEFAULT_LR_AIRFLOW_BY_TEMP,
    DEFAULT_LR_AXIS_AZIMUTH,
    DEFAULT_LR_FOOTPRINT_X,
    DEFAULT_LR_FOOTPRINT_Y,
    DEFAULT_LR_PLANE_PITCH,
    DEFAULT_LR_PARK_AT_DEFAULT,
    DEFAULT_LR_PROTECTED_HEIGHT,
    DEFAULT_LR_ROOF_HEIGHT,
    DEFAULT_LR_SHADE_AIRFLOW,
    DEFAULT_LR_SLAT_CHORD,
    DEFAULT_LR_SLAT_SPACING,
    DEFAULT_LR_SLAT_THICKNESS,
    DEFAULT_LR_THETA_MAX,
    DEFAULT_LR_THETA_MIN,
    _RANGE_LR_AXIS_AZIMUTH,
    _RANGE_LR_FOOTPRINT,
    _RANGE_LR_PLANE_PITCH,
    _RANGE_LR_PROTECTED_HEIGHT,
    _RANGE_LR_ROOF_HEIGHT,
    _RANGE_LR_SLAT_CM,
    _RANGE_LR_SLAT_THICKNESS,
    _RANGE_LR_THETA,
    ControlMethod,
)
from ..engine.covers import AdaptiveLouveredRoofCover
from ..pipeline.types import DecisionStep
from ..unit_system import length_default, length_selector, slat_default, slat_selector
from ._summary_labels import COVER_TYPE_LABELS_EN, GEOMETRY_LABELS_EN
from .base import (
    CAP_HAS_SET_TILT_POSITION,
    TILT_AXIS,
    CoverAxis,
    CoverTypePolicy,
    caps_get,
)
from .tilt import TILT_CAPABLE_ENTITY_FILTER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..engine.covers import AdaptiveGeneralCover
    from ..pipeline.types import PipelineResult
    from ..services.configuration_service import ConfigurationService


# Option keys stored in canonical metres / centimetres (config-flow conversion).
LOUVERED_ROOF_LENGTH_KEYS: tuple[str, ...] = (
    CONF_LR_ROOF_HEIGHT,
    CONF_LR_PROTECTED_HEIGHT,
    CONF_LR_FOOTPRINT_X,
    CONF_LR_FOOTPRINT_Y,
)
LOUVERED_ROOF_SLAT_KEYS: tuple[str, ...] = (
    CONF_LR_SLAT_CHORD,
    CONF_LR_SLAT_THICKNESS,
    CONF_LR_SLAT_SPACING,
)


def _as_float(value) -> float | None:
    """Coerce a config value (often a string like ``"20"``) to float, or None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _climate_wants_airflow(hass, options: dict) -> bool | None:
    """Whether climate mode wants the airflow vent (i.e. it is "hot").

    Hot when the outside temperature exceeds ``outside_threshold`` OR the inside
    temperature exceeds ``temp_high`` — the same thresholds ACP's climate
    "summer" branch uses. Returns ``None`` when neither temperature is readable,
    so the configured flavor is kept. Needs only the outside sensor to work.
    """
    inside = _read_temperature(hass, options.get(CONF_TEMP_ENTITY))
    outside = _read_temperature(hass, options.get(CONF_OUTSIDETEMP_ENTITY))
    th_out = _as_float(options.get(CONF_OUTSIDE_THRESHOLD))
    th_in = _as_float(options.get(CONF_TEMP_HIGH))
    votes: list[bool] = []
    if outside is not None and th_out is not None:
        votes.append(outside > th_out)
    if inside is not None and th_in is not None:
        votes.append(inside > th_in)
    if not votes:
        return None
    return any(votes)


def _read_temperature(hass, entity: str | None) -> float | None:
    """Read a temperature entity as a float, or ``None`` if unavailable.

    Accepts a plain sensor (its numeric state) or a ``climate.*`` entity (its
    ``current_temperature`` attribute), matching how ``ClimateProvider`` reads
    the inside-temperature sensor.
    """
    if not entity or hass is None:
        return None
    from ..helpers import get_domain, get_safe_state, state_attr

    raw = (
        state_attr(hass, entity, "current_temperature")
        if get_domain(entity) == "climate"
        else get_safe_state(hass, entity)
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _deg_selector(lo: float, hi: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=lo,
            max=hi,
            step=1,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="°",
        )
    )


def geometry_louvered_roof_schema(hass: HomeAssistant | None = None) -> vol.Schema:
    """Louvered-roof geometry schema. ``hass=None`` → metric labels."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LR_AXIS_AZIMUTH, default=DEFAULT_LR_AXIS_AZIMUTH
            ): _deg_selector(*_RANGE_LR_AXIS_AZIMUTH),
            vol.Optional(
                CONF_LR_PLANE_PITCH, default=DEFAULT_LR_PLANE_PITCH
            ): _deg_selector(*_RANGE_LR_PLANE_PITCH),
            vol.Required(
                CONF_LR_ROOF_HEIGHT, default=length_default(DEFAULT_LR_ROOF_HEIGHT, hass)
            ): length_selector(
                hass,
                min_m=_RANGE_LR_ROOF_HEIGHT[0],
                max_m=_RANGE_LR_ROOF_HEIGHT[1],
                metric_step=0.05,
            ),
            vol.Required(
                CONF_LR_PROTECTED_HEIGHT,
                default=length_default(DEFAULT_LR_PROTECTED_HEIGHT, hass),
            ): length_selector(
                hass,
                min_m=_RANGE_LR_PROTECTED_HEIGHT[0],
                max_m=_RANGE_LR_PROTECTED_HEIGHT[1],
                metric_step=0.05,
            ),
            vol.Required(
                CONF_LR_FOOTPRINT_X,
                default=length_default(DEFAULT_LR_FOOTPRINT_X, hass),
            ): length_selector(
                hass,
                min_m=_RANGE_LR_FOOTPRINT[0],
                max_m=_RANGE_LR_FOOTPRINT[1],
                metric_step=0.1,
            ),
            vol.Required(
                CONF_LR_FOOTPRINT_Y,
                default=length_default(DEFAULT_LR_FOOTPRINT_Y, hass),
            ): length_selector(
                hass,
                min_m=_RANGE_LR_FOOTPRINT[0],
                max_m=_RANGE_LR_FOOTPRINT[1],
                metric_step=0.1,
            ),
            vol.Required(
                CONF_LR_SLAT_CHORD, default=slat_default(DEFAULT_LR_SLAT_CHORD, hass)
            ): slat_selector(hass, min_cm=_RANGE_LR_SLAT_CM[0], max_cm=_RANGE_LR_SLAT_CM[1]),
            vol.Required(
                CONF_LR_SLAT_THICKNESS,
                default=slat_default(DEFAULT_LR_SLAT_THICKNESS, hass),
            ): slat_selector(
                hass,
                min_cm=_RANGE_LR_SLAT_THICKNESS[0],
                max_cm=_RANGE_LR_SLAT_THICKNESS[1],
            ),
            vol.Required(
                CONF_LR_SLAT_SPACING, default=slat_default(DEFAULT_LR_SLAT_SPACING, hass)
            ): slat_selector(hass, min_cm=_RANGE_LR_SLAT_CM[0], max_cm=_RANGE_LR_SLAT_CM[1]),
            vol.Required(
                CONF_LR_THETA_MIN, default=DEFAULT_LR_THETA_MIN
            ): _deg_selector(*_RANGE_LR_THETA),
            vol.Required(
                CONF_LR_THETA_MAX, default=DEFAULT_LR_THETA_MAX
            ): _deg_selector(*_RANGE_LR_THETA),
            # Backs the "Shade airflow" runtime switch (option-backed). Shown here
            # too so config-flow users can set the default and so the key is a
            # valid live option for validation.
            vol.Optional(
                CONF_LR_SHADE_AIRFLOW, default=DEFAULT_LR_SHADE_AIRFLOW
            ): selector.BooleanSelector(),
            # Backs the "Park at Default" runtime switch (option-backed). When on,
            # the cover holds its default position whenever no sun reaches the
            # protected plane, instead of the max-sunlight curve.
            vol.Optional(
                CONF_LR_PARK_AT_DEFAULT, default=DEFAULT_LR_PARK_AT_DEFAULT
            ): selector.BooleanSelector(),
            # Drive the airflow flavor from the climate-section temperature
            # sensors instead of the manual switch: vent only when the terrace
            # (inside temp) is hotter than outside AND outside exceeds the
            # climate-section ``outside_threshold`` — so a cool evening keeps
            # the warmth in.
            vol.Optional(
                CONF_LR_AIRFLOW_BY_TEMP, default=DEFAULT_LR_AIRFLOW_BY_TEMP
            ): selector.BooleanSelector(),
        }
    )


GEOMETRY_LOUVERED_ROOF_SCHEMA = geometry_louvered_roof_schema()


class LouveredRoofPolicy(CoverTypePolicy, register=True):
    """Cover whose overhead lamellas tilt about one axis (bioclimatic pergola)."""

    cover_type = "cover_louvered_roof"
    axes: ClassVar[tuple[CoverAxis, ...]] = (TILT_AXIS,)
    supports_shade_airflow_switch: ClassVar[bool] = True
    supports_park_at_default_switch: ClassVar[bool] = True
    # Climate mode steers the airflow flavor here, not the position (see
    # build_calc_engine); the ClimateHandler defers so normal shading keeps the
    # position.
    climate_controls_position: ClassVar[bool] = False

    def wiki_anchor(self) -> str:
        """Louvered-roof geometry page."""
        return "Configuration-Louvered-Roof"

    def display_label(self, labels: dict[str, str] | None = None) -> str:
        """User-facing label for louvered roofs."""
        L = {**COVER_TYPE_LABELS_EN, **(labels or {})}
        return L["cover_types.louvered_roof"]

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """Reject window / awning / venetian-slat geometry — this type has its own."""
        return [
            (vertical_only, "vertical blind"),
            (awning_only, "awning"),
            (tilt_only, "tilt"),
        ]

    def geometry_schema(
        self,
        hass: HomeAssistant | None = None,
        options: dict | None = None,  # noqa: ARG002
    ) -> vol.Schema:
        """Return the louvered-roof geometry schema for the given locale."""
        if hass is None:
            return GEOMETRY_LOUVERED_ROOF_SCHEMA
        return geometry_louvered_roof_schema(hass)

    def geometry_length_keys(self) -> tuple[str, ...]:
        """Roof/protected heights and footprint extents are stored in metres."""
        return LOUVERED_ROOF_LENGTH_KEYS

    def geometry_slat_keys(self) -> tuple[str, ...]:
        """Lamella chord/thickness/spacing are stored in canonical centimetres."""
        return LOUVERED_ROOF_SLAT_KEYS

    def entity_selector_filter(self) -> selector.EntityFilterSelectorConfig:
        """Require entities that advertise ``set_tilt_position``."""
        return TILT_CAPABLE_ENTITY_FILTER

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Warn when no bound entity advertises ``set_tilt_position``."""
        if not any(
            caps_get(caps, CAP_HAS_SET_TILT_POSITION) for caps in known.values()
        ):
            return [
                "⚠️ Configured as louvered roof but no bound cover advertises "
                "set_tilt_position — the lamella angle cannot be commanded."
            ]
        return []

    def summary_geometry_lines(
        self, config: dict[str, Any], labels: dict[str, str] | None = None
    ) -> list[str]:
        """Render the axis / heights / slat / travel block."""
        L = {**GEOMETRY_LABELS_EN, **(labels or {})}
        parts: list[str] = []
        if (v := config.get(CONF_LR_AXIS_AZIMUTH)) is not None:
            parts.append(L["geometry.louvered_roof.axis"].format(v=v))
        if (v := config.get(CONF_LR_PLANE_PITCH)) is not None:
            parts.append(L["geometry.louvered_roof.pitch"].format(v=v))
        h = config.get(CONF_LR_ROOF_HEIGHT)
        p = config.get(CONF_LR_PROTECTED_HEIGHT)
        if h is not None and p is not None:
            parts.append(L["geometry.louvered_roof.heights"].format(h=h, p=p))
        lo = config.get(CONF_LR_THETA_MIN)
        hi = config.get(CONF_LR_THETA_MAX)
        if lo is not None and hi is not None:
            parts.append(L["geometry.louvered_roof.travel"].format(lo=lo, hi=hi))
        return [", ".join(parts)] if parts else []

    def build_calc_engine(
        self,
        *,
        logger,
        sol_azi: float,
        sol_elev: float,
        sun_data,
        config,
        config_service: ConfigurationService,
        options: dict,
    ) -> AdaptiveGeneralCover:
        """Build an ``AdaptiveLouveredRoofCover`` (occupancy-shading geometry).

        The shade-pose flavor (airflow vs closed) can be temperature-driven:

        * **Climate Mode on** → climate steers the flavor: vent when it is "hot"
          (outside above ``outside_threshold`` OR inside above ``temp_high``),
          otherwise closed. Climate does NOT move the position here (the handler
          defers via ``climate_controls_position``).
        * else **``lr_airflow_by_temp`` on** → vent only when the terrace (inside)
          is hotter than outside AND outside exceeds ``outside_threshold``.
        * else → the manual ``Shade Airflow`` switch.

        Temps are read live each cycle; if the inputs are unavailable the
        configured/switch flavor is kept.
        """
        lr_config = LouveredRoofConfig.from_options(options)
        hass = config_service.hass
        if options.get(CONF_CLIMATE_MODE, False):
            hot = _climate_wants_airflow(hass, options)
            if hot is not None:
                lr_config.shade_airflow = hot
        elif options.get(CONF_LR_AIRFLOW_BY_TEMP, DEFAULT_LR_AIRFLOW_BY_TEMP):
            inside = _read_temperature(hass, options.get(CONF_TEMP_ENTITY))
            outside = _read_temperature(hass, options.get(CONF_OUTSIDETEMP_ENTITY))
            threshold = _as_float(options.get(CONF_OUTSIDE_THRESHOLD))
            if inside is not None and outside is not None and threshold is not None:
                lr_config.shade_airflow = inside > outside and outside > threshold
        return AdaptiveLouveredRoofCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            lr_config=lr_config,
        )

    def post_pipeline_resolve(
        self,
        result: PipelineResult,
        *,
        logger,  # noqa: ARG002
        sol_azi: float,  # noqa: ARG002
        sol_elev: float,  # noqa: ARG002
        sun_data,  # noqa: ARG002
        config,  # noqa: ARG002
        config_service: ConfigurationService,  # noqa: ARG002
        options: dict,  # noqa: ARG002
        cover: AdaptiveGeneralCover | None = None,
    ) -> PipelineResult:
        """Remap a climate winter/summer decision onto the roof's own poses.

        The climate handler routes tilt-primary covers through the venetian
        slat-angle rules, which are wrong for an overhead plane. When the climate
        handler wins, override its position with the roof's geometry-correct pose:
        winter heating → max-sunlight (edge-on, for solar gain); summer cooling →
        fully closed (max shade). All other decisions pass through unchanged.
        """
        if cover is None or not isinstance(cover, AdaptiveLouveredRoofCover):
            return result
        if result.control_method == ControlMethod.WINTER:
            position = cover.max_light_percentage()
            reason = "louvered roof: winter heating → max-sunlight (edge-on)"
        elif result.control_method == ControlMethod.SUMMER:
            position = cover.closed_percentage()
            reason = "louvered roof: summer cooling → fully closed (max shade)"
        else:
            return result
        trace = list(result.decision_trace)
        trace.append(
            DecisionStep(
                handler="louvered_roof",
                matched=True,
                reason=reason,
                position=position,
            )
        )
        return dataclasses.replace(
            result, position=position, reason=reason, decision_trace=trace
        )
