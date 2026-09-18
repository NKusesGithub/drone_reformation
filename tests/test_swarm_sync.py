"""The "drone IDs from CrazySwarm" button: read crazyflies.yaml, write config.yaml."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from dashboard_service import swarm_sync

CRAZYFLIES = """\
# named list of all robots
fileversion: 3

robots:
  cf1:
    enabled: true
    uri: radio://0/80/2M/E7E7E7E701
    initial_position: [1.0, 0.5, 0]
    type: cf21

  cf2:
    enabled: true
    uri: radio://0/80/2M/E7E7E7E702
    initial_position: [0.0, 0.5, 0]
    type: cf21

  cf12:
    enabled: true
    uri: radio://0/80/2M/E7E7E7E712
    initial_position: [-1.0, 0.5, 0]
    type: cf21

  cf9:
    enabled: false
    uri: radio://0/80/2M/E7E7E7E709
    initial_position: [0.0, -1.0, 0]
    type: cf21

all:
  firmware_logging:
    enabled: true
"""

CONFIG = """\
drones:
  # Must match the IDs enabled in the CrazySwarm crazyflies.yaml file.
  ids: [1, 2, 3, 4, 5]
  mode: crazyswarm
  hover_z: 1.0

  vehicle_names:
    "1": cf1
    "2": cf2
    "3": cf3
    "4": cf4
    "5": cf5

mission:
  old_formation: [2, 3]
  formation_spacing: 0.5
"""


@pytest.fixture
def files(tmp_path, monkeypatch):
    crazyflies = tmp_path / "crazyflies.yaml"
    config = tmp_path / "config.yaml"
    crazyflies.write_text(CRAZYFLIES)
    config.write_text(CONFIG)
    monkeypatch.setattr(swarm_sync, "CRAZYFLIES_YAML", crazyflies)
    monkeypatch.setattr(swarm_sync, "CONFIG_YAML", config)
    monkeypatch.setattr(swarm_sync, "BACKUP_DIR", tmp_path / "config_backups")
    return {"crazyflies": crazyflies, "config": config, "backups": tmp_path / "config_backups"}


# --------------------------------------------------------------------------
# Suggested rows
# --------------------------------------------------------------------------


@pytest.mark.parametrize("count", range(1, 16))
def test_suggested_rows_always_widen_and_add_up(count):
    """A row that repeats or narrows can leave drones stuck mid-reformation
    (README_EXPLAINED 12.10), so a suggestion must never produce one."""
    rows = swarm_sync.suggest_formation(count)

    assert sum(rows) == count
    assert all(value >= 1 for value in rows)
    assert all(b > a for a, b in zip(rows, rows[1:])), rows


@pytest.mark.parametrize(
    "count,expected", [(1, [1]), (2, [2]), (3, [1, 2]), (4, [1, 3]), (5, [2, 3]), (9, [2, 3, 4])]
)
def test_suggested_rows_are_as_deep_as_they_can_be(count, expected):
    assert swarm_sync.suggest_formation(count) == expected


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------


def test_preview_reads_enabled_drones_only(files):
    plan = swarm_sync.preview()
    assert [d["name"] for d in plan["drones"]] == ["cf1", "cf2", "cf12"]


def test_drone_id_comes_from_the_radio_address(files):
    """The bridge reads the last two characters as hex, so cf12 is 18, not 12."""
    ids = {d["name"]: d["id"] for d in swarm_sync.preview()["drones"]}
    assert ids == {"cf1": 1, "cf2": 2, "cf12": 18}


def test_preview_does_not_write_anything(files):
    before = files["config"].read_text()
    plan = swarm_sync.preview()

    assert plan["changed"] is True
    assert files["config"].read_text() == before
    assert not files["backups"].exists()


def test_rows_are_suggested_when_the_drone_count_changed(files):
    plan = swarm_sync.preview()
    # 5 drones before, 3 now, so the old [2, 3] cannot stand.
    assert plan["proposed"]["formation"] == [1, 2]
    assert plan["proposed"]["formation_source"] == "suggested"


def test_rows_are_left_alone_when_they_still_fit(files):
    files["config"].write_text(CONFIG.replace("old_formation: [2, 3]", "old_formation: [1, 2]"))
    plan = swarm_sync.preview()

    assert plan["proposed"]["formation"] == [1, 2]
    assert plan["proposed"]["formation_source"] == "unchanged"


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------


def test_apply_writes_ids_names_and_rows(files):
    swarm_sync.apply()
    written = yaml.safe_load(files["config"].read_text())

    assert written["drones"]["ids"] == [1, 2, 18]
    # Keys stay quoted, as in config.example.yaml; the services do int(k) themselves.
    assert written["drones"]["vehicle_names"] == {"1": "cf1", "2": "cf2", "18": "cf12"}
    assert written["mission"]["old_formation"] == [1, 2]


def test_apply_keeps_comments_and_other_settings(files):
    swarm_sync.apply()
    text = files["config"].read_text()

    assert "# Must match the IDs enabled in the CrazySwarm crazyflies.yaml file." in text
    assert "formation_spacing: 0.5" in text
    assert "hover_z: 1.0" in text


def test_apply_saves_a_backup_of_the_old_file(files):
    swarm_sync.apply()
    backups = list(files["backups"].glob("config.yaml.*.bak"))

    assert len(backups) == 1
    assert backups[0].read_text() == CONFIG


def test_apply_never_touches_the_crazyswarm_repo(files):
    swarm_sync.apply()
    assert files["crazyflies"].read_text() == CRAZYFLIES


def test_applying_twice_is_a_no_op(files):
    swarm_sync.apply()
    second = swarm_sync.apply()

    assert second["changed"] is False
    assert second["backup"] is None
    assert len(list(files["backups"].glob("*.bak"))) == 1


def test_your_own_rows_are_accepted(files):
    swarm_sync.apply(formation=[3])
    assert yaml.safe_load(files["config"].read_text())["mission"]["old_formation"] == [3]


def test_rows_that_do_not_add_up_are_refused(files):
    before = files["config"].read_text()
    with pytest.raises(swarm_sync.SyncError, match="3 drones"):
        swarm_sync.apply(formation=[2, 3])

    assert files["config"].read_text() == before


def test_rows_that_narrow_are_allowed_but_warned_about(files):
    plan = swarm_sync.apply(formation=[2, 1])

    assert plan["warnings"]
    assert "stuck" in plan["warnings"][0]
    assert yaml.safe_load(files["config"].read_text())["mission"]["old_formation"] == [2, 1]


# --------------------------------------------------------------------------
# Failures the user can fix
# --------------------------------------------------------------------------


def test_a_missing_crazyflies_file_is_explained(files):
    files["crazyflies"].unlink()
    with pytest.raises(swarm_sync.SyncError, match="CRAZYFLIES_DIR"):
        swarm_sync.preview()


def test_no_enabled_drones_is_explained(files):
    files["crazyflies"].write_text(CRAZYFLIES.replace("enabled: true", "enabled: false"))
    with pytest.raises(swarm_sync.SyncError, match="no drones are enabled"):
        swarm_sync.preview()


def test_two_drones_sharing_an_id_is_explained(files):
    clash = CRAZYFLIES.replace("E7E7E7E712", "E7E7E7E702")
    files["crazyflies"].write_text(clash)
    with pytest.raises(swarm_sync.SyncError, match="share drone id"):
        swarm_sync.preview()


def test_a_config_without_an_ids_line_is_explained(files):
    files["config"].write_text(textwrap.dedent("""\
        drones:
          mode: crazyswarm
        mission:
          old_formation: [1, 2]
        """))
    with pytest.raises(swarm_sync.SyncError, match='no active "ids:" line'):
        swarm_sync.preview()
