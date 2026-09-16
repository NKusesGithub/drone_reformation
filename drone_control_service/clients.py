from __future__ import annotations

import math
import os
import time
from abc import ABC, abstractmethod
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

import requests


class DroneClientBase(ABC):
    """Backend contract owned exclusively by Docker 1."""

    ids: List[int]

    @abstractmethod
    def health(self) -> Dict[str, Any]: ...

    @abstractmethod
    def get_states(self) -> Dict[int, Dict[str, Any]]: ...

    @abstractmethod
    def get_drone_status(self, drone_id: int) -> Dict[str, Any]: ...

    @abstractmethod
    def setup_hover(self, drone_ids: Optional[Iterable[int]] = None) -> Any: ...

    @abstractmethod
    def hover(self, drone_ids: Optional[Iterable[int]] = None) -> Any: ...

    @abstractmethod
    def move_to_xy_z(
        self,
        drone_id: int,
        x: float,
        y: float,
        z: float,
        velocity: float,
    ) -> Any: ...

    @abstractmethod
    def land(self, drone_ids: Iterable[int], disarm: bool = True) -> Any: ...

    def down(self, drone_ids: Iterable[int], disarm: bool = True) -> Any:
        """A simulated loss uses the normal land path; status becomes ``down``."""
        return self.land(drone_ids, disarm=disarm)

    @abstractmethod
    def shutdown(
        self,
        drone_ids: Optional[Iterable[int]] = None,
        land: bool = True,
        disarm: bool = True,
        release_api_control: bool = True,
    ) -> Any: ...


class CrazySwarmApiDroneClient(DroneClientBase):
    """HTTP adapter for the current per-drone CrazySwarm FastAPI service.

    Docker 1 is the only service that talks to this API. All other containers
    continue to call Docker 1 through ``RemoteDroneControlClient``.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        drones_cfg = config.get("drones", {})
        self.ids = [int(x) for x in drones_cfg.get("ids", [1, 2, 3])]
        self.base_url = os.getenv(
            "CRAZYSWARM_API_URL",
            str(drones_cfg.get("crazyswarm_api_url", "http://127.0.0.1:8011")),
        ).rstrip("/")
        self.timeout = float(drones_cfg.get("control_timeout", 300.0))
        self.hover_z = float(drones_cfg.get("hover_z", 1.0))
        self.takeoff_duration = float(drones_cfg.get("takeoff_duration", 2.0))
        self.land_height = float(drones_cfg.get("land_height", 0.04))
        self.land_duration = float(drones_cfg.get("land_duration", 2.0))
        self.command_settle_seconds = float(drones_cfg.get("command_settle_seconds", 0.25))
        self.group_mask = int(drones_cfg.get("group_mask", 0))
        self._session = requests.Session()

        api_key = os.getenv("CRAZYSWARM_API_KEY", "").strip()
        if api_key:
            self._session.headers.update({"X-API-Key": api_key})

    def _ids_or_all(self, drone_ids: Optional[Iterable[int]]) -> List[int]:
        ids = [int(x) for x in drone_ids] if drone_ids is not None else list(self.ids)
        invalid = [x for x in ids if x not in self.ids]
        if invalid:
            raise ValueError(f"Unknown drone IDs: {invalid}. Valid IDs: {self.ids}")
        return ids

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                method,
                url,
                json=payload,
                timeout=self.timeout if timeout is None else float(timeout),
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            raise RuntimeError(f"CrazySwarm API rejected {method} {path}: {body}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"CrazySwarm API request failed for {method} {url}: {exc}") from exc

        if not response.content:
            return {}
        return response.json()

    def health(self) -> Dict[str, Any]:
        payload = self._request("GET", "/health", timeout=min(self.timeout, 10.0))
        return {
            "backend": "crazyswarm",
            "base_url": self.base_url,
            "upstream": payload,
        }

    @staticmethod
    def _normalize_status_item(item: Dict[str, Any]) -> Dict[str, Any]:
        drone_id = int(item.get("id", item.get("drone_id")))
        name = str(item.get("name", f"cf{drone_id}"))
        status_value = str(item.get("status", "idle")).strip().lower()
        if status_value not in {"idle", "busy", "down"}:
            status_value = "idle"

        raw_position = item.get("position") or {}
        position_received = bool(
            item.get("position_received", item.get("pose_received", bool(raw_position)))
        )
        downed = status_value == "down"

        return {
            "drone_id": drone_id,
            "id": drone_id,
            "vehicle_name": name,
            "name": name,
            "x": float(raw_position.get("x", 0.0)),
            "y": float(raw_position.get("y", 0.0)),
            "z": float(raw_position.get("z", 0.0)),
            "vx": 0.0,
            "vy": 0.0,
            "vz": 0.0,
            "armed": not downed,
            "api_control": True,
            "landed": downed,
            "downed": downed,
            "status": status_value,
            "remaining_seconds": float(item.get("remaining_seconds", 0.0) or 0.0),
            "position_received": position_received,
            "position_timestamp": item.get("position_timestamp"),
            "crazyflie_status": item.get("crazyflie_status", {}),
            "crazyflie_status_received": bool(item.get("crazyflie_status_received", False)),
            "mode": "crazyswarm",
            "last_update": time.time(),
        }

    def get_states(self) -> Dict[int, Dict[str, Any]]:
        payload = self._request("GET", "/drones/status")
        items = payload.get("drones", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise RuntimeError("CrazySwarm /drones/status returned an unsupported payload")

        states: Dict[int, Dict[str, Any]] = {}
        for raw in items:
            if not isinstance(raw, dict):
                continue
            normalized = self._normalize_status_item(raw)
            drone_id = int(normalized["drone_id"])
            if drone_id in self.ids:
                states[drone_id] = normalized
        return states

    def get_drone_status(self, drone_id: int) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        payload = self._request("GET", f"/drones/{drone_id}/status")
        if not isinstance(payload, dict):
            raise RuntimeError(f"CrazySwarm status payload for drone {drone_id} is not a mapping")
        return self._normalize_status_item(payload)

    def setup_hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        arm_results = []
        takeoff_results = []

        for drone_id in ids:
            arm_results.append(
                self._request(
                    "POST",
                    f"/drones/{drone_id}/arm",
                    payload={"arm": True},
                )
            )

        time.sleep(2.0)

        for drone_id in ids:
            takeoff_results.append(
                self._request(
                    "POST",
                    f"/drones/{drone_id}/takeoff",
                    payload={
                        "target_height": self.hover_z,
                        "duration": self.takeoff_duration,
                        "group_mask": self.group_mask,
                    },
                )
            )

        time.sleep(max(0.0, self.takeoff_duration + self.command_settle_seconds))
        return {"arm": arm_results, "takeoff": takeoff_results}

    def hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        # The high-level CrazySwarm commands hold their final setpoint. There is
        # no separate hover endpoint in the current HTTP API.
        return {
            "status": "accepted",
            "command": "hold_current_setpoint",
            "drone_ids": ids,
            "note": "No new command was sent; high-level setpoints remain active.",
        }

    def move_to_xy_z(
        self,
        drone_id: int,
        x: float,
        y: float,
        z: float,
        velocity: float,
    ) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        return self._request(
            "POST",
            f"/drones/{drone_id}/go-to",
            payload={
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "yaw": 0.0,
                "velocity": float(velocity),
                "relative": False,
                "group_mask": self.group_mask,
            },
        )

    def land(self, drone_ids: Iterable[int], disarm: bool = True) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        land_results = []
        for drone_id in ids:
            land_results.append(
                self._request(
                    "POST",
                    f"/drones/{drone_id}/land",
                    payload={
                        "target_height": self.land_height,
                        "duration": self.land_duration,
                        "group_mask": self.group_mask,
                    },
                )
            )

        time.sleep(max(0.0, self.land_duration + self.command_settle_seconds))

        disarm_results = []
        if disarm:
            for drone_id in ids:
                disarm_results.append(
                    self._request(
                        "POST",
                        f"/drones/{drone_id}/arm",
                        payload={"arm": False},
                    )
                )

        return {"land": land_results, "disarm": disarm_results}

    def shutdown(
        self,
        drone_ids: Optional[Iterable[int]] = None,
        land: bool = True,
        disarm: bool = True,
        release_api_control: bool = True,
    ) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        result: Dict[str, Any] = {
            "drone_ids": ids,
            "release_api_control": bool(release_api_control),
            "note": "release_api_control is not applicable to the CrazySwarm HTTP API.",
        }
        if land:
            result["land"] = self.land(ids, disarm=disarm)
        elif disarm:
            result["disarm"] = [
                self._request(
                    "POST",
                    f"/drones/{drone_id}/arm",
                    payload={"arm": False},
                )
                for drone_id in ids
            ]
        return result


class MockDroneClient(DroneClientBase):
    """In-memory backend used for stack smoke tests."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        drones_cfg = config.get("drones", {})
        self.ids = [int(x) for x in drones_cfg.get("ids", [1, 2, 3, 4])]
        self.hover_z = float(drones_cfg.get("hover_z", 1.0))
        self.vehicle_names = {
            int(k): str(v) for k, v in drones_cfg.get("vehicle_names", {}).items()
        }
        initial_positions = drones_cfg.get("initial_positions", {})
        self._lock = RLock()
        self._states: Dict[int, Dict[str, Any]] = {}
        now = time.time()

        for drone_id in self.ids:
            pos = initial_positions.get(str(drone_id), initial_positions.get(drone_id, [0.0, 0.0]))
            x = float(pos[0]) if len(pos) > 0 else 0.0
            y = float(pos[1]) if len(pos) > 1 else 0.0
            z = float(pos[2]) if len(pos) > 2 else 0.0
            self._states[drone_id] = {
                "drone_id": drone_id,
                "id": drone_id,
                "vehicle_name": self.vehicle_names.get(drone_id, f"cf{drone_id}"),
                "name": self.vehicle_names.get(drone_id, f"cf{drone_id}"),
                "x": x,
                "y": y,
                "z": z,
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "armed": False,
                "api_control": True,
                "landed": False,
                "downed": False,
                "status": "idle",
                "remaining_seconds": 0.0,
                "position_received": True,
                "mode": "mock",
                "last_update": now,
            }

    def _ids_or_all(self, drone_ids: Optional[Iterable[int]]) -> List[int]:
        ids = [int(x) for x in drone_ids] if drone_ids is not None else list(self.ids)
        invalid = [x for x in ids if x not in self.ids]
        if invalid:
            raise ValueError(f"Unknown drone IDs: {invalid}. Valid IDs: {self.ids}")
        return ids

    def health(self) -> Dict[str, Any]:
        return {"backend": "mock", "status": "ready"}

    def get_states(self) -> Dict[int, Dict[str, Any]]:
        with self._lock:
            return {i: dict(v) for i, v in self._states.items()}

    def get_drone_status(self, drone_id: int) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        with self._lock:
            return dict(self._states[drone_id])

    def setup_hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        with self._lock:
            for drone_id in ids:
                self._states[drone_id].update(
                    {
                        "armed": True,
                        "landed": False,
                        "downed": False,
                        "status": "idle",
                        "z": self.hover_z,
                        "last_update": time.time(),
                    }
                )
        return {"drone_ids": ids}

    def hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        return {"drone_ids": ids, "status": "accepted"}

    def move_to_xy_z(
        self,
        drone_id: int,
        x: float,
        y: float,
        z: float,
        velocity: float,
    ) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        with self._lock:
            state = self._states[drone_id]
            if state["status"] == "down":
                raise RuntimeError(f"Drone {drone_id} is down and cannot move")
            old_x, old_y, old_z = float(state["x"]), float(state["y"]), float(state["z"])
            distance = math.sqrt((x - old_x) ** 2 + (y - old_y) ** 2 + (z - old_z) ** 2)
            duration = max(distance / max(float(velocity), 1e-6), 0.001)
            state.update(
                {
                    "status": "busy",
                    "remaining_seconds": duration,
                    "vx": (float(x) - old_x) / duration,
                    "vy": (float(y) - old_y) / duration,
                    "vz": (float(z) - old_z) / duration,
                }
            )

        time.sleep(min(duration, 0.05))
        with self._lock:
            state = self._states[drone_id]
            state.update(
                {
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "status": "idle",
                    "remaining_seconds": 0.0,
                    "last_update": time.time(),
                }
            )
        return {"drone_id": drone_id, "computed_duration": duration}

    def land(self, drone_ids: Iterable[int], disarm: bool = True) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        with self._lock:
            for drone_id in ids:
                state = self._states[drone_id]
                state.update(
                    {
                        "z": 0.0,
                        "vx": 0.0,
                        "vy": 0.0,
                        "vz": 0.0,
                        "landed": True,
                        "downed": True,
                        "status": "down",
                        "remaining_seconds": 0.0,
                        "armed": False if disarm else state["armed"],
                        "last_update": time.time(),
                    }
                )
        return {"drone_ids": ids}

    def shutdown(
        self,
        drone_ids: Optional[Iterable[int]] = None,
        land: bool = True,
        disarm: bool = True,
        release_api_control: bool = True,
    ) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        if land:
            self.land(ids, disarm=disarm)
        return {"drone_ids": ids, "release_api_control": release_api_control}


class AirSimDroneClient(DroneClientBase):
    """Legacy AirSim adapter retained for backward compatibility."""

    def __init__(self, config: Dict[str, Any]):
        try:
            import airsim  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("DRONE_MODE=airsim requires the airsim Python package") from exc

        self.airsim = airsim
        self.config = config
        drones_cfg = config.get("drones", {})
        self.ids = [int(x) for x in drones_cfg.get("ids", [1, 2, 3, 4])]
        self.hover_z = float(drones_cfg.get("hover_z", -20.0))
        self.takeoff_timeout = float(drones_cfg.get("takeoff_timeout", 30.0))
        self.move_velocity = float(drones_cfg.get("move_velocity", 2.0))
        self.vehicle_names = {
            int(k): str(v) for k, v in drones_cfg.get("vehicle_names", {}).items()
        }
        self.initial_positions = {
            int(k): [float(v) for v in values]
            for k, values in drones_cfg.get("initial_positions", {}).items()
        }
        self._busy_until: Dict[int, float] = {}
        self._lock = RLock()
        ip = os.getenv("AIRSIM_IP", str(drones_cfg.get("airsim_ip", "127.0.0.1")))
        self.client = airsim.MultirotorClient(ip=ip)
        self.client.confirmConnection()

    def _name(self, drone_id: int) -> str:
        return self.vehicle_names.get(int(drone_id), f"Drone{int(drone_id)}")

    def _ids_or_all(self, drone_ids: Optional[Iterable[int]]) -> List[int]:
        ids = [int(x) for x in drone_ids] if drone_ids is not None else list(self.ids)
        invalid = [x for x in ids if x not in self.ids]
        if invalid:
            raise ValueError(f"Unknown drone IDs: {invalid}. Valid IDs: {self.ids}")
        return ids

    def _initial(self, drone_id: int) -> tuple[float, float, float]:
        values = self.initial_positions.get(int(drone_id), [0.0, 0.0, 0.0])
        return (
            float(values[0]) if len(values) > 0 else 0.0,
            float(values[1]) if len(values) > 1 else 0.0,
            float(values[2]) if len(values) > 2 else 0.0,
        )

    def health(self) -> Dict[str, Any]:
        return {"backend": "airsim", "status": "ready"}

    def get_states(self) -> Dict[int, Dict[str, Any]]:
        output: Dict[int, Dict[str, Any]] = {}
        now = time.monotonic()
        for drone_id in self.ids:
            name = self._name(drone_id)
            state = self.client.getMultirotorState(vehicle_name=name)
            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity
            initial_x, initial_y, initial_z = self._initial(drone_id)
            landed = state.landed_state == self.airsim.LandedState.Landed
            if landed:
                activity = "down"
            elif self._busy_until.get(drone_id, 0.0) > now:
                activity = "busy"
            else:
                activity = "idle"
            output[drone_id] = {
                "drone_id": drone_id,
                "id": drone_id,
                "vehicle_name": name,
                "name": name,
                "x": float(pos.x_val) + initial_x,
                "y": float(pos.y_val) + initial_y,
                "z": float(pos.z_val) + initial_z,
                "vx": float(vel.x_val),
                "vy": float(vel.y_val),
                "vz": float(vel.z_val),
                "armed": bool(getattr(state, "armed", not landed)),
                "api_control": True,
                "landed": bool(landed),
                "downed": activity == "down",
                "status": activity,
                "remaining_seconds": max(0.0, self._busy_until.get(drone_id, 0.0) - now),
                "position_received": True,
                "mode": "airsim",
                "last_update": time.time(),
            }
        return output

    def get_drone_status(self, drone_id: int) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        return self.get_states()[drone_id]

    def setup_hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        futures = []
        for drone_id in ids:
            name = self._name(drone_id)
            self.client.enableApiControl(True, vehicle_name=name)
            self.client.armDisarm(True, vehicle_name=name)
            futures.append(self.client.takeoffAsync(timeout_sec=self.takeoff_timeout, vehicle_name=name))
        for future in futures:
            future.join()
        futures = [
            self.client.moveToZAsync(self.hover_z, self.move_velocity, vehicle_name=self._name(drone_id))
            for drone_id in ids
        ]
        for future in futures:
            future.join()
        return {"drone_ids": ids}

    def hover(self, drone_ids: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        for drone_id in ids:
            self.client.hoverAsync(vehicle_name=self._name(drone_id))
        return {"drone_ids": ids}

    def move_to_xy_z(
        self,
        drone_id: int,
        x: float,
        y: float,
        z: float,
        velocity: float,
    ) -> Dict[str, Any]:
        drone_id = self._ids_or_all([drone_id])[0]
        current = self.get_states()[drone_id]
        distance = math.sqrt(
            (float(x) - float(current["x"])) ** 2
            + (float(y) - float(current["y"])) ** 2
            + (float(z) - float(current["z"])) ** 2
        )
        duration = distance / max(float(velocity), 1e-6)
        initial_x, initial_y, initial_z = self._initial(drone_id)
        self.client.moveToPositionAsync(
            float(x) - initial_x,
            float(y) - initial_y,
            float(z) - initial_z,
            float(velocity),
            vehicle_name=self._name(drone_id),
        )
        self._busy_until[drone_id] = time.monotonic() + duration
        return {"drone_id": drone_id, "computed_duration": duration}

    def land(self, drone_ids: Iterable[int], disarm: bool = True) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        futures = [
            self.client.landAsync(vehicle_name=self._name(drone_id)) for drone_id in ids
        ]
        for future in futures:
            future.join()
        if disarm:
            for drone_id in ids:
                self.client.armDisarm(False, vehicle_name=self._name(drone_id))
        return {"drone_ids": ids}

    def shutdown(
        self,
        drone_ids: Optional[Iterable[int]] = None,
        land: bool = True,
        disarm: bool = True,
        release_api_control: bool = True,
    ) -> Dict[str, Any]:
        ids = self._ids_or_all(drone_ids)
        if land:
            self.land(ids, disarm=disarm)
        for drone_id in ids:
            name = self._name(drone_id)
            if not land:
                self.client.hoverAsync(vehicle_name=name)
            if disarm and not land:
                self.client.armDisarm(False, vehicle_name=name)
            if release_api_control:
                self.client.enableApiControl(False, vehicle_name=name)
        return {"drone_ids": ids}


def make_drone_client(config: Dict[str, Any]) -> DroneClientBase:
    mode = os.getenv(
        "DRONE_MODE",
        str(config.get("drones", {}).get("mode", "crazyswarm")),
    ).strip().lower()

    if mode in {"crazyswarm", "crazyflie", "ros2"}:
        return CrazySwarmApiDroneClient(config)
    if mode == "mock":
        return MockDroneClient(config)
    if mode in {"airsim", "colosseum"}:
        return AirSimDroneClient(config)
    raise ValueError(
        f"Unknown DRONE_MODE={mode!r}. Use 'crazyswarm', 'mock', or 'airsim'."
    )
