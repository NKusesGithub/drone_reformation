"""Docker 3 geometry: compact_rows() and make_slots().

These two functions decide the shape the survivors fly in, so they are the
highest-value pure functions in the stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from formation_service.app import FormationRequest, compact_rows, make_slots

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# compact_rows: how survivors are redistributed into rows
# --------------------------------------------------------------------------


def test_no_losses_leaves_the_formation_untouched():
    assert compact_rows([1, 2, 3, 2, 1], 0) == [1, 2, 3, 2, 1]


def test_survivors_fill_from_the_front():
    # 9 drones, 3 lost: the 6 survivors fill the front rows at full capacity
    # and the now-empty rear rows disappear.
    assert compact_rows([1, 2, 3, 2, 1], 3) == [1, 2, 3]


def test_partially_filled_row_is_the_last_one():
    # 9 drones, 4 lost: 5 survivors = 3 + 2, so the second row is short.
    assert compact_rows([3, 3, 3], 4) == [3, 2]


@pytest.mark.parametrize(
    "old_formation,downed",
    [
        ([1, 2, 3, 2, 1], 0),
        ([1, 2, 3, 2, 1], 1),
        ([1, 2, 3, 2, 1], 4),
        ([1, 2, 3, 2, 1], 8),
        ([3, 3, 3], 4),
        ([1], 0),
        ([5, 4, 3, 2, 1], 7),
    ],
)
def test_every_survivor_gets_a_row_slot(old_formation, downed):
    """The invariant that matters: no survivor is dropped, none invented."""
    rows = compact_rows(old_formation, downed)
    assert sum(rows) == sum(old_formation) - downed


@pytest.mark.parametrize(
    "old_formation,downed",
    [([1, 2, 3, 2, 1], 3), ([3, 3, 3], 4), ([5, 4, 3, 2, 1], 7)],
)
def test_no_row_exceeds_its_original_capacity(old_formation, downed):
    """Rows may shrink or vanish, but a row must never grow wider than it
    started, or the formation would be wider than the airspace allows."""
    rows = compact_rows(old_formation, downed)
    for row_index, count in enumerate(rows):
        assert count <= old_formation[row_index]


def test_losing_everything_yields_an_empty_formation():
    assert compact_rows([1, 2, 3, 2, 1], 9) == []


def test_losing_more_than_exist_is_rejected():
    with pytest.raises(ValueError, match="exceeds total drones"):
        compact_rows([1, 2, 3], 7)


# --------------------------------------------------------------------------
# make_slots: turning row counts into coordinates
# --------------------------------------------------------------------------


def test_one_slot_per_drone():
    rows = [1, 2, 3]
    assert len(make_slots(rows, 0.5)) == sum(rows)


def test_a_single_drone_row_sits_on_the_centre_line():
    slots = make_slots([1], 0.5)
    assert slots[0][0] == pytest.approx(0.0)


@pytest.mark.parametrize("rows", [[2], [3], [4], [1, 2, 3]])
def test_rows_are_centred_on_x_zero(rows):
    """Each row is symmetric about x=0, so the formation has no lateral drift
    as rows are added or removed."""
    slots = make_slots(rows, 0.5)
    start = 0
    for count in rows:
        xs = [x for x, _ in slots[start : start + count]]
        assert sum(xs) == pytest.approx(0.0)
        start += count


def test_rows_step_backward_by_exactly_one_spacing():
    spacing = 0.5
    slots = make_slots([1, 1, 1], spacing)
    ys = [y for _, y in slots]
    assert ys == pytest.approx([0.0, -spacing, -2 * spacing])


def test_neighbours_in_a_row_are_one_spacing_apart():
    spacing = 0.5
    slots = make_slots([3], spacing)
    xs = sorted(x for x, _ in slots)
    assert xs[1] - xs[0] == pytest.approx(spacing)
    assert xs[2] - xs[1] == pytest.approx(spacing)


def test_empty_formation_produces_no_slots():
    assert len(make_slots([], 0.5)) == 0


# --------------------------------------------------------------------------
# Defaults drift
# --------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known drift: the request-model fallbacks are still the pre-CrazySwarm "
        "AirSim-scale numbers (spacing 10.0 m, old_formation [1,3,4,3,2,1]) "
        "while the shipped config is metric (0.5 m, [1,2,3,2,1]). Harmless "
        "today only because mission always passes explicit values. Remove this "
        "marker when the defaults are reconciled."
    ),
)
def test_request_defaults_match_the_shipped_config():
    with (REPO_ROOT / "config.example.yaml").open() as handle:
        shipped = yaml.safe_load(handle)

    defaults = FormationRequest()
    assert defaults.spacing == shipped["mission"]["formation_spacing"]
    assert defaults.old_formation == shipped["mission"]["old_formation"]
