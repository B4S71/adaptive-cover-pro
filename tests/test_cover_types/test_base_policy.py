"""Default CoverTypePolicy hook behaviour for non-venetian cover types."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.adaptive_cover_pro.cover_types.blind import BlindPolicy


@pytest.mark.asyncio
async def test_maybe_update_tilt_only_default_is_noop() -> None:
    """Base-class maybe_update_tilt_only must return None without side-effects."""
    policy = BlindPolicy()
    result = await policy.maybe_update_tilt_only(
        "cover.x",
        current_position=42,
        context=MagicMock(),
        reason="solar",
    )
    assert result is None
