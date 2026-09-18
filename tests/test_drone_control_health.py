"""Docker 1 /health must always say which backend is in use.

The dashboard's mode badge ("MOCK: no real drones" / "CRAZYSWARM: real drones")
comes from this field. It once went missing whenever the backend was degraded,
which is exactly the state of a CrazySwarm run before the bridge is up, and the
dashboard kept showing the previous run's MOCK badge.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import drone_control_service.app as control
from drone_control_service.clients import CrazySwarmApiDroneClient, MockDroneClient


@pytest.fixture
def client():
    return TestClient(control.app)


def test_healthy_reply_includes_the_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["mode"] == "mock"  # conftest forces DRONE_MODE=mock


def test_degraded_reply_still_includes_the_mode(client, monkeypatch):
    def backend_down():
        raise RuntimeError("bridge not reachable")

    monkeypatch.setattr(control._CLIENT, "health", backend_down)

    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["mode"] == "mock"


@pytest.mark.parametrize("alias", ["crazyswarm", "crazyflie", "ros2"])
def test_mode_names_the_backend_not_the_alias(monkeypatch, alias):
    """make_drone_client() accepts several spellings for the real-drone backend.
    All of them must report 'crazyswarm', or the dashboard would not warn that
    real drones are connected."""
    monkeypatch.setenv("DRONE_MODE", alias)
    real = control.make_drone_client({"drones": {"ids": [1]}})

    assert isinstance(real, CrazySwarmApiDroneClient)
    assert control._mode_of(real) == "crazyswarm"


def test_mock_client_reports_mock():
    assert control._mode_of(MockDroneClient({"drones": {"ids": [1]}})) == "mock"
