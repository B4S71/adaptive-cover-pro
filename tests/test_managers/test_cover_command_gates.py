"""Unit tests for check_position_delta gate function extensions.

Tests that the gate function accepts optional axis_label and
special_positions=None without changing existing behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from custom_components.adaptive_cover_pro.managers.cover_command.gates import (
    check_position_delta,
)


def _logger():
    return MagicMock()


class TestCheckPositionDeltaExtensions:
    """Backward-compatible extensions to check_position_delta for tilt axis reuse."""

    def test_check_position_delta_with_no_special_positions(self):
        """Passing special_positions=None behaves the same as passing an empty list."""
        logger = _logger()
        # delta=10, min_change=5 → should pass with special_positions=None
        result_none = check_position_delta(
            "cover.x", 60, 5, None, position=50, logger=logger
        )
        result_empty = check_position_delta(
            "cover.x", 60, 5, [], position=50, logger=logger
        )
        assert result_none == result_empty
        assert result_none is True

        # delta=2, min_change=5 → should fail with special_positions=None
        result_small = check_position_delta(
            "cover.x", 52, 5, None, position=50, logger=logger
        )
        assert result_small is False

    def test_check_position_delta_uses_axis_label_in_log(self):
        """When axis_label='tilt' is passed, the debug log contains 'tilt'."""
        logger = _logger()
        check_position_delta(
            "cover.x", 60, 5, None, position=50, logger=logger, axis_label="tilt"
        )
        # The logger.debug was called and at least one call message contains 'tilt'
        assert any("tilt" in str(call) for call in logger.debug.call_args_list)
