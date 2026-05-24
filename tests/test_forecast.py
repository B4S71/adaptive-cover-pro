"""Tests for forecast.build_forecast — pure pure-function level coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock

import pytest

from custom_components.adaptive_cover_pro.forecast import (
    EVENT_FOV_ENTER,
    EVENT_FOV_EXIT,
    EVENT_SUNRISE,
    EVENT_SUNSET,
    FORECAST_STEP_MINUTES,
    FORECAST_WINDOW_HOURS,
    Forecast,
    ForecastEvent,
    ForecastSample,
    build_forecast,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


def _make_sun_data(
    *,
    n_samples: int = 96,
    step_minutes: int = 5,
    azi_at: float = 180.0,
    ele_at: float = 30.0,
    sunrise: datetime | None = None,
    sunset: datetime | None = None,
):
    """Build a minimal SunData stand-in for forecast tests.

    Produces a constant-sun timeline for *n_samples* steps of *step_minutes*
    starting at _NOW.  Tests that need a varying sun pattern can patch the
    azimuth/elevation lists after construction.
    """
    times = [_NOW + timedelta(minutes=i * step_minutes) for i in range(n_samples)]
    sd = MagicMock()
    sd.times = times
    sd.solar_azimuth = [azi_at] * n_samples
    sd.solar_elevation = [ele_at] * n_samples
    sd.sunrise = MagicMock(return_value=sunrise)
    sd.sunset = MagicMock(return_value=sunset)
    return sd


def _make_cover_factory(*, solar_valid: bool, percentage: int = 40):
    """Build a cover_factory closure used by build_forecast.

    The returned cover's direct_sun_valid always returns *solar_valid*; its
    calculate_percentage() always returns *percentage*.  Tests that want
    per-timestamp variation pass a custom factory.
    """

    def factory(azi: float, ele: float):  # noqa: ARG001
        cover = MagicMock()
        cover.direct_sun_valid = solar_valid
        cover.calculate_percentage = MagicMock(return_value=percentage)
        return cover

    return factory


# ---------------------------------------------------------------------------
# Sample series shape
# ---------------------------------------------------------------------------


class TestBuildForecastSamples:
    """build_forecast emits one sample per tick over the configured window."""

    def test_default_cadence_emits_step_per_15_minutes_for_12_hours(self):
        sd = _make_sun_data()
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=10,
            now=_NOW,
        )
        # 12 hours of 15-minute steps inclusive at both ends = 12 * 60 / 15 + 1.
        expected = (FORECAST_WINDOW_HOURS * 60 // FORECAST_STEP_MINUTES) + 1
        assert len(f.samples) == expected
        # All samples carry the configured default since solar isn't valid.
        assert all(s.position == 10 and s.handler == "default" for s in f.samples)

    def test_solar_valid_samples_use_calculated_percentage(self):
        sd = _make_sun_data()
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=True, percentage=55),
            default_position=10,
            now=_NOW,
        )
        assert all(s.position == 55 and s.handler == "solar" for s in f.samples)

    def test_custom_step_and_window_produce_proportional_sample_count(self):
        sd = _make_sun_data(n_samples=200, step_minutes=5)
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=0,
            now=_NOW,
            step_minutes=30,
            window_hours=4,
        )
        assert len(f.samples) == (4 * 60 // 30) + 1

    def test_empty_sun_data_returns_empty_samples_and_events(self):
        sd = _make_sun_data(n_samples=0)
        sd.times = []
        sd.solar_azimuth = []
        sd.solar_elevation = []
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=0,
            now=_NOW,
        )
        assert f.samples == ()
        assert f.events == ()


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------


class TestBuildForecastEvents:
    """Sunrise / sunset / FOV transitions land in the events list."""

    def test_sunrise_and_sunset_emitted_when_present(self):
        sunrise = _NOW + timedelta(hours=2)
        sunset = _NOW + timedelta(hours=10)
        sd = _make_sun_data(sunrise=sunrise, sunset=sunset)
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=0,
            now=_NOW,
        )
        kinds = [e.kind for e in f.events]
        assert EVENT_SUNRISE in kinds
        assert EVENT_SUNSET in kinds

    def test_sunrise_sunset_skipped_when_none_returned(self):
        sd = _make_sun_data(sunrise=None, sunset=None)
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=0,
            now=_NOW,
        )
        assert EVENT_SUNRISE not in [e.kind for e in f.events]
        assert EVENT_SUNSET not in [e.kind for e in f.events]

    def test_handler_switch_emits_fov_enter_and_exit(self):
        """Cover-factory swings direct_sun_valid mid-window → enter + exit events."""
        sd = _make_sun_data()
        # solar valid during minutes 30-90 (i.e. samples 2-6 at 15-min step).
        valid_window_start = _NOW + timedelta(minutes=30)
        valid_window_end = _NOW + timedelta(minutes=90)

        def factory(_azi, _ele):
            cover = MagicMock()
            cover.calculate_percentage = MagicMock(return_value=50)
            # Mutated per call via closure to time-of-call check is awkward; the
            # forecast walker passes (azi, ele) at *target* time, so we need a
            # different signal — use a counter tracking call index.
            return cover

        # Simpler: drive the switch by providing per-tick solar validity via a
        # cover_factory that toggles based on the call counter.
        call_state = {"calls": 0}
        toggle_points = [2, 6]  # sample indices where direct_sun_valid flips

        def toggling_factory(_azi, _ele):
            idx = call_state["calls"]
            call_state["calls"] += 1
            cover = MagicMock()
            cover.direct_sun_valid = toggle_points[0] <= idx < toggle_points[1]
            cover.calculate_percentage = MagicMock(return_value=50)
            return cover

        # Silence linters: factory + tick variables are intentionally unused.
        _ = factory
        _ = valid_window_start
        _ = valid_window_end

        f = build_forecast(
            sun_data=sd,
            cover_factory=toggling_factory,
            default_position=0,
            now=_NOW,
        )
        kinds = [e.kind for e in f.events]
        assert EVENT_FOV_ENTER in kinds
        assert EVENT_FOV_EXIT in kinds

    def test_events_returned_sorted_by_time(self):
        sd = _make_sun_data(
            sunrise=_NOW + timedelta(hours=4),
            sunset=_NOW + timedelta(hours=10),
        )
        f = build_forecast(
            sun_data=sd,
            cover_factory=_make_cover_factory(solar_valid=False),
            default_position=0,
            now=_NOW,
        )
        times = [e.t for e in f.events]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Wire-format serialization
# ---------------------------------------------------------------------------


class TestForecastToAttrs:
    """to_attrs() produces a stable wire shape for the diagnostic sensor."""

    def test_samples_serialise_with_iso_timestamps(self):
        f = Forecast(
            samples=(ForecastSample(t=_NOW, position=42, handler="solar"),),
            events=(),
        )
        attrs = f.to_attrs()
        assert attrs["forecast"] == [
            {"t": _NOW.isoformat(), "position": 42, "handler": "solar"}
        ]

    def test_events_serialise_with_iso_timestamps(self):
        f = Forecast(
            samples=(),
            events=(ForecastEvent(t=_NOW, kind=EVENT_SUNRISE, label="Sunrise"),),
        )
        attrs = f.to_attrs()
        assert attrs["events"] == [
            {"t": _NOW.isoformat(), "kind": "sunrise", "label": "Sunrise"}
        ]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("default", [0, 50, 100])
def test_default_position_round_trips_through_samples(default: int):
    """Whatever default_position we pass appears verbatim in non-solar samples."""
    sd = _make_sun_data()
    f = build_forecast(
        sun_data=sd,
        cover_factory=_make_cover_factory(solar_valid=False),
        default_position=default,
        now=_NOW,
    )
    assert {s.position for s in f.samples} == {default}
