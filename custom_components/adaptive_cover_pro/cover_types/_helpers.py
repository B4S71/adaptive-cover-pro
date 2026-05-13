"""Shared helpers for cover-type policy summary rendering."""

from __future__ import annotations

from typing import Any

from ..const import CONF_DISTANCE, CONF_HEIGHT_WIN, CONF_SILL_HEIGHT, CONF_WINDOW_DEPTH


def window_dimensions_lines(config: dict[str, Any]) -> list[str]:
    """Render the "<H>m tall window, blocking sun <D>m..." block.

    Used by both ``BlindPolicy`` and ``VenetianPolicy`` since their geometry
    summary leads with the same window-dimensions sentence.
    """
    h = config.get(CONF_HEIGHT_WIN)
    d = config.get(CONF_DISTANCE)
    depth = config.get(CONF_WINDOW_DEPTH) or 0
    sill = config.get(CONF_SILL_HEIGHT) or 0
    dim_parts: list[str] = []
    if h is not None:
        dim_parts.append(f"{h}m tall window")
    if d is not None:
        dim_parts.append(f"blocking sun {d}m from the glass")
    extras: list[str] = []
    if depth > 0:
        extras.append(f"reveal {depth}m")
    if sill > 0:
        extras.append(f"sill {sill}m")
    dim_str = ", ".join(dim_parts)
    if extras:
        dim_str += f" ({', '.join(extras)})"
    return [dim_str] if dim_str else []
