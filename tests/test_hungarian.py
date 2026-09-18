"""Docker 2 assignment: which survivor flies to which slot."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from hungarian_service.app import AssignmentRequest, assign


def _assign(active_ids, old_positions, target_positions, **kwargs):
    return assign(
        AssignmentRequest(
            active_ids=active_ids,
            old_positions=old_positions,
            target_positions=target_positions,
            **kwargs,
        )
    )


def test_drones_already_on_target_do_not_move():
    result = _assign([1, 2], {1: (0.0, 0.0), 2: (1.0, 0.0)}, [(0.0, 0.0), (1.0, 0.0)])
    assert result["summary"]["total_travel_distance"] == pytest.approx(0.0)


def test_every_drone_gets_exactly_one_distinct_slot():
    result = _assign(
        [1, 2, 3],
        {1: (0.0, 0.0), 2: (1.0, 0.0), 3: (2.0, 0.0)},
        [(0.0, 1.0), (1.0, 1.0), (2.0, 1.0)],
    )
    assigned_drones = [item["drone_id"] for item in result["assignment"]]
    assigned_slots = [item["slot_idx"] for item in result["assignment"]]

    assert sorted(assigned_drones) == [1, 2, 3]
    assert sorted(assigned_slots) == [0, 1, 2]


def test_assignment_avoids_crossing_paths():
    """The whole point of the Hungarian solver: the cheap pairing, not the
    naive in-order one. Swapping these two would double the distance flown."""
    result = _assign([1, 2], {1: (0.0, 0.0), 2: (10.0, 0.0)}, [(10.0, 0.0), (0.0, 0.0)])
    chosen = {item["drone_id"]: item["slot_idx"] for item in result["assignment"]}

    assert chosen == {1: 1, 2: 0}
    assert result["summary"]["total_travel_distance"] == pytest.approx(0.0)


def test_front_drones_are_ranked_to_move_first():
    """Cascade order is front-to-back (larger y first) so a drone never flies
    into a slot that the drone ahead of it has not vacated yet."""
    result = _assign(
        [1, 2, 3],
        {1: (0.0, -1.0), 2: (0.0, 1.0), 3: (0.0, 0.0)},
        [(0.0, -1.0), (0.0, 1.0), (0.0, 0.0)],
    )
    order = [item["drone_id"] for item in result["assignment"]]
    ranks = [item["cascade_rank"] for item in result["assignment"]]

    assert order == [2, 3, 1]
    assert ranks == [1, 2, 3]


def test_spare_slots_are_allowed():
    """Formation may hand back more slots than there are survivors; the extras
    are simply left empty."""
    result = _assign([1], {1: (0.0, 0.0)}, [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    assert len(result["assignment"]) == 1


def test_unknown_drone_position_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _assign([1, 2], {1: (0.0, 0.0)}, [(0.0, 0.0), (1.0, 1.0)])

    assert exc.value.status_code == 400
    assert "Missing old_positions" in exc.value.detail


def test_too_few_slots_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _assign([1, 2], {1: (0.0, 0.0), 2: (1.0, 0.0)}, [(0.0, 0.0)])

    assert exc.value.status_code == 400
    assert "Need at least 2 target positions" in exc.value.detail


def test_backward_penalty_steers_a_drone_to_a_forward_slot():
    """The penalty only has room to act when there are spare slots to choose
    between -- if every slot must be filled, someone has to take the rear one
    no matter how it is priced.

    Slot 0 sits just behind the drone, slot 1 well ahead. Distance alone picks
    the near one; a large backward penalty should outweigh the longer flight.
    """
    positions = {1: (0.0, 0.0)}
    targets = [(0.0, -0.5), (0.0, 3.0)]

    # forward_jump_penalty is zeroed so the two penalties cannot mask one another.
    without = _assign([1], positions, targets, forward_jump_penalty=0.0)
    with_penalty = _assign(
        [1],
        positions,
        targets,
        forward_jump_penalty=0.0,
        backward_penalty=1000.0,
        backward_threshold=0.0,
    )

    assert without["assignment"][0]["slot_idx"] == 0
    assert with_penalty["assignment"][0]["slot_idx"] == 1
