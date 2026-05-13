"""Tests for VenetianPolicy.post_pipeline_resolve.

Covers the SOLAR gate (tilt is only computed when the solar pipeline won)
and the tilt-only mode position rewrite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.adaptive_cover_pro.cover_types.venetian import VenetianPolicy
from custom_components.adaptive_cover_pro.enums import ControlMethod
from custom_components.adaptive_cover_pro.pipeline.types import PipelineResult


def _make_result(method: ControlMethod, position: int = 50) -> PipelineResult:
    return PipelineResult(position=position, control_method=method, reason="test")


def _make_policy() -> VenetianPolicy:
    return VenetianPolicy()


def _config_service_stub():
    """Minimal config_service stub that returns objects the engine can use."""
    from tests.cover_helpers import make_tilt_config, make_vertical_config

    svc = MagicMock()
    svc.get_vertical_data.return_value = make_vertical_config()
    svc.get_tilt_data.return_value = make_tilt_config()
    return svc


def _solar_kwargs():
    """Kwargs suitable for a SOLAR post_pipeline_resolve call."""
    from tests.cover_helpers import make_cover_config

    sun_data = MagicMock()
    sun_data.timezone = "UTC"
    return {
        "logger": MagicMock(),
        "sol_azi": 180.0,
        "sol_elev": 45.0,
        "sun_data": sun_data,
        "config": make_cover_config(),
        "config_service": _config_service_stub(),
        "options": {},
    }


def _non_solar_kwargs():
    """Kwargs for a non-SOLAR call — dependencies should never be touched."""
    return {
        "logger": MagicMock(),
        "sol_azi": 0.0,
        "sol_elev": -10.0,
        "sun_data": MagicMock(),
        "config": MagicMock(),
        "config_service": MagicMock(),
        "options": {},
    }


class TestPostPipelineResolveSolarGate:
    """Tilt is meaningful only when the solar handler drove the position decision."""

    def test_tilt_set_when_control_method_is_solar(self):
        policy = _make_policy()
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.SOLAR), **_solar_kwargs()
        )
        assert out.tilt is not None

    @pytest.mark.parametrize(
        "method",
        [
            ControlMethod.DEFAULT,
            ControlMethod.MANUAL,
            ControlMethod.WEATHER,
            ControlMethod.FORCE,
            ControlMethod.MOTION,
            ControlMethod.CUSTOM_POSITION,
            ControlMethod.SUMMER,
            ControlMethod.WINTER,
            ControlMethod.CLOUD,
            ControlMethod.GLARE_ZONE,
        ],
    )
    def test_tilt_is_none_for_non_solar_control_method(self, method):
        policy = _make_policy()
        out = policy.post_pipeline_resolve(_make_result(method), **_non_solar_kwargs())
        assert out.tilt is None

    def test_non_solar_position_is_unchanged(self):
        """The position must not be altered for non-solar decisions."""
        policy = _make_policy()
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.WEATHER, position=75), **_non_solar_kwargs()
        )
        assert out.position == 75

    def test_none_result_returned_unchanged(self):
        """Guard against coordinator passing None on cold-start."""
        policy = _make_policy()
        out = policy.post_pipeline_resolve(None, **_non_solar_kwargs())
        assert out is None


class TestPostPipelineResolveTiltOnlyMode:
    """tilt_only mode forces position to 0 when solar drives the decision."""

    def test_tilt_only_rewrites_position_to_zero_for_solar(self):
        from custom_components.adaptive_cover_pro.const import VENETIAN_MODE_TILT_ONLY

        policy = _make_policy()
        policy._venetian_mode = VENETIAN_MODE_TILT_ONLY
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.SOLAR, position=50), **_solar_kwargs()
        )
        assert out.position == 0
        assert out.tilt is not None

    def test_tilt_only_records_venetian_mode_trace_step(self):
        from custom_components.adaptive_cover_pro.const import VENETIAN_MODE_TILT_ONLY

        policy = _make_policy()
        policy._venetian_mode = VENETIAN_MODE_TILT_ONLY
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.SOLAR, position=50), **_solar_kwargs()
        )
        handler_names = [s.handler for s in out.decision_trace]
        assert "venetian_mode" in handler_names

    def test_tilt_only_does_not_rewrite_for_non_solar(self):
        from custom_components.adaptive_cover_pro.const import VENETIAN_MODE_TILT_ONLY

        policy = _make_policy()
        policy._venetian_mode = VENETIAN_MODE_TILT_ONLY
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.WEATHER, position=80), **_non_solar_kwargs()
        )
        assert out.position == 80
        assert out.tilt is None

    def test_position_and_tilt_mode_does_not_rewrite_position(self):
        """Default mode must not collapse position to 0."""
        policy = _make_policy()
        out = policy.post_pipeline_resolve(
            _make_result(ControlMethod.SOLAR, position=50), **_solar_kwargs()
        )
        assert out.position == 50
