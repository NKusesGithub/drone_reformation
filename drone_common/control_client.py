from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import requests


class RemoteDroneControlClient:
    """HTTP-only client for Docker 1.

    Mission, downed-simulator, and visualization remain backend-agnostic and
    never import CrazySwarm, ROS 2, AirSim, or Colosseum libraries.
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._session = requests.Session()

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        response = self._session.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Drone-control rejected {method} {path}: {response.text}"
            ) from exc
        return response.json() if response.content else {}

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def health(self) -> Dict[str, Any]:
        return self._get("/health")

    def status(self) -> Dict[str, Any]:
        return self._get("/status")

    def get_states(self) -> Dict[int, Dict[str, Any]]:
        payload = self._get("/states")
        return {int(k): v for k, v in payload.items()}

    def get_all_drone_statuses(self) -> Dict[int, Dict[str, Any]]:
        payload = self._get("/drones/status")
        drones = payload.get("drones", [])
        return {
            int(item.get("drone_id", item.get("id"))): item
            for item in drones
        }

    def get_drone_status(self, drone_id: int) -> Dict[str, Any]:
        return self._get(f"/drones/{int(drone_id)}/status")

    def setup_hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        return self._post(
            "/setup_hover",
            {"drone_ids": None if drone_ids is None else [int(x) for x in drone_ids]},
        )

    def hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        return self._post(
            "/hover",
            {"drone_ids": None if drone_ids is None else [int(x) for x in drone_ids]},
        )

    def move_to_xy_z(
        self,
        drone_id: int,
        x: float,
        y: float,
        z: float,
        velocity: float,
    ) -> Dict[str, Any]:
        return self._post(
            "/move_to_xy_z",
            {
                "drone_id": int(drone_id),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "velocity": float(velocity),
            },
        )

    def land(self, drone_ids: Iterable[int], disarm: bool = True) -> Dict[str, Any]:
        return self._post(
            "/land",
            {"drone_ids": [int(x) for x in drone_ids], "disarm": bool(disarm)},
        )

    def down(self, drone_ids: Iterable[int], disarm: bool = True) -> Dict[str, Any]:
        return self._post(
            "/down",
            {"drone_ids": [int(x) for x in drone_ids], "disarm": bool(disarm)},
        )

    def shutdown(
        self,
        drone_ids: Optional[Iterable[int]] = None,
        land: bool = True,
        disarm: bool = True,
        release_api_control: bool = True,
    ) -> Dict[str, Any]:
        return self._post(
            "/shutdown",
            {
                "drone_ids": None if drone_ids is None else [int(x) for x in drone_ids],
                "land": bool(land),
                "disarm": bool(disarm),
                "release_api_control": bool(release_api_control),
            },
        )
