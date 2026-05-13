"""CoverTypePolicy base class.

One concrete subclass per supported cover type. The coordinator selects a
single instance via ``get_policy()`` at startup; every venetian-specific
decision (calc engine choice, post-pipeline tilt fill, manual-override
secondary axis, dual-axis cover-command sequencing) lives behind a hook
on this class so the shared code paths never branch on cover type.

Three of four cover types (blind, awning, tilt) implement only
``build_calc_engine``; the rest of the hooks default to no-ops. Venetian
overrides everything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.const import (
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)

from ..const import ATTR_POSITION, ATTR_TILT_POSITION, POSITION_CLOSED, POSITION_OPEN
from ..helpers import get_open_close_state, should_use_tilt, state_attr

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

    from ..engine.covers import AdaptiveGeneralCover
    from ..pipeline.types import PipelineResult
    from ..services.configuration_service import ConfigurationService


# ---------------------------------------------------------------------------
# Axis-related string constants
# ---------------------------------------------------------------------------
# HA cover entities expose two scalar attributes for current state and two
# capability flags in supported_features. These names are part of HA's contract
# so they're stable strings — naming them here lets the policy/axis layer
# reference symbolic identifiers instead of raw literals.

STATE_ATTR_POSITION = "current_position"
STATE_ATTR_TILT_POSITION = "current_tilt_position"

CAP_HAS_SET_POSITION = "has_set_position"
CAP_HAS_SET_TILT_POSITION = "has_set_tilt_position"
CAP_HAS_OPEN = "has_open"
CAP_HAS_CLOSE = "has_close"
CAP_HAS_STOP = "has_stop"

AXIS_NAME_POSITION = "position"
AXIS_NAME_TILT = "tilt"


@dataclass(frozen=True, slots=True)
class CoverAxis:
    """One controllable axis on a cover entity.

    Encodes everything the control code currently re-derives from the cover
    type string: the HA service to call, the service-data attribute that
    carries the target value, the state attribute that carries the current
    value, the capability flag that signals "this entity exposes this axis",
    and the cover-type semantic of "what does fully-open mean". Passing a
    ``CoverAxis`` around eliminates ``cover_type == "cover_tilt"`` checks at
    call sites.
    """

    name: str
    service: str
    service_attr: str
    state_attr: str
    capability_key: str
    open_blocks_sun: bool


# Module-level singletons. Each policy declares ``axes`` referencing these so
# every policy describing a position axis shares one ``CoverAxis`` instance.
# Awning's "open=blocks-sun" semantic differs from blind/tilt/venetian, so
# awning declares its own ``POSITION_AXIS_OPEN_BLOCKS_SUN`` rather than
# mutating the shared singleton.

POSITION_AXIS = CoverAxis(
    name=AXIS_NAME_POSITION,
    service=SERVICE_SET_COVER_POSITION,
    service_attr=ATTR_POSITION,
    state_attr=STATE_ATTR_POSITION,
    capability_key=CAP_HAS_SET_POSITION,
    open_blocks_sun=False,
)

POSITION_AXIS_OPEN_BLOCKS_SUN = CoverAxis(
    name=AXIS_NAME_POSITION,
    service=SERVICE_SET_COVER_POSITION,
    service_attr=ATTR_POSITION,
    state_attr=STATE_ATTR_POSITION,
    capability_key=CAP_HAS_SET_POSITION,
    open_blocks_sun=True,
)

TILT_AXIS = CoverAxis(
    name=AXIS_NAME_TILT,
    service=SERVICE_SET_COVER_TILT_POSITION,
    service_attr=ATTR_TILT_POSITION,
    state_attr=STATE_ATTR_TILT_POSITION,
    capability_key=CAP_HAS_SET_TILT_POSITION,
    open_blocks_sun=False,
)


def caps_get(caps: Any, key: str, default: bool = False) -> bool:
    """Read a capability flag from either a dict or a ``CoverCapabilities``.

    ``check_cover_features`` returns a dict; ``CoverProvider`` constructs the
    dataclass form. Both shapes are consumed throughout the integration so a
    single accessor — combined with the ``CAP_*`` constants above — replaces
    hardcoded ``caps.get("has_…")`` strings at every call site.
    """
    if caps is None:
        return default
    if isinstance(caps, dict):
        return bool(caps.get(key, default))
    return bool(getattr(caps, key, default))


# Internal alias retained for backward compatibility with existing imports.
_caps_get = caps_get


class CoverTypePolicy(ABC):
    """Per-cover-type policy."""

    cover_type: ClassVar[str]

    # Ordered tuple: the primary axis comes first. ``select_default_axis``
    # consults this when picking which HA service to call. Single-axis covers
    # (blind, awning, tilt) declare one entry; venetian declares two.
    axes: ClassVar[tuple[CoverAxis, ...]] = ()

    # Whether this cover type can shield specific floor zones from direct sun
    # (the "glare zones" feature). Only meaningful for vertical blinds today,
    # but a future cover type that gains the same capability flips this on
    # without touching every gate site.
    supports_glare_zones: ClassVar[bool] = False

    @abstractmethod
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
        """Instantiate the calculation engine for this cover type."""

    def post_pipeline_resolve(
        self,
        result: PipelineResult,
        *,
        logger,
        sol_azi: float,
        sol_elev: float,
        sun_data,
        config,
        config_service: ConfigurationService,
        options: dict,
    ) -> PipelineResult:
        """Enrich the pipeline result. Default: identity."""
        return result

    def position_context_overrides(self, result: PipelineResult) -> dict[str, Any]:
        """Extra kwargs for ``PositionContext``. Default: empty."""
        return {}

    def secondary_axis_check(self, result: PipelineResult, cmd_svc) -> Any | None:
        """Return a manual-override secondary-axis check, or ``None``."""
        return None

    def attach(self, **kwargs: Any) -> None:
        """Bind late-resolved dependencies (cmd_svc, grace_mgr, …).

        Called by the coordinator after ``CoverCommandService`` is built.
        Policies that need a long-lived helper (e.g. ``VenetianPolicy``'s
        dual-axis sequencer) construct it here. Default: no-op.
        """
        return

    def is_in_tilt_suppression(self, entity_id: str) -> bool:  # noqa: ARG002
        """Return whether the tilt-axis suppression window is open.

        Default ``False`` for cover types without a back-rotating tilt axis.
        """
        return False

    async def maybe_update_tilt_only(
        self,
        entity_id: str,  # noqa: ARG002
        *,
        current_position: int | None,  # noqa: ARG002
        context: Any,  # noqa: ARG002
        reason: str,  # noqa: ARG002
    ) -> None:
        """Send a tilt-only update when no position command will fire.

        Default: no-op for cover types without a tilt axis. VenetianPolicy
        overrides this to drive continuous tilt updates.
        """
        return

    async def after_position_command(
        self,
        cmd_svc,
        entity_id: str,
        *,
        service: str,
        position: int,
        context,
        reason: str,
    ) -> None:
        """Run any post-command work (default: no-op).

        Receives the actually-emitted ``service`` so policies can branch on
        which axis just fired (e.g. venetian only sequences after a position
        command, not after a direct tilt command).
        """
        return

    # ---- Axis routing -------------------------------------------------- #

    def select_default_axis(self, caps: Any) -> CoverAxis:
        """Pick the axis ``CoverCommandService`` should target for this entity.

        Built on top of ``should_use_tilt`` so the existing fallback rule —
        "an entity that only advertises set_tilt_position routes to tilt
        regardless of declared cover type" — is preserved bit-for-bit.

        ``caps=None`` happens when ``check_cover_features`` could not read the
        entity (HA hasn't initialised it yet, or it's unavailable). The legacy
        callers normalised that to an empty dict; doing the same here means
        callers don't have to guard at every call site.
        """
        primary = self.axes[0]
        is_tilt_default = primary.name == AXIS_NAME_TILT
        if should_use_tilt(is_tilt_default, caps if caps is not None else {}):
            return TILT_AXIS
        return primary

    def position_for_intent(self, *, sun_through: bool) -> int:
        """Map a semantic intent to the numeric value for the primary axis.

        ``sun_through=True`` → "let sun reach the window" (winter heating).
        ``sun_through=False`` → "block sun" (summer cooling).

        Awning's "open=blocks-sun" semantic flips the answer compared to
        blind/tilt/venetian; the flip lives on ``axes[0].open_blocks_sun``
        rather than on the policy class itself.
        """
        primary = self.axes[0]
        if sun_through:
            return POSITION_CLOSED if primary.open_blocks_sun else POSITION_OPEN
        return POSITION_OPEN if primary.open_blocks_sun else POSITION_CLOSED

    def read_axis_value(
        self,
        hass: HomeAssistant,
        entity: str,
        caps: Any,
        *,
        state_obj: State | None = None,
    ) -> int | None:
        """Read the current value on the axis this policy targets by default.

        Single source of truth for the four call sites that historically did
        the same ``should_use_tilt → branch on attribute`` dance:
        ``CoverCommandService._read_position_with_capabilities``,
        ``CoverProvider.read_positions``, manual_override state-change
        handling, and the position-capability check inside ``_prepare_service_call``.
        """
        axis = self.select_default_axis(caps)
        if _caps_get(caps, axis.capability_key, default=True):
            if state_obj is not None:
                return state_obj.attributes.get(axis.state_attr)
            return state_attr(hass, entity, axis.state_attr)
        return get_open_close_state(hass, entity, state_obj=state_obj)

    # ---- Config-flow / options-service helpers ------------------------- #

    def cover_capability_warnings(self, known: dict[str, dict]) -> list[str]:
        """Return user-facing warnings about the bound covers' capabilities.

        Default: no warnings — vertical / awning / tilt logic still lives in
        ``config_flow._check_cover_capabilities``. ``VenetianPolicy``
        overrides to express its dual-axis capability requirement.
        """
        return []

    def glare_zones_config(self, config_service, options: dict) -> Any | None:
        """Return a ``GlareZonesConfig`` for this cover, or ``None``.

        Default ``None`` — only ``BlindPolicy`` reads its glare-zone config
        from options. Lets the coordinator populate the snapshot without
        branching on cover type.
        """
        return None

    def disallowed_geometry_fields(
        self,
        *,
        vertical_only: set[str],
        awning_only: set[str],
        tilt_only: set[str],
    ) -> list[tuple[set[str], str]]:
        """List ``(field_set, type_label)`` pairs that are invalid for this cover.

        ``options_service.validate_options_patch`` uses this to decide which
        cross-type geometry fields to reject. Default returns nothing — the
        caller must use this method to opt in (each registered policy
        implements it explicitly so we don't silently fail open).
        """
        return []
