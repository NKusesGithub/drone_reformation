"""drone_common.config: the loader every service depends on at import time."""

from __future__ import annotations

from pathlib import Path

import pytest

import drone_common.config as config_module
from drone_common.config import default_config_path, get_drone_ids, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_default_path_is_the_repo_root_config(monkeypatch):
    """The container layout mirrors the repo layout, so one expression has to
    resolve to /app/config.yaml in Docker and ./config.yaml on the host."""
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    assert default_config_path() == REPO_ROOT / "config.yaml"


def test_config_path_env_var_wins(monkeypatch, tmp_path):
    override = tmp_path / "elsewhere.yaml"
    override.write_text("drones:\n  ids: [7]\n")
    monkeypatch.setenv("CONFIG_PATH", str(override))

    assert default_config_path() == override
    assert get_drone_ids(load_config()) == [7]


def test_explicit_argument_beats_the_env_var(monkeypatch, tmp_path):
    override = tmp_path / "env.yaml"
    override.write_text("drones:\n  ids: [7]\n")
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("drones:\n  ids: [9]\n")
    monkeypatch.setenv("CONFIG_PATH", str(override))

    assert get_drone_ids(load_config(explicit)) == [9]


def test_a_named_file_that_is_missing_is_an_error(tmp_path):
    """A path someone typed and got wrong must fail loudly, or the service
    silently runs on its inline fallback values instead."""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "typo.yaml")


def test_the_default_file_may_be_absent(monkeypatch, tmp_path):
    """A bare checkout has no config.yaml, and `startup_all.sh --mock` still
    has to work there."""
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", tmp_path / "absent.yaml")
    assert load_config() == {}


def test_a_yaml_file_that_is_not_a_mapping_is_rejected(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- 1\n- 2\n")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_config(bad)


def test_an_empty_file_loads_as_empty_config(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert load_config(empty) == {}


def test_drone_ids_are_coerced_to_int(tmp_path):
    quoted = tmp_path / "quoted.yaml"
    quoted.write_text('drones:\n  ids: ["1", "2", "3"]\n')
    assert get_drone_ids(load_config(quoted)) == [1, 2, 3]


def test_drone_ids_fall_back_when_absent():
    assert get_drone_ids({}) == [1, 2, 3]


def test_the_suite_reads_the_fixture_not_your_local_config():
    """Guard against the fixture wiring silently breaking: the fixture has 5
    drones, config.example.yaml has 9."""
    assert get_drone_ids(load_config()) == [1, 2, 3, 4, 5]
