"""Docker 4 helpers: collision checking and the idle/busy/down status model.

The status model is the core idea of the stack -- mission decides a drone is
lost purely from what Docker 1 reports -- so it is worth pinning down.
"""

from __future__ import annotations

import pytest

from mission_service.app import (
    _activity_status,
    _check_pairwise_safety,
    _detect_downed,
    _xy,
)

SAFETY_GAP = 0.25


# --------------------------------------------------------------------------
# Pairwise safety
# --------------------------------------------------------------------------


def test_well_separated_targets_are_safe():
    safe, reason = _check_pairwise_safety([(0.0, 0.0), (1.0, 0.0)], SAFETY_GAP)
    assert safe
    assert reason is None


def test_targets_closer_than_the_gap_are_rejected():
    safe, reason = _check_pairwise_safety([(0.0, 0.0), (0.1, 0.0)], SAFETY_GAP)
    assert not safe
    assert "violate safety gap" in reason


def test_the_gap_itself_is_allowed():
    """Boundary: the check is a strict `<`, so exactly one gap apart passes.
    Formation spacing is often an exact multiple of the gap, so an off-by-one
    here would reject legitimate formations."""
    safe, _ = _check_pairwise_safety([(0.0, 0.0), (SAFETY_GAP, 0.0)], SAFETY_GAP)
    assert safe


def test_the_violating_pair_is_named():
    _, reason = _check_pairwise_safety(
        [(0.0, 0.0), (5.0, 0.0), (5.05, 0.0)], SAFETY_GAP
    )
    assert "points 1 and 2" in reason


@pytest.mark.parametrize("points", [[], [(0.0, 0.0)]])
def test_nothing_to_collide_with_is_safe(points):
    safe, _ = _check_pairwise_safety(points, SAFETY_GAP)
    assert safe


# --------------------------------------------------------------------------
# Status model
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reported", ["idle", "busy", "down"])
def test_known_states_pass_through(reported):
    assert _activity_status({"status": reported}) == reported


def test_status_is_case_insensitive():
    assert _activity_status({"status": "BUSY"}) == "busy"
    assert _activity_status({"status": " Down "}) == "down"


def test_only_down_counts_as_lost():
    states = {
        1: {"status": "idle"},
        2: {"status": "down"},
        3: {"status": "busy"},
    }
    assert _detect_downed(states) == {2}


def test_an_unrecognised_status_is_treated_as_idle():
    """Fail safe rather than declaring a drone lost on a status we cannot
    parse -- a spurious 'down' would trigger a full reformation."""
    assert _activity_status({"status": "recalibrating"}) == "idle"


def test_legacy_flags_only_apply_when_status_is_unparseable():
    """Documents current behaviour, which is narrower than it looks.

    `_activity_status` falls back to the legacy `downed`/`landed` flags only
    when `status` is present but unrecognised. When `status` is absent the
    `.get("status", "idle")` default is itself accepted, so the fallback never
    runs. That is harmless today -- all three backends emit an explicit
    `status` -- but the fallback is effectively dead code.
    """
    assert _activity_status({"status": "???", "landed": True}) == "down"
    assert _activity_status({"downed": True}) == "idle"


# --------------------------------------------------------------------------
# Coordinate extraction
# --------------------------------------------------------------------------


def test_position_is_read_as_xy_only():
    """Altitude is held by Docker 1; mission plans strictly in the plane."""
    assert list(_xy({"x": 1.5, "y": -2.5, "z": 1.0})) == [1.5, -2.5]


def test_string_coordinates_are_coerced():
    assert list(_xy({"x": "1.5", "y": "-2.5"})) == [1.5, -2.5]
