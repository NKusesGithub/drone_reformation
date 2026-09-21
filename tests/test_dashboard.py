"""Dashboard: the page is served, and only the listed actions get forwarded."""

from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient

import dashboard_service.app as dashboard


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class Calls(list):
    """Forwarded requests, plus `reply`: what the fake upstream answers with
    (a FakeResponse, or an exception to raise). `replies` overrides `reply`
    for any URL that contains one of its keys."""

    reply: object = None
    replies: dict


@pytest.fixture
def calls(monkeypatch):
    """Record every request the dashboard forwards instead of sending it."""
    recorded = Calls()
    recorded.reply = FakeResponse(200, {"status": "ok"})
    recorded.replies = {}

    def fake_request(method, url, json=None, timeout=None):
        recorded.append({"method": method, "url": url, "json": json, "timeout": timeout})
        reply = next((r for key, r in recorded.replies.items() if key in url), recorded.reply)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(dashboard.requests, "request", fake_request)
    return recorded


@pytest.fixture
def client():
    return TestClient(dashboard.app)


def post(client, path, body=None):
    return client.post(path, json=body if body is not None else {})


def test_the_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Drone Reformation Dashboard</title>" in response.text


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_status_reads_are_forwarded_to_the_right_service(client, calls):
    client.get("/api/control/drones/status")
    client.get("/api/mission/status")

    assert calls[0]["url"] == f"{dashboard.UPSTREAMS['control']}/drones/status"
    assert calls[0]["method"] == "GET"
    assert calls[1]["url"] == f"{dashboard.UPSTREAMS['mission']}/status"


def test_button_body_is_passed_through(client, calls):
    post(client, "/api/simulator/down", {"drone_ids": [2], "disarm": True})

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == f"{dashboard.UPSTREAMS['simulator']}/down"
    assert calls[0]["json"] == {"drone_ids": [2], "disarm": True}


def test_slow_actions_get_a_long_timeout(client, calls):
    """Reform and land wait for drones to finish, so a short timeout would
    report failure while the drones are still moving."""
    post(client, "/api/mission/reform_now")
    assert calls[0]["timeout"] >= 300


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/control/move_to_xy_z"),   # not a button: no direct flying
        ("POST", "/api/control/setup_hover"),
        ("GET", "/api/mission/start"),           # right path, wrong method
        ("GET", "/api/nowhere/status"),          # unknown service
    ],
)
def test_anything_not_on_the_list_is_refused(client, calls, method, path):
    response = client.request(method, path, json={} if method == "POST" else None)

    assert response.status_code == 404
    assert calls == []


def test_actions_must_be_json(client, calls):
    """A form on another website can POST text/plain to localhost without the
    browser asking first. That must not start the mission."""
    response = client.post(
        "/api/mission/start",
        content='{"setup_hover": true}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert calls == []


def test_invalid_json_is_rejected(client, calls):
    response = client.post(
        "/api/mission/start", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert calls == []


def test_upstream_errors_are_passed_back(client, calls):
    calls.reply = FakeResponse(400, {"detail": "Unknown drone IDs: [42]"})

    response = post(client, "/api/simulator/down", {"drone_ids": [42]})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown drone IDs: [42]"


def test_an_unreachable_service_is_a_502(client, calls):
    calls.reply = requests.ConnectionError("connection refused")

    response = client.get("/api/mission/status")

    assert response.status_code == 502
    assert "mission is unreachable" in response.json()["detail"]


# --------------------------------------------------------------------------
# The debug panel: which services work, plus the known-faults checklist.
#
# drone-control and mission both answer /health with HTTP 200 while broken,
# so these tests give each URL its own reply. A single shared reply cannot
# tell a probe that reads the right route from one that reads the wrong one.
# --------------------------------------------------------------------------

CONTROL_HEALTH = f"{dashboard.UPSTREAMS['control']}/health"
MISSION_STATUS = f"{dashboard.UPSTREAMS['mission']}/status"


def healthy(calls, mode="crazyswarm", upstream=None):
    """Every service answering, with a running mission worker."""
    backend = {"backend": mode, "upstream": upstream if upstream is not None else {"ready": True}}
    calls.replies = {
        CONTROL_HEALTH: FakeResponse(200, {"status": "ok", "mode": mode, "backend": backend}),
        MISSION_STATUS: FakeResponse(200, {"running": True, "last_error": None}),
    }


def rows(client):
    return {row["name"]: row for row in client.get("/api/debug/status").json()["services"]}


def test_debug_status_lists_every_port_and_the_bridge(client, calls):
    healthy(calls)
    body = client.get("/api/debug/status").json()

    ports = [(row["name"], row["port"]) for row in body["services"]]
    assert ports == [
        ("drone-control", 8001),
        ("hungarian", 8002),
        ("formation", 8003),
        ("mission", 8004),
        ("downed-simulator", 8005),
        ("dashboard", 8006),
        ("crazyswarm-bridge", 8011),
    ]


def test_debug_status_reads_the_routes_that_tell_the_truth(client, calls):
    healthy(calls)
    client.get("/api/debug/status")

    assert {call["url"] for call in calls} == {
        CONTROL_HEALTH,
        MISSION_STATUS,  # not /health: it answers ok with a dead worker
        f"{dashboard.DEBUG_URLS['hungarian']}/health",
        f"{dashboard.DEBUG_URLS['formation']}/health",
        f"{dashboard.UPSTREAMS['simulator']}/health",
    }
    # The bridge listens on 127.0.0.1, which this container cannot reach, so
    # it is never probed directly: its row comes from drone-control.
    assert all(":8011" not in call["url"] for call in calls)


def test_debug_status_reports_the_dashboard_itself_as_up_without_a_request(client, calls):
    healthy(calls)
    assert rows(client)["dashboard"]["state"] == "ok"
    assert all("8006" not in call["url"] for call in calls)


def test_a_healthy_stack_is_all_ok(client, calls):
    healthy(calls)
    assert {name: row["state"] for name, row in rows(client).items()} == {
        "drone-control": "ok",
        "hungarian": "ok",
        "formation": "ok",
        "mission": "ok",
        "downed-simulator": "ok",
        "dashboard": "ok",
        "crazyswarm-bridge": "ok",
    }


def test_the_18_september_incident_shows_red_where_it_was_broken(client, calls):
    # The bridge was gone. drone-control still answered /health with HTTP 200,
    # and mission's /health still said ok, but its worker had died.
    refused = "Connection refused to 127.0.0.1:8011"
    calls.replies = {
        CONTROL_HEALTH: FakeResponse(200, {"status": "degraded", "mode": "crazyswarm",
                                           "backend_error": refused}),
        MISSION_STATUS: FakeResponse(200, {"running": False,
                                           "last_error": f"RuntimeError: {refused}"}),
    }

    table = rows(client)

    assert table["drone-control"]["state"] == "degraded"
    assert table["drone-control"]["ok"] is False
    assert table["crazyswarm-bridge"]["state"] == "down"
    assert refused in table["crazyswarm-bridge"]["detail"]
    assert table["mission"]["state"] == "down"
    assert refused in table["mission"]["detail"]


def test_a_mission_worker_that_never_started_is_down(client, calls):
    healthy(calls)
    calls.replies[MISSION_STATUS] = FakeResponse(200, {"running": False, "last_error": None})

    mission = rows(client)["mission"]
    assert mission["state"] == "down"
    assert "not running" in mission["detail"]


def test_a_bridge_that_answers_but_is_not_ready_is_down(client, calls):
    healthy(calls, upstream={"ready": False, "status": "initializing"})

    bridge = rows(client)["crazyswarm-bridge"]
    assert bridge["state"] == "down"
    assert "not ready" in bridge["detail"]


def test_a_bridge_health_without_a_ready_key_is_ok(client, calls):
    # Mission's own readiness rule: only an explicit false blocks it.
    healthy(calls, upstream={"status": "ok"})
    assert rows(client)["crazyswarm-bridge"]["state"] == "ok"


@pytest.mark.parametrize("mode", ["mock", "airsim"])
def test_the_bridge_is_unused_outside_crazyswarm_mode(client, calls, mode):
    healthy(calls, mode=mode)

    bridge = rows(client)["crazyswarm-bridge"]
    assert bridge["state"] == "unused"
    assert bridge["ok"] is False
    assert mode in bridge["detail"]


def test_everything_unreachable_is_down_and_the_bridge_is_unknown(client, calls):
    calls.reply = requests.ConnectionError("connection refused")

    table = rows(client)

    assert table["dashboard"]["state"] == "ok"
    assert table["crazyswarm-bridge"]["state"] == "unknown"
    for name, row in table.items():
        if name not in {"dashboard", "crazyswarm-bridge"}:
            assert row["state"] == "down", name
            assert "connection refused" in row["detail"]


def test_an_error_response_is_down(client, calls):
    healthy(calls)
    calls.replies[CONTROL_HEALTH] = FakeResponse(500, text="internal error")

    control = rows(client)["drone-control"]
    assert control["state"] == "down"
    assert control["detail"] == "HTTP 500"


def test_debug_status_includes_the_known_faults_checklist(client, calls):
    healthy(calls)
    body = client.get("/api/debug/status").json()

    symptoms = {item["symptom"] for item in body["checklist"]}
    assert any("mission" in s and "/health" in s for s in symptoms)
    assert any("degraded" in s for s in symptoms)
    assert all("check" in item and item["check"] for item in body["checklist"])


# --------------------------------------------------------------------------
# The dashboard's own routes (config editing), which must not be swallowed
# by the catch-all that forwards everything else.
# --------------------------------------------------------------------------

CONFIG_TEXT = """\
drones:
  ids: [1, 2]
  hover_z: 1.0
mission:
  old_formation: [2]
  formation_spacing: 0.5
"""


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    from dashboard_service import configio

    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT)
    monkeypatch.setattr(configio, "CONFIG_YAML", path)
    monkeypatch.setattr(configio, "BACKUP_DIR", tmp_path / "config_backups")
    monkeypatch.setitem(configio.FILES["config"], "path", path)
    return path


def test_the_page_assets_are_served(client):
    assert "function renderMap" in client.get("/static/app.js").text
    assert ".card" in client.get("/static/style.css").text


def test_settings_are_readable(client, config_file, calls):
    body = client.get("/api/config/parameters").json()

    assert {p["id"] for p in body["parameters"]} >= {"drones.hover_z", "mission.safety_gap"}
    assert calls == []  # answered here, not forwarded to another service


def test_settings_can_be_saved(client, config_file):
    response = client.post(
        "/api/config/parameters", json={"edits": [{"id": "drones.hover_z", "value": "1.3"}]}
    )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert "hover_z: 1.3" in config_file.read_text()


def test_a_bad_value_is_reported_not_crashed(client, config_file):
    before = config_file.read_text()
    response = client.post(
        "/api/config/parameters", json={"edits": [{"id": "drones.hover_z", "value": "up"}]}
    )

    assert response.status_code == 400
    assert "not a number" in response.json()["detail"]
    assert config_file.read_text() == before


def test_saving_settings_needs_json(client, config_file):
    response = client.post(
        "/api/config/parameters", content='{"edits": []}', headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 415


def test_the_whole_file_can_be_saved(client, config_file):
    text = CONFIG_TEXT.replace("hover_z: 1.0", "hover_z: 1.6")
    response = client.post("/api/config/raw", json={"text": text})

    assert response.status_code == 200
    assert config_file.read_text() == text


def test_broken_yaml_is_refused_over_http(client, config_file):
    before = config_file.read_text()
    response = client.post("/api/config/raw", json={"text": "drones:\n  ids: [1,\n"})

    assert response.status_code == 400
    assert config_file.read_text() == before


def test_an_unknown_file_is_a_404(client):
    assert client.get("/api/config/file/passwords").status_code == 404
