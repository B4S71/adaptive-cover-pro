"""Tests for the CoverAxis abstraction layer.

Phase 1–4 of the cover-driver refactor introduced ``CoverAxis``, axis
declarations on each policy, and three policy methods (``select_default_axis``,
``position_for_intent``, ``read_axis_value``) that the rest of the codebase
consults instead of comparing cover-type strings. This file pins the
behavioural contract for those additions so a future refactor can't silently
break them.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from unittest.mock import MagicMock

import pytest

from custom_components.adaptive_cover_pro.const import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    POSITION_CLOSED,
    POSITION_OPEN,
)
from custom_components.adaptive_cover_pro.cover_types import get_policy
from custom_components.adaptive_cover_pro.cover_types.base import (
    AXIS_NAME_POSITION,
    AXIS_NAME_TILT,
    CAP_HAS_SET_POSITION,
    CAP_HAS_SET_TILT_POSITION,
    POSITION_AXIS,
    POSITION_AXIS_OPEN_BLOCKS_SUN,
    STATE_ATTR_POSITION,
    STATE_ATTR_TILT_POSITION,
    TILT_AXIS,
    CoverAxis,
)
from custom_components.adaptive_cover_pro.state.snapshot import CoverCapabilities

# Cover-type keys exercised across the parametrised tests below. Listed once
# here so adding a new cover type only changes one place (the parametrize
# decorators below pick up the new value automatically).
ALL_COVER_TYPES = ["cover_blind", "cover_awning", "cover_tilt", "cover_venetian"]


# ---------------------------------------------------------------------------
# CoverAxis dataclass shape
# ---------------------------------------------------------------------------


class TestCoverAxis:
    """The dataclass itself — frozen, slotted, hashable."""

    @pytest.mark.unit
    def test_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            POSITION_AXIS.name = "tilt"  # type: ignore[misc]

    @pytest.mark.unit
    def test_uses_slots(self):
        # ``slots=True`` removes ``__dict__``; trying to read it raises.
        with pytest.raises(AttributeError):
            POSITION_AXIS.__dict__  # noqa: B018

    @pytest.mark.unit
    def test_hashable(self):
        # Frozen dataclasses are hashable, so axes can live in sets / dict keys.
        assert {POSITION_AXIS, TILT_AXIS, POSITION_AXIS} == {POSITION_AXIS, TILT_AXIS}

    @pytest.mark.unit
    def test_equality_is_value_based(self):
        twin = CoverAxis(
            name=AXIS_NAME_POSITION,
            service=POSITION_AXIS.service,
            service_attr=POSITION_AXIS.service_attr,
            state_attr=POSITION_AXIS.state_attr,
            capability_key=POSITION_AXIS.capability_key,
            open_blocks_sun=False,
        )
        assert twin == POSITION_AXIS


# ---------------------------------------------------------------------------
# Axis singletons carry the right HA-side identifiers
# ---------------------------------------------------------------------------


class TestAxisSingletons:
    """Sanity-check the constants other call sites depend on."""

    @pytest.mark.unit
    def test_position_axis_attrs(self):
        assert POSITION_AXIS.name == AXIS_NAME_POSITION
        assert POSITION_AXIS.service_attr == ATTR_POSITION
        assert POSITION_AXIS.state_attr == STATE_ATTR_POSITION
        assert POSITION_AXIS.capability_key == CAP_HAS_SET_POSITION
        assert POSITION_AXIS.open_blocks_sun is False

    @pytest.mark.unit
    def test_tilt_axis_attrs(self):
        assert TILT_AXIS.name == AXIS_NAME_TILT
        assert TILT_AXIS.service_attr == ATTR_TILT_POSITION
        assert TILT_AXIS.state_attr == STATE_ATTR_TILT_POSITION
        assert TILT_AXIS.capability_key == CAP_HAS_SET_TILT_POSITION
        assert TILT_AXIS.open_blocks_sun is False

    @pytest.mark.unit
    def test_awning_position_axis_flips_sun_semantic(self):
        # Awning's "open=blocks-sun" semantic lives on the axis instance, so
        # ``position_for_intent`` falls out of the base implementation without
        # any subclass override.
        assert POSITION_AXIS_OPEN_BLOCKS_SUN.name == AXIS_NAME_POSITION
        assert POSITION_AXIS_OPEN_BLOCKS_SUN.open_blocks_sun is True


# ---------------------------------------------------------------------------
# Each policy declares the right axes
# ---------------------------------------------------------------------------


class TestPolicyAxesDeclarations:
    """Each policy declares the right axes tuple."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("cover_type", "expected_axis_names"),
        [
            ("cover_blind", (AXIS_NAME_POSITION,)),
            ("cover_awning", (AXIS_NAME_POSITION,)),
            ("cover_tilt", (AXIS_NAME_TILT,)),
            ("cover_venetian", (AXIS_NAME_POSITION, AXIS_NAME_TILT)),
        ],
    )
    def test_axes_declaration(self, cover_type, expected_axis_names):
        policy = get_policy(cover_type)
        assert tuple(a.name for a in policy.axes) == expected_axis_names

    @pytest.mark.unit
    def test_blind_tilt_venetian_dont_treat_open_as_sun_blocked(self):
        for cover_type in ("cover_blind", "cover_tilt", "cover_venetian"):
            assert get_policy(cover_type).axes[0].open_blocks_sun is False

    @pytest.mark.unit
    def test_awning_treats_open_as_sun_blocked(self):
        assert get_policy("cover_awning").axes[0].open_blocks_sun is True


# ---------------------------------------------------------------------------
# select_default_axis — parity with the legacy should_use_tilt routing rule
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        # (label, caps, expected axis name per policy primary)
        (
            "full-capable",
            {"has_set_position": True, "has_set_tilt_position": True},
            {
                "cover_blind": AXIS_NAME_POSITION,
                "cover_awning": AXIS_NAME_POSITION,
                "cover_tilt": AXIS_NAME_TILT,
                "cover_venetian": AXIS_NAME_POSITION,
            },
        ),
        (
            "position-only",
            {"has_set_position": True, "has_set_tilt_position": False},
            {
                "cover_blind": AXIS_NAME_POSITION,
                "cover_awning": AXIS_NAME_POSITION,
                "cover_tilt": AXIS_NAME_TILT,  # cover_tilt always routes tilt
                "cover_venetian": AXIS_NAME_POSITION,
            },
        ),
        (
            "tilt-only-fallback",
            {"has_set_position": False, "has_set_tilt_position": True},
            {
                # The "entity only supports tilt" rule overrides declared type:
                # blind/awning/venetian get routed to TILT_AXIS too.
                "cover_blind": AXIS_NAME_TILT,
                "cover_awning": AXIS_NAME_TILT,
                "cover_tilt": AXIS_NAME_TILT,
                "cover_venetian": AXIS_NAME_TILT,
            },
        ),
    ],
    ids=lambda p: p[0],
)
def caps_scenario(request):
    return request.param


class TestSelectDefaultAxis:
    """``select_default_axis`` matches the legacy ``should_use_tilt`` rule."""

    @pytest.mark.unit
    @pytest.mark.parametrize("cover_type", ALL_COVER_TYPES)
    def test_dict_caps(self, caps_scenario, cover_type):
        _label, caps, expected = caps_scenario
        axis = get_policy(cover_type).select_default_axis(caps)
        assert axis.name == expected[cover_type]

    @pytest.mark.unit
    @pytest.mark.parametrize("cover_type", ALL_COVER_TYPES)
    def test_dataclass_caps(self, caps_scenario, cover_type):
        _label, caps_dict, expected = caps_scenario
        caps = CoverCapabilities(
            has_set_position=caps_dict["has_set_position"],
            has_set_tilt_position=caps_dict["has_set_tilt_position"],
            has_open=True,
            has_close=True,
        )
        axis = get_policy(cover_type).select_default_axis(caps)
        assert axis.name == expected[cover_type]

    @pytest.mark.unit
    @pytest.mark.parametrize("cover_type", ALL_COVER_TYPES)
    def test_none_caps_normalizes_to_empty(self, cover_type):
        # ``check_cover_features`` returns None when the entity isn't ready;
        # ``select_default_axis`` must not crash and must route to the policy's
        # primary axis (no tilt-fallback, since caps are unknown).
        policy = get_policy(cover_type)
        axis = policy.select_default_axis(None)
        assert axis.name == policy.axes[0].name


# ---------------------------------------------------------------------------
# position_for_intent — semantic intent → numeric axis value
# ---------------------------------------------------------------------------


class TestPositionForIntent:
    """``position_for_intent`` maps semantic intents to numeric values."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("cover_type", "sun_through_value", "sun_blocked_value"),
        [
            ("cover_blind", POSITION_OPEN, POSITION_CLOSED),
            ("cover_awning", POSITION_CLOSED, POSITION_OPEN),
            ("cover_tilt", POSITION_OPEN, POSITION_CLOSED),
            ("cover_venetian", POSITION_OPEN, POSITION_CLOSED),
        ],
    )
    def test_intent_map(self, cover_type, sun_through_value, sun_blocked_value):
        policy = get_policy(cover_type)
        assert policy.position_for_intent(sun_through=True) == sun_through_value
        assert policy.position_for_intent(sun_through=False) == sun_blocked_value


# ---------------------------------------------------------------------------
# read_axis_value — single source of truth for "current value on this axis"
# ---------------------------------------------------------------------------


def _hass_with_state(attributes: dict | None, *, state: str = "open") -> MagicMock:
    """Build a mock hass whose ``states.get`` returns one state object.

    ``attributes=None`` simulates an entity without any of the position
    attributes, which exercises the ``get_open_close_state`` fallback.
    """
    hass = MagicMock()
    state_obj = MagicMock()
    state_obj.state = state
    state_obj.attributes = attributes if attributes is not None else {}
    hass.states.get.return_value = state_obj
    return hass


class TestReadAxisValue:
    """``read_axis_value`` is the single source of truth for axis reads."""

    @pytest.mark.unit
    def test_blind_reads_current_position(self):
        hass = _hass_with_state({"current_position": 42})
        caps = {"has_set_position": True, "has_set_tilt_position": False}
        result = get_policy("cover_blind").read_axis_value(hass, "cover.blind", caps)
        assert result == 42

    @pytest.mark.unit
    def test_tilt_reads_current_tilt_position(self):
        hass = _hass_with_state({"current_tilt_position": 35})
        caps = {"has_set_position": False, "has_set_tilt_position": True}
        result = get_policy("cover_tilt").read_axis_value(hass, "cover.tilt", caps)
        assert result == 35

    @pytest.mark.unit
    def test_venetian_reads_current_position(self):
        # Venetian's primary axis is position (its tilt axis is dispatched
        # separately by the DualAxisSequencer), so read_axis_value returns the
        # position value here.
        hass = _hass_with_state({"current_position": 60, "current_tilt_position": 30})
        caps = {"has_set_position": True, "has_set_tilt_position": True}
        result = get_policy("cover_venetian").read_axis_value(
            hass, "cover.venetian", caps
        )
        assert result == 60

    @pytest.mark.unit
    def test_state_obj_overrides_hass_lookup(self):
        # When a state_obj is passed, read_axis_value reads its attributes
        # directly and does not consult ``hass.states`` (preserves the legacy
        # CoverCommandService behaviour where the freshly-arriving state event
        # is the source of truth).
        hass = _hass_with_state({"current_position": 1})  # would-be stale value
        state_obj = MagicMock()
        state_obj.attributes = {"current_position": 75}
        result = get_policy("cover_blind").read_axis_value(
            hass, "cover.blind", {"has_set_position": True}, state_obj=state_obj
        )
        assert result == 75

    @pytest.mark.unit
    def test_falls_back_to_open_close_when_axis_not_capable(self):
        # has_set_position=False → no axis attribute available → fall through
        # to ``get_open_close_state``, which derives a position from "open"/
        # "closed". The mock hass returns state="open" by default so the
        # helper returns POSITION_OPEN.
        hass = _hass_with_state({}, state="open")
        caps = {"has_set_position": False, "has_set_tilt_position": False}
        result = get_policy("cover_blind").read_axis_value(hass, "cover.simple", caps)
        assert result == POSITION_OPEN

    @pytest.mark.unit
    def test_tilt_only_fallback_routes_to_tilt(self):
        # has_set_position=False AND has_set_tilt_position=True flips the
        # blind's primary axis to tilt for this entity, so we read
        # ``current_tilt_position``.
        hass = _hass_with_state({"current_tilt_position": 25})
        caps = {"has_set_position": False, "has_set_tilt_position": True}
        result = get_policy("cover_blind").read_axis_value(hass, "cover.blind", caps)
        assert result == 25


# ---------------------------------------------------------------------------
# Regression guard for CODING_GUIDELINES.md "no hardcoded capability strings"
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_PRODUCTION_ROOT = _REPO_ROOT / "custom_components" / "adaptive_cover_pro"

# ``caps.get("has_X")`` is the banned form. ``caps.get(SOME_VAR)`` (where the
# argument is not a string literal — typically ``axis.capability_key``) is
# allowed. The pattern below matches exactly the banned shape.
_BANNED_CAPS_GET_RE = re.compile(r'caps\.get\(\s*"has_[a-z_]+"')


@pytest.mark.unit
def test_no_hardcoded_caps_get_strings_in_production() -> None:
    """Fail if any production module reintroduces a hardcoded ``caps.get("has_X")``.

    Use ``caps_get(caps, CAP_HAS_X)`` (or read off a ``CoverAxis.capability_key``)
    instead — see CODING_GUIDELINES.md "Cover Type Abstraction".
    """
    offenders: list[str] = []
    for path in _PRODUCTION_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _BANNED_CAPS_GET_RE.search(line):
                # Skip lines that are clearly comment/docstring (start with `#`
                # or contain triple-quote markers). The pattern still catches
                # genuine call sites because production code never starts a
                # call-expression line with a comment marker.
                stripped = line.strip()
                if stripped.startswith(("#", '"', "'")):
                    continue
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {stripped}")
    assert not offenders, (
        "Hardcoded caps.get('has_*') strings found — replace with "
        "caps_get(caps, CAP_HAS_*):\n  " + "\n  ".join(offenders)
    )
