"""Unit tests for ``DualAxisSequencer``.

The sequencer owns:
- the venetian tilt-axis suppression window (``stamp_position_command`` /
  ``is_in_suppression``), and
- the post-position settle loop + ``set_cover_tilt_position`` call
  (``run_sequence``).

These tests exercise it in isolation — the integration with
``CoverCommandService.apply_position`` is covered in
``tests/test_cover_command_venetian.py``.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.adaptive_cover_pro.const import (
    VENETIAN_TILT_SUPPRESSION_SECONDS,
)
from custom_components.adaptive_cover_pro.diagnostics.event_buffer import EventBuffer
from custom_components.adaptive_cover_pro.managers.dual_axis_sequencer import (
    DualAxisSequencer,
)


@pytest.fixture(autouse=True)
def _zero_post_tilt_delay(monkeypatch):
    """Skip the 1.5s real-motor settle delay in unit tests."""
    monkeypatch.setattr(
        "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer."
        "VENETIAN_POST_TILT_REBASE_DELAY_SECONDS",
        0,
    )


def _build_sequencer(
    *,
    current_positions=None,
    dry_run=False,
    set_commanded_position=None,
    get_state=None,
    get_current_tilt_position=None,
    event_buffer=None,
    invert_tilt=None,
    get_min_change=None,
):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    if current_positions is None:
        current_positions = []
    iter_positions = iter(current_positions)
    if set_commanded_position is None:
        set_commanded_position = lambda *_: None  # noqa: E731
    return (
        hass,
        DualAxisSequencer(
            hass=hass,
            logger=MagicMock(),
            grace_mgr=MagicMock(),
            get_current_position=lambda _eid: next(iter_positions, None),
            set_commanded_position=set_commanded_position,
            position_tolerance=5,
            is_dry_run=lambda: dry_run,
            get_state=get_state,
            get_current_tilt_position=get_current_tilt_position,
            event_buffer=event_buffer,
            invert_tilt=invert_tilt,
            get_min_change=get_min_change,
        ),
    )


@pytest.mark.unit
class TestSuppressionWindow:
    """``stamp_position_command`` and ``is_in_suppression`` mediate the back-rotate window."""

    def test_no_stamp_means_not_suppressed(self):
        _, seq = _build_sequencer()
        assert seq.is_in_suppression("cover.x") is False

    def test_fresh_stamp_is_suppressed(self):
        _, seq = _build_sequencer()
        seq.stamp_position_command("cover.x")
        assert seq.is_in_suppression("cover.x") is True

    def test_stale_stamp_expires(self):
        _, seq = _build_sequencer()
        seq._suppression_at["cover.x"] = dt.datetime.now(dt.UTC) - dt.timedelta(
            seconds=VENETIAN_TILT_SUPPRESSION_SECONDS + 1
        )
        assert seq.is_in_suppression("cover.x") is False


@pytest.mark.asyncio
class TestSettleAndTilt:
    """Settle-loop and tilt-service-call branches of ``run_sequence``."""

    async def test_settle_returns_when_target_reached(self):
        # Sequence: 80 (off-target), 50 (within 5%-tolerance) → reached.
        _, seq = _build_sequencer(current_positions=[80, 50])
        reached, last = await seq._wait_for_position_settle("cover.x", target=50)
        assert reached is True
        assert last == 50

    async def test_settle_bails_on_unavailable(self):
        _, seq = _build_sequencer(current_positions=[None])
        reached, last = await seq._wait_for_position_settle("cover.x", target=50)
        assert reached is False
        assert last is None

    async def test_run_sequence_emits_tilt_after_settle(self):
        hass, seq = _build_sequencer(current_positions=[60])
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        called = hass.services.async_call.call_args.args
        assert called[1] == "set_cover_tilt_position"
        assert called[2]["tilt_position"] == 80

    async def test_run_sequence_records_last_tilt_target(self):
        _, seq = _build_sequencer()
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_dry_run_skips_service_call(self):
        hass, seq = _build_sequencer(dry_run=True)
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 60))
        await seq.run_sequence(
            "cover.x", position_target=60, tilt_target=80, reason="solar"
        )
        assert hass.services.async_call.call_count == 0


@pytest.mark.asyncio
class TestPostTiltRebase:
    """After a successful tilt command, the commanded position is rebased to the
    actual post-tilt position so reconciliation sees zero drift.
    """

    async def test_rebases_commanded_position_to_actual_post_tilt(self):
        """After tilt, set_commanded_position is called with the actual position."""
        set_cmd_pos = MagicMock()
        # position_target=50, post-tilt actual=56 → |delta|=6 > tolerance(5).
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        seq._get_current_position = lambda _eid: 56
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_called_once_with("cover.x", 56)

    async def test_does_not_rebase_when_post_tilt_position_none(self):
        """If current_position is unavailable after tilt, skip the rebase."""
        set_cmd_pos = MagicMock()
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        seq._get_current_position = lambda _eid: None
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()

    async def test_does_not_rebase_when_drift_within_tolerance(self):
        """Drift of 2% (≤ tolerance of 5%) should not trigger a rebase."""
        set_cmd_pos = MagicMock()
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        # position_target=50, actual=52 → |delta|=2 ≤ 5
        seq._get_current_position = lambda _eid: 52
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()

    async def test_rebase_reads_position_after_post_tilt_delay(self, monkeypatch):
        """A delay must occur between the tilt service call and the position rebase.

        Without this delay the rebase reads current_position immediately after
        set_cover_tilt_position returns. For async motors (Shelly/KNX/Somfy) the
        mechanical back-drive happens AFTER the service call returns, so the
        immediate read sees the pre-back-drive value and the rebase is skipped.
        The fix is asyncio.sleep(VENETIAN_POST_TILT_REBASE_DELAY_SECONDS) between
        the tilt call and the rebase so the motor has time to settle first.
        """
        sleep_calls: list[float] = []

        async def _capture_sleep(delay):
            sleep_calls.append(delay)

        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer.asyncio.sleep",
            _capture_sleep,
        )

        set_cmd_pos = MagicMock()
        _, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        seq._get_current_position = lambda _eid: 56
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))

        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )

        assert sleep_calls, (
            "asyncio.sleep was not called after the tilt service call — "
            "post-tilt rebase delay is missing"
        )

    async def test_does_not_rebase_when_tilt_service_fails(self):
        """If the tilt service call raises, rebase must not run."""
        from homeassistant.exceptions import HomeAssistantError

        set_cmd_pos = MagicMock()
        hass, seq = _build_sequencer(set_commanded_position=set_cmd_pos)
        hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("tilt fail")
        )
        seq._wait_for_position_settle = AsyncMock(return_value=(True, 50))
        await seq.run_sequence(
            "cover.x", position_target=50, tilt_target=80, reason="solar"
        )
        set_cmd_pos.assert_not_called()


@pytest.mark.asyncio
class TestSendTiltCommand:
    """``_send_tilt_command`` is the shared tilt-emission body used by both
    ``run_sequence`` and ``update_tilt_only``.
    """

    async def test_emits_tilt_service_call(self):
        hass, seq = _build_sequencer()
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        call = hass.services.async_call.call_args.args
        assert call[1] == "set_cover_tilt_position"
        assert call[2]["tilt_position"] == 80

    async def test_records_last_tilt_target(self):
        _, seq = _build_sequencer()
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_dry_run_skips_service_call(self):
        hass, seq = _build_sequencer(dry_run=True)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert hass.services.async_call.call_count == 0


@pytest.mark.asyncio
class TestUpdateTiltOnly:
    """``update_tilt_only`` emits tilt without a settle wait."""

    async def test_emits_tilt_without_settle_wait(self):
        hass, seq = _build_sequencer()
        seq._wait_for_position_settle = AsyncMock()
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=40, reason="solar"
        )
        seq._wait_for_position_settle.assert_not_awaited()
        assert hass.services.async_call.call_count == 1
        assert hass.services.async_call.call_args.args[1] == "set_cover_tilt_position"

    async def test_stamps_suppression_after_send(self):
        _, seq = _build_sequencer()
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=40, reason="solar"
        )
        assert seq.is_in_suppression("cover.x") is True

    async def test_short_circuits_when_target_unchanged(self):
        hass, seq = _build_sequencer()
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=40, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        # Same target — must not fire again.
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=42, reason="solar"
        )
        assert hass.services.async_call.call_count == 1

    async def test_emits_when_target_changes(self):
        hass, seq = _build_sequencer()
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=40, reason="solar"
        )
        await seq.update_tilt_only(
            "cover.x", tilt_target=85, current_position=40, reason="solar"
        )
        assert hass.services.async_call.call_count == 2


@pytest.mark.asyncio
class TestSettleStateAware:
    """_wait_for_position_settle must not declare stall while cover.state is moving."""

    async def test_settle_does_not_fire_while_state_is_closing(self, monkeypatch):
        """Stall counter must stay at zero while state=closing, regardless of position."""
        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer"
            ".VENETIAN_POSITION_SETTLE_POLL_SECONDS",
            0,
        )
        # State: closing for 5 polls, then open for 3 → stall fires on poll 8.
        state_seq = iter(
            [
                "closing",
                "closing",
                "closing",
                "closing",
                "closing",
                "open",
                "open",
                "open",
            ]
        )
        calls = [0]

        def get_pos(_eid):
            calls[0] += 1
            return 40

        _, seq = _build_sequencer(get_state=lambda _eid: next(state_seq, "open"))
        seq._get_current_position = get_pos

        reached, last = await seq._wait_for_position_settle("cover.x", target=10)

        assert reached is False
        assert last == 40
        # Pre-fix bug returns after 4 polls; fix must poll at least 6.
        assert calls[0] >= 6

    async def test_settle_does_not_fire_while_state_is_opening(self, monkeypatch):
        """Same as closing test — opening state must also suppress the stall counter."""
        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer"
            ".VENETIAN_POSITION_SETTLE_POLL_SECONDS",
            0,
        )
        state_seq = iter(
            [
                "opening",
                "opening",
                "opening",
                "opening",
                "opening",
                "open",
                "open",
                "open",
            ]
        )
        calls = [0]

        def get_pos(_eid):
            calls[0] += 1
            return 40

        _, seq = _build_sequencer(get_state=lambda _eid: next(state_seq, "open"))
        seq._get_current_position = get_pos

        reached, last = await seq._wait_for_position_settle("cover.x", target=10)

        assert reached is False
        assert calls[0] >= 6

    async def test_settle_resets_unchanged_counter_when_motion_resumes(
        self, monkeypatch
    ):
        """Stall counter must reset if state becomes moving mid-sequence."""
        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer"
            ".VENETIAN_POSITION_SETTLE_POLL_SECONDS",
            0,
        )
        # open→open→closing→closing→open→open→open: counter resets on polls 3-4.
        state_seq = iter(["open", "open", "closing", "closing", "open", "open", "open"])
        calls = [0]

        def get_pos(_eid):
            calls[0] += 1
            return 40

        _, seq = _build_sequencer(get_state=lambda _eid: next(state_seq, "open"))
        seq._get_current_position = get_pos

        reached, last = await seq._wait_for_position_settle("cover.x", target=10)

        assert reached is False
        # Without fix: returns after poll 4 (3 unchanged). With fix: 7 polls.
        assert calls[0] >= 6

    async def test_settle_unchanged_samples_only_count_when_stationary(
        self, monkeypatch
    ):
        """When state is always open, the existing 3-sample stall still fires."""
        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer"
            ".VENETIAN_POSITION_SETTLE_POLL_SECONDS",
            0,
        )
        state_seq = iter(["open", "open", "open", "open", "open"])
        calls = [0]

        def get_pos(_eid):
            calls[0] += 1
            return 40

        _, seq = _build_sequencer(get_state=lambda _eid: next(state_seq, "open"))
        seq._get_current_position = get_pos

        reached, last = await seq._wait_for_position_settle("cover.x", target=10)

        assert reached is False
        # poll 1: last=None → reset; poll 2-4: unchanged 1-3 → stall at poll 4.
        assert calls[0] == 4

    async def test_settle_falls_back_when_no_get_state(self, monkeypatch):
        """No get_state injected → behaves identically to pre-fix code (stall at 3)."""
        monkeypatch.setattr(
            "custom_components.adaptive_cover_pro.managers.dual_axis_sequencer"
            ".VENETIAN_POSITION_SETTLE_POLL_SECONDS",
            0,
        )
        calls = [0]

        def get_pos(_eid):
            calls[0] += 1
            return 40

        _, seq = _build_sequencer()  # no get_state
        seq._get_current_position = get_pos

        reached, last = await seq._wait_for_position_settle("cover.x", target=10)

        assert reached is False
        assert calls[0] == 4


@pytest.mark.asyncio
class TestTiltVerification:
    """After _send_tilt_command, the recorded target is cleared if tilt didn't land."""

    async def test_clears_tilt_target_when_actual_drifts_beyond_tolerance(self):
        """Tilt sent to 80 but cover reads back 0: target must be cleared."""
        _, seq = _build_sequencer(get_current_tilt_position=lambda _eid: 0)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        # |0 - 80| = 80 > VENETIAN_TILT_VERIFY_TOLERANCE → cleared
        assert seq.last_tilt_target("cover.x") is None

    async def test_keeps_tilt_target_when_actual_within_tolerance(self):
        """Tilt sent to 80, reads back 78: within 5% tolerance → keep target."""
        _, seq = _build_sequencer(get_current_tilt_position=lambda _eid: 78)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        # |78 - 80| = 2 <= 5 → keep
        assert seq.last_tilt_target("cover.x") == 80

    async def test_keeps_tilt_target_when_tilt_position_unknown(self):
        """Cannot read actual tilt (None) → fail-open: keep target to avoid retry storms."""
        _, seq = _build_sequencer(get_current_tilt_position=lambda _eid: None)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_update_tilt_only_retries_after_drift_clears_target(self):
        """update_tilt_only must resend when the recorded target was cleared by drift."""
        hass, seq = _build_sequencer(get_current_tilt_position=lambda _eid: 0)
        # First send: drift clears the target.
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") is None
        assert hass.services.async_call.call_count == 1
        # Same target via update_tilt_only: short-circuit compares against None → resends.
        await seq.update_tilt_only(
            "cover.x", tilt_target=80, current_position=60, reason="solar"
        )
        assert hass.services.async_call.call_count == 2


@pytest.mark.asyncio
class TestTiltDiagnosticEvents:
    """DualAxisSequencer emits EventBuffer entries for every tilt command outcome."""

    async def test_tilt_command_sent_event_recorded(self):
        buf = EventBuffer(maxlen=16)
        _, seq = _build_sequencer(event_buffer=buf)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        sent = [e for e in buf.snapshot() if e["event"] == "tilt_command_sent"]
        assert len(sent) == 1
        ev = sent[0]
        assert ev["entity_id"] == "cover.x"
        assert ev["tilt_position"] == 80
        assert ev["position_target"] == 60
        assert ev["trigger"] == "solar"
        assert "ts" in ev

    async def test_tilt_command_skipped_on_dry_run(self):
        buf = EventBuffer(maxlen=16)
        _, seq = _build_sequencer(dry_run=True, event_buffer=buf)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        skipped = [e for e in buf.snapshot() if e["event"] == "tilt_command_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "dry_run"
        assert skipped[0]["entity_id"] == "cover.x"
        assert skipped[0]["tilt_position"] == 80
        assert "ts" in skipped[0]

    async def test_tilt_command_skipped_on_short_circuit(self):
        buf = EventBuffer(maxlen=16)
        hass, seq = _build_sequencer(event_buffer=buf)
        # First call actually sends.
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=40, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        # Replace buffer to isolate the second call's events.
        buf2 = EventBuffer(maxlen=16)
        seq._event_buffer = buf2
        # Second call with same target → short-circuit.
        await seq.update_tilt_only(
            "cover.x", tilt_target=70, current_position=42, reason="solar"
        )
        assert hass.services.async_call.call_count == 1
        skipped = [e for e in buf2.snapshot() if e["event"] == "tilt_command_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "target_unchanged"
        assert skipped[0]["tilt_position"] == 70
        assert skipped[0]["current_position"] == 42
        assert "ts" in skipped[0]

    async def test_tilt_command_verified_event(self):
        buf = EventBuffer(maxlen=16)
        _, seq = _build_sequencer(
            get_current_tilt_position=lambda _eid: 78,
            event_buffer=buf,
        )
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        verified = [e for e in buf.snapshot() if e["event"] == "tilt_command_verified"]
        assert len(verified) == 1
        ev = verified[0]
        assert ev["entity_id"] == "cover.x"
        assert ev["tilt_target"] == 80
        assert ev["actual_tilt_position"] == 78
        assert ev["delta"] == 2
        assert "ts" in ev

    async def test_tilt_command_drift_event(self):
        buf = EventBuffer(maxlen=16)
        _, seq = _build_sequencer(
            get_current_tilt_position=lambda _eid: 0,
            event_buffer=buf,
        )
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        drift = [e for e in buf.snapshot() if e["event"] == "tilt_command_drift"]
        assert len(drift) == 1
        ev = drift[0]
        assert ev["entity_id"] == "cover.x"
        assert ev["tilt_target"] == 80
        assert ev["actual_tilt_position"] == 0
        assert ev["delta"] == 80
        assert "ts" in ev

    async def test_no_verify_event_when_tilt_position_unknown(self):
        buf = EventBuffer(maxlen=16)
        _, seq = _build_sequencer(
            get_current_tilt_position=lambda _eid: None,
            event_buffer=buf,
        )
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        verify_events = [
            e
            for e in buf.snapshot()
            if e["event"] in ("tilt_command_verified", "tilt_command_drift")
        ]
        assert len(verify_events) == 0


@pytest.mark.asyncio
class TestTiltInversion:
    """_send_tilt_command applies optional tilt-axis inversion before sending."""

    async def test_inverts_wire_value_when_invert_tilt_is_true(self):
        """With invert_tilt=True, wire value sent must be 100 - tilt_target."""
        hass, seq = _build_sequencer(invert_tilt=lambda: True)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        wire = hass.services.async_call.call_args.args[2]["tilt_position"]
        assert wire == 20  # 100 - 80

    async def test_passes_target_through_when_invert_tilt_is_false(self):
        """With invert_tilt=False, wire value must equal tilt_target unchanged."""
        hass, seq = _build_sequencer(invert_tilt=lambda: False)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        wire = hass.services.async_call.call_args.args[2]["tilt_position"]
        assert wire == 80

    async def test_recorded_tilt_target_stays_logical(self):
        """last_tilt_target must store the logical (user-facing) value, not the wire value."""
        _, seq = _build_sequencer(invert_tilt=lambda: True)
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_invert_tilt_callable_evaluated_per_call(self):
        """Callable must be evaluated on each send so runtime option changes take effect."""
        inverted = [True]
        hass, seq = _build_sequencer(invert_tilt=lambda: inverted[0])
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        first_wire = hass.services.async_call.call_args_list[-1].args[2][
            "tilt_position"
        ]
        assert first_wire == 20

        inverted[0] = False
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        second_wire = hass.services.async_call.call_args_list[-1].args[2][
            "tilt_position"
        ]
        assert second_wire == 80

    async def test_verify_keeps_target_when_wire_actual_matches_inverted_target(self):
        """Verification must compare in logical space: wire=20 → logical=80, matches tilt_target=80."""
        _, seq = _build_sequencer(
            invert_tilt=lambda: True,
            get_current_tilt_position=lambda _eid: 20,
        )
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") == 80

    async def test_verify_detects_drift_in_logical_space_when_inverted(self):
        """Wire=80 → logical=20 when inverted; delta against tilt_target=80 is 60 → drift."""
        _, seq = _build_sequencer(
            invert_tilt=lambda: True,
            get_current_tilt_position=lambda _eid: 80,
        )
        await seq._send_tilt_command(
            "cover.x", tilt_target=80, position_target=60, reason="solar"
        )
        assert seq.last_tilt_target("cover.x") is None


@pytest.mark.asyncio
class TestTiltDeltaGate:
    """Tilt commands must respect the configured min-change threshold."""

    async def test_below_min_change_skips_service_call(self):
        """When tilt delta is below min_change, no service call is made and a skip event is emitted."""
        from custom_components.adaptive_cover_pro.diagnostics.event_buffer import (
            EventBuffer,
        )

        buf = EventBuffer(maxlen=20)
        hass, seq = _build_sequencer(get_min_change=lambda: 8, event_buffer=buf)
        seq._tilt_targets["cover.x"] = 50

        await seq._send_tilt_command(
            "cover.x", tilt_target=53, position_target=60, reason="solar"
        )

        assert hass.services.async_call.call_count == 0
        events = buf.snapshot()
        assert len(events) == 1
        assert events[0]["event"] == "tilt_command_skipped"
        assert events[0]["reason"] == "delta_too_small"

    async def test_at_or_above_min_change_emits_service_call(self):
        """When tilt delta meets min_change, the tilt service call fires."""
        hass, seq = _build_sequencer(get_min_change=lambda: 8)
        seq._tilt_targets["cover.x"] = 50

        await seq._send_tilt_command(
            "cover.x", tilt_target=58, position_target=60, reason="solar"
        )

        assert hass.services.async_call.call_count == 1

    async def test_first_cycle_bypasses_gate(self):
        """With no prior tilt target, the gate is bypassed (first-cycle send)."""
        hass, seq = _build_sequencer(get_min_change=lambda: 50)
        # No seed in _tilt_targets — simulates first cycle

        await seq._send_tilt_command(
            "cover.x", tilt_target=10, position_target=60, reason="solar"
        )

        assert hass.services.async_call.call_count == 1

    async def test_force_kwarg_bypasses_gate(self):
        """force=True bypasses the delta gate regardless of delta size."""
        hass, seq = _build_sequencer(get_min_change=lambda: 50)
        seq._tilt_targets["cover.x"] = 50

        await seq._send_tilt_command(
            "cover.x", tilt_target=51, position_target=60, reason="solar", force=True
        )

        assert hass.services.async_call.call_count == 1

    async def test_default_min_change_one_is_permissive(self):
        """Without get_min_change, any delta ≥ 1 sends — gate is permissive by default."""
        hass, seq = _build_sequencer()  # no get_min_change
        seq._tilt_targets["cover.x"] = 50

        await seq._send_tilt_command(
            "cover.x", tilt_target=51, position_target=60, reason="solar"
        )

        assert hass.services.async_call.call_count == 1
