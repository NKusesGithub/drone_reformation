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


# --------------------------------------------------------------------------
# front_axis: which way the formation faces
# --------------------------------------------------------------------------


def test_front_drones_are_ranked_to_move_first_along_x():
    """The cascade follows front_axis: with '+x' the drone at the largest x
    is the one that must vacate its slot first."""
    result = _assign(
        [1, 2, 3],
        {1: (-1.0, 0.0), 2: (1.0, 0.0), 3: (0.0, 0.0)},
        [(-1.0, 0.0), (1.0, 0.0), (0.0, 0.0)],
        front_axis="+x",
    )

    assert [item["drone_id"] for item in result["assignment"]] == [2, 3, 1]
    assert [item["cascade_rank"] for item in result["assignment"]] == [1, 2, 3]


def test_a_long_forward_jump_along_x_is_penalised():
    """The rear-drone-jumps-to-the-front case, turned a quarter turn. Slot 0 is
    3 m ahead and slot 1 is 5 m behind, so distance alone takes the front slot;
    the forward-jump penalty has to be the thing that sends it to the rear."""
    positions = {1: (-3.0, 0.0)}
    targets = [(0.0, 0.0), (-8.0, 0.0)]

    free = _assign([1], positions, targets, front_axis="+x", forward_jump_penalty=0.0)
    penalised = _assign(
        [1],
        positions,
        targets,
        front_axis="+x",
        spacing=0.5,
        forward_jump_penalty=1000.0,
    )

    assert free["assignment"][0]["slot_idx"] == 0
    assert penalised["assignment"][0]["slot_idx"] == 1
    assert penalised["assignment"][0]["delta_front"] == pytest.approx(-5.0)


def test_the_front_axis_only_changes_which_axis_is_forward():
    """The +x answer is the +y answer with every coordinate swapped."""
    kwargs = {"spacing": 0.5, "forward_jump_penalty": 1000.0}
    on_y = _assign(
        [1, 2],
        {1: (0.0, -3.0), 2: (0.0, 0.0)},
        [(0.0, 0.0), (0.0, -8.0)],
        front_axis="+y",
        **kwargs,
    )
    on_x = _assign(
        [1, 2],
        {1: (-3.0, 0.0), 2: (0.0, 0.0)},
        [(0.0, 0.0), (-8.0, 0.0)],
        front_axis="+x",
        **kwargs,
    )

    assert [item["slot_idx"] for item in on_y["assignment"]] == [
        item["slot_idx"] for item in on_x["assignment"]
    ]
    assert [item["cascade_rank"] for item in on_y["assignment"]] == [
        item["cascade_rank"] for item in on_x["assignment"]
    ]


def test_the_backward_penalty_follows_the_front_axis():
    positions = {1: (0.0, 0.0)}
    targets = [(-0.5, 0.0), (3.0, 0.0)]

    without = _assign([1], positions, targets, front_axis="+x", forward_jump_penalty=0.0)
    with_penalty = _assign(
        [1],
        positions,
        targets,
        front_axis="+x",
        forward_jump_penalty=0.0,
        backward_penalty=1000.0,
        backward_threshold=0.0,
    )

    assert without["assignment"][0]["slot_idx"] == 0
    assert with_penalty["assignment"][0]["slot_idx"] == 1


def test_the_default_front_axis_is_plus_y():
    result = _assign([1], {1: (0.0, 0.0)}, [(1.0, 2.0)])

    assert result["front_axis"] == "+y"
    assert result["assignment"][0]["delta_front"] == pytest.approx(2.0)


def test_an_unknown_front_axis_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _assign([1], {1: (0.0, 0.0)}, [(0.0, 0.0)], front_axis="+z")

    assert exc.value.status_code == 400
    assert "front_axis" in exc.value.detail
