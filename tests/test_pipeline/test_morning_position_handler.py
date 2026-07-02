"""Tests for MorningPositionHandler (pre-sunrise morning position)."""

from __future__ import annotations

from custom_components.adaptive_cover_pro.const import ControlMethod
from custom_components.adaptive_cover_pro.pipeline.handlers.morning_position import (
    MorningPositionHandler,
)
from tests.test_pipeline.conftest import make_snapshot


class TestMorningPositionHandler:
    """Test MorningPositionHandler."""

    handler = MorningPositionHandler()

    def test_priority_sits_between_solar_and_glare_zone(self) -> None:
        """Priority 43 — above solar (40), below glare-zone (45)."""
        assert self.handler.priority == 43

    def test_returns_none_when_window_inactive(self) -> None:
        """No result when the morning window is not active."""
        snap = make_snapshot(morning_active=False, morning_position=30)
        assert self.handler.evaluate(snap) is None

    def test_returns_configured_position_when_active(self) -> None:
        """Return the configured morning position while the window is active."""
        snap = make_snapshot(morning_active=True, morning_position=30)
        result = self.handler.evaluate(snap)
        assert result is not None
        assert result.control_method == ControlMethod.MORNING
        assert result.position == 30

    def test_falls_back_to_default_when_position_unset(self) -> None:
        """With no configured morning position, use the effective default."""
        snap = make_snapshot(
            morning_active=True, morning_position=None, default_position=55
        )
        result = self.handler.evaluate(snap)
        assert result is not None
        assert result.position == 55
        assert "default" in result.reason

    def test_fires_regardless_of_sun_and_time_window(self) -> None:
        """Fires even with no sun and outside the operating time window."""
        snap = make_snapshot(
            morning_active=True,
            morning_position=20,
            direct_sun_valid=False,
            in_time_window=False,
        )
        result = self.handler.evaluate(snap)
        assert result is not None
        assert result.position == 20

    def test_zero_position_is_respected(self) -> None:
        """A configured 0% (fully closed) morning position is not treated as unset."""
        snap = make_snapshot(
            morning_active=True, morning_position=0, default_position=80
        )
        result = self.handler.evaluate(snap)
        assert result is not None
        assert result.position == 0
