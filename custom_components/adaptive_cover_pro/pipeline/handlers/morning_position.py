"""Morning-position handler — hold a fixed position in the pre-sunrise window."""

from __future__ import annotations

from ...const import ControlMethod
from ..handler import OverrideHandler
from ..helpers import compute_default_position
from ..types import PipelineResult, PipelineSnapshot


class MorningPositionHandler(OverrideHandler):
    """Hold the configured pre-sunrise "morning" position before sunrise.

    Priority 43 — above SolarHandler (40), below GlareZoneHandler (45). Fires
    whenever the pre-sunrise window is active (``snapshot.morning_active``),
    which the coordinator computes from the sunrise resume boundary and the
    configured lead time. Unlike SolarHandler it does NOT gate on sun visibility
    or the operating time window: the whole point is to open the cover to a
    known position while the sun is still below the horizon, instead of falling
    through to the default position.

    The position is ``snapshot.morning_position`` when configured (an explicit
    fixed target, limit-exempt like the sunset position), otherwise the effective
    default position with the same min/max treatment the DefaultHandler applies —
    so an enabled-but-position-less config simply opens early to the same default
    the cover would otherwise show, and the live result matches the forecast.
    """

    name = "morning_position"
    priority = 43

    def evaluate(self, snapshot: PipelineSnapshot) -> PipelineResult | None:
        """Return the morning position while the pre-sunrise window is active."""
        if not snapshot.morning_active:
            return None
        configured = snapshot.morning_position
        if configured is not None:
            position = configured
            source = "configured"
        else:
            position = compute_default_position(snapshot)
            source = "default"
        return PipelineResult(
            position=position,
            tilt=snapshot.default_tilt,
            control_method=ControlMethod.MORNING,
            reason=f"pre-sunrise morning position ({source}) {position}%",
            raw_calculated_position=position,
        )

    def describe_skip(self, snapshot: PipelineSnapshot) -> str:  # noqa: ARG002
        """Reason when the morning-position handler does not match."""
        return "pre-sunrise morning window not active"
