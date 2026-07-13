"""Tests for is_morning_preopen_active() — the pre-sunrise morning window."""

from __future__ import annotations

import datetime as dt
from datetime import UTC
from unittest.mock import MagicMock, patch

from custom_components.adaptive_cover_pro.helpers import is_morning_preopen_active


def _sun(sunrise_hour: int = 6, sunrise_minute: int = 0) -> MagicMock:
    """Mock SunData whose sunrise() returns a naive-UTC datetime for today.

    Build this BEFORE entering ``_freeze_now`` — the freeze patches
    ``helpers.dt.datetime``, which is the shared ``datetime`` module singleton,
    so any ``dt.datetime(...)`` constructed inside the patch becomes a MagicMock.
    """
    today = dt.date.today()
    sun = MagicMock()
    sun.sunrise.return_value = dt.datetime(
        today.year, today.month, today.day, sunrise_hour, sunrise_minute, 0
    )
    return sun


def _freeze_now(hour: int, minute: int):
    """Patch helpers.dt.datetime.now(UTC) to today at hour:minute (naive UTC)."""
    today = dt.date.today()
    aware = dt.datetime(today.year, today.month, today.day, hour, minute, 0, tzinfo=UTC)
    return patch(
        "custom_components.adaptive_cover_pro.helpers.dt.datetime",
        **{"now.return_value": aware},
    )


class TestDisabled:
    """The lead time doubles as the enable switch."""

    def test_none_lead_is_off(self) -> None:
        sun = _sun()
        with _freeze_now(5, 50):
            assert is_morning_preopen_active(None, sun, 0) is False

    def test_zero_lead_is_off(self) -> None:
        sun = _sun()
        with _freeze_now(5, 50):
            assert is_morning_preopen_active(0, sun, 0) is False


class TestWindow:
    """Window is [ (sunrise + sunrise_off) − lead , (sunrise + sunrise_off) )."""

    def test_active_inside_window(self) -> None:
        # sunrise 06:00, off 0, lead 15 → window [05:45, 06:00)
        sun = _sun()
        with _freeze_now(5, 50):
            assert is_morning_preopen_active(15, sun, 0) is True

    def test_inactive_before_start(self) -> None:
        sun = _sun()
        with _freeze_now(5, 40):
            assert is_morning_preopen_active(15, sun, 0) is False

    def test_inactive_at_boundary_is_exclusive(self) -> None:
        # At exactly the resume boundary the morning window has ended.
        sun = _sun()
        with _freeze_now(6, 0):
            assert is_morning_preopen_active(15, sun, 0) is False

    def test_inactive_after_sunrise(self) -> None:
        sun = _sun()
        with _freeze_now(6, 5):
            assert is_morning_preopen_active(15, sun, 0) is False

    def test_start_is_inclusive(self) -> None:
        sun = _sun()
        with _freeze_now(5, 45):
            assert is_morning_preopen_active(15, sun, 0) is True


class TestHold:
    """hold_minutes keeps the window open AFTER the boundary (post-sunrise)."""

    def test_hold_extends_past_boundary(self) -> None:
        # sunrise 06:00, off 0, lead 15, hold 30 → window [05:45, 06:30)
        sun = _sun()
        with _freeze_now(6, 5):  # past sunrise, still within the hold
            assert is_morning_preopen_active(15, sun, 0, hold_minutes=30) is True

    def test_hold_end_is_exclusive(self) -> None:
        sun = _sun()
        with _freeze_now(6, 30):
            assert is_morning_preopen_active(15, sun, 0, hold_minutes=30) is False

    def test_hold_active_just_before_end(self) -> None:
        sun = _sun()
        with _freeze_now(6, 29):
            assert is_morning_preopen_active(15, sun, 0, hold_minutes=30) is True

    def test_hold_alone_enables_without_lead(self) -> None:
        # lead None/0 but hold 30 → window [06:00, 06:30); pre-sunrise stays OFF
        sun = _sun()
        with _freeze_now(5, 50):  # before sunrise → outside the post-sunrise hold
            assert is_morning_preopen_active(0, sun, 0, hold_minutes=30) is False
        with _freeze_now(6, 10):  # after sunrise, within hold
            assert is_morning_preopen_active(None, sun, 0, hold_minutes=30) is True

    def test_no_lead_no_hold_is_off(self) -> None:
        sun = _sun()
        with _freeze_now(6, 5):
            assert is_morning_preopen_active(0, sun, 0, hold_minutes=0) is False


class TestSunriseOffsetShiftsBoundary:
    """The resume boundary tracks sunrise + sunrise_off, so the window moves."""

    def test_negative_offset_moves_window_earlier(self) -> None:
        # sunrise 06:00, off -30 → boundary 05:30, lead 15 → window [05:15, 05:30)
        sun = _sun()
        with _freeze_now(5, 20):
            assert is_morning_preopen_active(15, sun, -30) is True

    def test_negative_offset_inactive_after_boundary(self) -> None:
        sun = _sun()
        with _freeze_now(5, 35):
            assert is_morning_preopen_active(15, sun, -30) is False
