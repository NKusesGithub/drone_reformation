"""Stack page: the commands it would run, and reading `docker compose ps`."""

from __future__ import annotations

import json

import pytest

from dashboard_service import stack


def test_start_defaults_never_take_off_and_leave_out_the_dashboard():
    argv = stack.start_argv({})
    assert argv[:2] == ["env", "MISSION_AUTO_START=0"]
    assert "./scripts/startup_all.sh" in argv
    assert "--no-dashboard" in argv
    assert "--crazyswarm" in argv
    assert "--no-build" not in argv


def test_start_options_map_to_script_flags():
    argv = stack.start_argv({"mode": "mock", "auto_start": "1", "build": "False",
                             "visualizer": "True"})
    assert argv[1] == "MISSION_AUTO_START=1"
    assert {"--mock", "--no-build", "--with-visualizer"} <= set(argv)


@pytest.mark.parametrize("values", [{"mode": "rm -rf /"}, {"auto_start": "yes"}])
def test_start_rejects_anything_outside_the_choices(values):
    with pytest.raises(stack.StackError):
        stack.start_argv(values)


def test_stop_lands_unless_told_not_to():
    assert stack.stop_argv({}) == ["./scripts/shutdown_all.sh"]
    assert stack.stop_argv({"land": "False"}) == ["./scripts/shutdown_all.sh", "--no-land"]


def test_ps_parses_both_compose_output_formats():
    row = {"Service": "mission", "Name": "m-1", "State": "running", "Status": "Up 5s",
           "Health": "", "Publishers": [{"URL": "0.0.0.0", "PublishedPort": 8004, "TargetPort": 8000},
                                        {"URL": "", "PublishedPort": 0, "TargetPort": 9}]}
    lines = stack._parse_ps(json.dumps(row) + "\n")
    array = stack._parse_ps(json.dumps([row]))
    assert lines == array
    assert lines[0]["Ports"] == "0.0.0.0:8004->8000"
    assert stack._parse_ps("") == []


def test_env_shows_only_known_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# c\nDRONE_MODE=mock\nCRAZYSWARM_API_KEY=secret\nMISSION_AUTO_START='0'\n")
    monkeypatch.setattr(stack, "ENV_FILE", env)
    assert stack.read_env() == {"DRONE_MODE": "mock", "MISSION_AUTO_START": "0"}


def test_bridge_port_follows_the_env_url(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(stack, "ENV_FILE", env)
    env.write_text("CRAZYSWARM_API_URL=http://127.0.0.1:8123\n")
    assert stack.bridge_port() == 8123
    env.write_text("CRAZYSWARM_API_URL=http://localhost\n")
    assert stack.bridge_port() == 8011
    env.write_text("")
    assert stack.bridge_port() == 8011


def test_bridge_command_is_the_readme_one(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(stack, "CRAZYSWARM_REPO", tmp_path / "ws dir")
    argv = stack.bridge_argv()
    assert argv[:5] == ["env", "-u", "PYTHONPATH", "bash", "-c"]
    script = argv[5]
    assert f"source '{tmp_path}/ws dir'/install/setup.bash" in script
    assert "exec /usr/bin/python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8011" in script


def test_bridge_refuses_to_start_when_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(stack, "CRAZYSWARM_REPO", tmp_path)
    monkeypatch.setattr(stack, "_listener_pid", lambda port: None)
    with pytest.raises(stack.StackError, match="not installed"):
        stack.bridge_start({})
