"""Editing config.yaml from the dashboard: comments survive, writes are checked."""

from __future__ import annotations

import pytest
import yaml

from dashboard_service import configio

CONFIG = """\
drones:
  # Must match the IDs enabled in the CrazySwarm crazyflies.yaml file.
  ids: [1, 2, 3]
  mode: crazyswarm

  # CrazySwarm uses positive Z above the floor.
  hover_z: 1.0
  takeoff_duration: 2.0
  group_mask: 0

  vehicle_names:
    "1": cf1
    "2": cf2
    "3": cf3

mission:
  old_formation: [1, 2]
  formation_spacing: 0.5
  safety_gap: 0.25
  waypoint_step: 0.25
  move_velocity: 0.5          # keep this slow indoors
  anchor_policy: initial_anchor
  include_downed_in_safety: false
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG)
    monkeypatch.setattr(configio, "CONFIG_YAML", path)
    monkeypatch.setattr(configio, "BACKUP_DIR", tmp_path / "config_backups")
    monkeypatch.setitem(configio.FILES["config"], "path", path)
    return path


def saved(path):
    return yaml.safe_load(path.read_text())


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def test_parameters_report_their_current_values(config):
    values = {p["id"]: p["value"] for p in configio.read_parameters()["parameters"]}

    assert values["drones.hover_z"] == "1.0"
    assert values["mission.move_velocity"] == "0.5"  # trailing comment stripped
    assert values["mission.anchor_policy"] == "initial_anchor"


def test_settings_absent_from_the_file_are_marked_not_present(config):
    by_id = {p["id"]: p for p in configio.read_parameters()["parameters"]}

    assert by_id["drones.hover_z"]["present"] is True
    assert by_id["mission.backward_penalty"]["present"] is False


def test_the_crazyswarm_file_is_offered_read_only():
    assert configio.FILES["crazyflies"]["editable"] is False
    assert configio.FILES["config"]["editable"] is True


# --------------------------------------------------------------------------
# Writing settings
# --------------------------------------------------------------------------


def test_saving_a_setting_changes_only_that_line(config):
    before = config.read_text().splitlines()
    configio.write_parameters([{"id": "drones.hover_z", "value": "1.4"}])
    after = config.read_text().splitlines()

    assert saved(config)["drones"]["hover_z"] == 1.4
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1


def test_comments_and_layout_survive(config):
    configio.write_parameters([{"id": "mission.safety_gap", "value": "0.3"}])
    text = config.read_text()

    assert "# Must match the IDs enabled in the CrazySwarm crazyflies.yaml file." in text
    assert "# CrazySwarm uses positive Z above the floor." in text
    assert "# keep this slow indoors" in text


def test_a_trailing_comment_on_the_edited_line_is_kept(config):
    configio.write_parameters([{"id": "mission.move_velocity", "value": "0.4"}])

    assert "move_velocity: 0.4          # keep this slow indoors" in config.read_text()
    assert saved(config)["mission"]["move_velocity"] == 0.4


def test_whole_numbers_stay_floats(config):
    """A bare 2 would load as an int; the services multiply these by floats."""
    configio.write_parameters([{"id": "drones.hover_z", "value": "2"}])

    assert "hover_z: 2.0" in config.read_text()
    assert isinstance(saved(config)["drones"]["hover_z"], float)


def test_an_int_setting_stays_an_int(config):
    configio.write_parameters([{"id": "drones.group_mask", "value": "1"}])
    assert "group_mask: 1\n" in config.read_text()


def test_a_choice_is_checked(config):
    with pytest.raises(configio.ConfigError, match="pick one of"):
        configio.write_parameters([{"id": "mission.anchor_policy", "value": "sideways"}])


def test_a_yes_no_setting_is_checked(config):
    configio.write_parameters([{"id": "mission.include_downed_in_safety", "value": "true"}])
    assert saved(config)["mission"]["include_downed_in_safety"] is True

    with pytest.raises(configio.ConfigError, match="true or false"):
        configio.write_parameters([{"id": "mission.include_downed_in_safety", "value": "maybe"}])


def test_text_where_a_number_belongs_is_refused(config):
    before = config.read_text()
    with pytest.raises(configio.ConfigError, match="not a number"):
        configio.write_parameters([{"id": "drones.hover_z", "value": "high"}])

    assert config.read_text() == before


def test_a_setting_that_is_not_in_the_file_says_so(config):
    with pytest.raises(configio.ConfigError, match="add the line by hand"):
        configio.write_parameters([{"id": "mission.backward_penalty", "value": "1.0"}])


def test_unknown_settings_are_refused(config):
    with pytest.raises(configio.ConfigError, match="unknown setting"):
        configio.write_parameters([{"id": "drones.rocket_fuel", "value": "9"}])


def test_a_dry_run_shows_the_diff_without_writing(config):
    before = config.read_text()
    result = configio.write_parameters([{"id": "drones.hover_z", "value": "1.9"}], dry_run=True)

    assert result["changed"] is True
    assert "hover_z" in result["diff"]
    assert result["backup"] is None
    assert config.read_text() == before


def test_a_backup_is_kept(config, tmp_path):
    configio.write_parameters([{"id": "drones.hover_z", "value": "1.2"}])
    backups = list((tmp_path / "config_backups").glob("config.yaml.*.bak"))

    assert len(backups) == 1
    assert backups[0].read_text() == CONFIG


# --------------------------------------------------------------------------
# Writing the whole file
# --------------------------------------------------------------------------


def test_raw_save_writes_and_backs_up(config, tmp_path):
    result = configio.write_raw(CONFIG.replace("hover_z: 1.0", "hover_z: 1.1"))

    assert result["changed"] is True
    assert saved(config)["drones"]["hover_z"] == 1.1
    assert list((tmp_path / "config_backups").glob("*.bak"))


def test_broken_yaml_is_refused(config):
    before = config.read_text()
    with pytest.raises(configio.ConfigError, match="not valid YAML"):
        configio.write_raw("drones:\n  ids: [1, 2\n")

    assert config.read_text() == before


def test_saving_the_same_text_changes_nothing(config, tmp_path):
    result = configio.write_raw(CONFIG)

    assert result["changed"] is False
    assert not (tmp_path / "config_backups").exists()


# --------------------------------------------------------------------------
# Warnings the stack does not make for itself
# --------------------------------------------------------------------------


def test_rows_that_do_not_match_the_drone_count_warn(config):
    result = configio.write_raw(CONFIG.replace("old_formation: [1, 2]", "old_formation: [1, 2, 3]"))
    assert any("spots" in w for w in result["warnings"])


def test_a_safety_gap_wider_than_the_spacing_warns(config):
    result = configio.write_raw(CONFIG.replace("safety_gap: 0.25", "safety_gap: 0.8"))
    assert any("wider than the spacing" in w for w in result["warnings"])


def test_a_hop_longer_than_the_safety_gap_warns(config):
    result = configio.write_raw(CONFIG.replace("waypoint_step: 0.25", "waypoint_step: 0.5"))
    assert any("longer than the safety gap" in w for w in result["warnings"])


def test_a_healthy_config_has_no_warnings(config):
    assert configio.read_file("config")["warnings"] == []
