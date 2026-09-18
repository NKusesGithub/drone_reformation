from __future__ import annotations

import os
import time
from threading import Event, RLock, Thread
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from drone_common.config import get_drone_ids, load_config
from drone_common.control_client import RemoteDroneControlClient

CONFIG = load_config()
DRONE_IDS = get_drone_ids(CONFIG)
DRONE_CONTROL_URL = os.getenv("DRONE_CONTROL_URL", "http://drone-control:8001").rstrip("/")
FORMATION_SERVICE_URL = os.getenv("FORMATION_SERVICE_URL", "http://formation:8000").rstrip("/")
HUNGARIAN_SERVICE_URL = os.getenv("HUNGARIAN_SERVICE_URL", "http://hungarian:8000").rstrip("/")
AUTO_START = os.getenv("MISSION_AUTO_START", "1").strip().lower() in {"1", "true", "yes"}

mission_cfg = CONFIG.get("mission", {})
drones_cfg = CONFIG.get("drones", {})
OLD_FORMATION = [int(x) for x in mission_cfg.get("old_formation", [1, 3, 4, 3, 2, 1])]
FORMATION_SPACING = float(mission_cfg.get("formation_spacing", 0.5))
HOVER_Z = float(drones_cfg.get("hover_z", 1.0))
POLL_INTERVAL = float(mission_cfg.get("poll_interval", 1.0))
SAFETY_GAP = float(mission_cfg.get("safety_gap", 0.25))
INCLUDE_DOWNED_IN_SAFETY = bool(mission_cfg.get("include_downed_in_safety", False))
WAYPOINT_STEP = float(mission_cfg.get("waypoint_step", 0.25))
MOVE_VELOCITY = float(mission_cfg.get("move_velocity", 0.5))
TARGET_TOLERANCE = float(mission_cfg.get("target_tolerance", 0.05))
MOVEMENT_POLL_INTERVAL = float(mission_cfg.get("movement_poll_interval", 0.1))
COMMAND_TIMEOUT_MARGIN = float(mission_cfg.get("command_timeout_margin", 3.0))
CONTROL_READY_TIMEOUT = float(mission_cfg.get("control_ready_timeout", 120.0))
MAX_MOVE_SECONDS_PER_DRONE = float(mission_cfg.get("max_move_seconds_per_drone", 120.0))
BACKWARD_PENALTY = float(mission_cfg.get("backward_penalty", 0.0))
BACKWARD_THRESHOLD = float(mission_cfg.get("backward_threshold", 0.0))
ANCHOR_POLICY = str(mission_cfg.get("anchor_policy", "active_centroid"))

control = RemoteDroneControlClient(
    DRONE_CONTROL_URL,
    timeout=float(mission_cfg.get("control_timeout", 300.0)),
)
app = FastAPI(title="Docker 4 - Mission Orchestrator")

_lock = RLock()
_stop_event = Event()
_worker: Optional[Thread] = None
_running = False
_last_downed: Set[int] = set()
_last_reform: Optional[Dict[str, Any]] = None
_last_move: Optional[Dict[str, Any]] = None
_last_error: Optional[str] = None
_setup_done = False
_initial_formation_done = False
_initial_anchor_xy: Optional[np.ndarray] = None


class StartRequest(BaseModel):
    setup_hover: bool = True


class SimulateDownedRequest(BaseModel):
    drone_ids: List[int]
    disarm: bool = True


class ShutdownRequest(BaseModel):
    land: bool = True
    disarm: bool = True
    release_api_control: bool = True



def _wait_for_control_ready() -> None:
    deadline = time.monotonic() + max(1.0, CONTROL_READY_TIMEOUT)
    last_error: Optional[str] = None

    while time.monotonic() < deadline and not _stop_event.is_set():
        try:
            payload = control.health()
            backend = payload.get("backend", {}) if isinstance(payload, dict) else {}
            upstream = backend.get("upstream", {}) if isinstance(backend, dict) else {}
            upstream_ready = upstream.get("ready")
            if payload.get("status") == "ok" and upstream_ready is not False:
                return
            last_error = f"control health not ready: {payload}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.0)

    raise RuntimeError(
        f"Docker 1/CrazySwarm API did not become ready within "
        f"{CONTROL_READY_TIMEOUT:.1f} seconds: {last_error}"
    )


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _activity_status(state: Dict[str, Any]) -> str:
    value = str(state.get("status", "idle")).strip().lower()
    if value in {"idle", "busy", "down"}:
        return value
    if state.get("downed") or state.get("landed"):
        return "down"
    return "idle"


def _is_downed(state: Dict[str, Any]) -> bool:
    return _activity_status(state) == "down"


def _xy(state: Dict[str, Any]) -> np.ndarray:
    return np.asarray([float(state["x"]), float(state["y"])], dtype=float)


def _detect_downed(states: Dict[int, Dict[str, Any]]) -> Set[int]:
    return {int(drone_id) for drone_id, state in states.items() if _is_downed(state)}


def _active_ids_from_states(states: Dict[int, Dict[str, Any]]) -> List[int]:
    return [
        int(drone_id)
        for drone_id in DRONE_IDS
        if int(drone_id) in states and not _is_downed(states[int(drone_id)])
    ]


def _formation_world_targets(
    slots_relative: List[List[float]],
    states: Dict[int, Dict[str, Any]],
    active_ids: List[int],
) -> List[Tuple[float, float]]:
    global _initial_anchor_xy

    slots = np.asarray(slots_relative, dtype=float)
    if len(slots) == 0:
        return []

    active_pos = np.asarray([_xy(states[drone_id]) for drone_id in active_ids], dtype=float)

    if ANCHOR_POLICY == "active_centroid":
        anchor = active_pos.mean(axis=0) - slots.mean(axis=0)
    elif ANCHOR_POLICY == "initial_anchor":
        if _initial_anchor_xy is None:
            _initial_anchor_xy = active_pos.mean(axis=0) - slots.mean(axis=0)
        anchor = _initial_anchor_xy
    elif ANCHOR_POLICY == "origin":
        anchor = np.asarray([0.0, 0.0], dtype=float)
    else:
        raise RuntimeError(f"Unknown mission.anchor_policy={ANCHOR_POLICY!r}")

    world = slots + anchor[None, :]
    return [(float(x), float(y)) for x, y in world]


def _check_pairwise_safety(
    points: List[Tuple[float, float]],
    safety_gap: float,
) -> Tuple[bool, Optional[str]]:
    arr = np.asarray(points, dtype=float)
    for i in range(len(arr)):
        for j in range(i + 1, len(arr)):
            distance = float(np.linalg.norm(arr[i] - arr[j]))
            if distance < safety_gap:
                return False, (
                    f"points {i} and {j} violate safety gap: "
                    f"distance={distance:.3f}, safety_gap={safety_gap:.3f}"
                )
    return True, None


def _waypoint_is_safe(
    drone_id: int,
    waypoint_xy: np.ndarray,
    states: Dict[int, Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    for other_id, state in states.items():
        other_id = int(other_id)
        if other_id == int(drone_id):
            continue
        if _is_downed(state) and not INCLUDE_DOWNED_IN_SAFETY:
            continue
        distance = float(np.linalg.norm(waypoint_xy - _xy(state)))
        if distance < SAFETY_GAP:
            return False, (
                f"waypoint for drone {drone_id} too close to drone {other_id}: "
                f"{distance:.3f} < {SAFETY_GAP:.3f}"
            )
    return True, None


def _call_formation(downed_count: int) -> Dict[str, Any]:
    return _post_json(
        f"{FORMATION_SERVICE_URL}/formation",
        {
            "old_formation": OLD_FORMATION,
            "downed_drones": int(downed_count),
            "spacing": FORMATION_SPACING,
        },
    )


def _call_hungarian(
    active_ids: List[int],
    states: Dict[int, Dict[str, Any]],
    target_positions: List[Tuple[float, float]],
) -> Dict[str, Any]:
    old_positions = {
        int(drone_id): [float(states[drone_id]["x"]), float(states[drone_id]["y"])]
        for drone_id in active_ids
    }
    return _post_json(
        f"{HUNGARIAN_SERVICE_URL}/assign",
        {
            "active_ids": active_ids,
            "old_positions": old_positions,
            "target_positions": target_positions,
            "backward_penalty": BACKWARD_PENALTY,
            "backward_threshold": BACKWARD_THRESHOLD,
            "cascade_front_first": True,
            "spacing": FORMATION_SPACING,
        },
    )


def _wait_for_terminal_status(drone_id: int, timeout: float) -> Dict[str, Any]:
    deadline = time.monotonic() + max(0.1, timeout)
    last: Dict[str, Any] = {}

    while time.monotonic() < deadline:
        last = control.get_drone_status(drone_id)
        current = _activity_status(last)
        if current in {"idle", "down"}:
            return last
        time.sleep(MOVEMENT_POLL_INTERVAL)

    raise TimeoutError(
        f"Drone {drone_id} remained busy for more than {timeout:.2f} seconds; "
        f"last status={last}"
    )


def _move_drone_safely(drone_id: int, target_xy: Tuple[float, float]) -> Dict[str, Any]:
    started = time.monotonic()
    steps = 0
    blocked = 0
    target = np.asarray(target_xy, dtype=float)
    last_block_reason: Optional[str] = None

    while time.monotonic() - started < MAX_MOVE_SECONDS_PER_DRONE:
        states = control.get_states()
        state = states.get(int(drone_id))
        if state is None:
            raise RuntimeError(f"Drone {drone_id} is missing from Docker 1 /states")
        if _is_downed(state):
            return {
                "drone_id": int(drone_id),
                "status": "aborted_down",
                "steps": steps,
                "blocked_count": blocked,
                "reason": "drone status became down during movement",
            }

        current = _xy(state)
        delta = target - current
        distance = float(np.linalg.norm(delta))
        if distance <= TARGET_TOLERANCE:
            return {
                "drone_id": int(drone_id),
                "status": "arrived",
                "target_position": target.tolist(),
                "final_position": current.tolist(),
                "steps": steps,
                "blocked_count": blocked,
                "elapsed_seconds": time.monotonic() - started,
            }

        direction = delta / max(distance, 1e-9)
        waypoint = current + direction * min(WAYPOINT_STEP, distance)
        safe, reason = _waypoint_is_safe(int(drone_id), waypoint, states)
        if not safe:
            blocked += 1
            last_block_reason = reason
            time.sleep(MOVEMENT_POLL_INTERVAL)
            continue

        step_distance = float(np.linalg.norm(waypoint - current))
        control.move_to_xy_z(
            int(drone_id),
            float(waypoint[0]),
            float(waypoint[1]),
            HOVER_Z,
            MOVE_VELOCITY,
        )
        steps += 1

        expected_duration = step_distance / max(MOVE_VELOCITY, 1e-6)
        terminal = _wait_for_terminal_status(
            int(drone_id),
            timeout=expected_duration + COMMAND_TIMEOUT_MARGIN,
        )
        if _activity_status(terminal) == "down":
            return {
                "drone_id": int(drone_id),
                "status": "aborted_down",
                "steps": steps,
                "blocked_count": blocked,
                "reason": "drone status became down while waiting for go-to completion",
            }

    return {
        "drone_id": int(drone_id),
        "status": "timeout",
        "target_position": target.tolist(),
        "steps": steps,
        "blocked_count": blocked,
        "last_block_reason": last_block_reason,
        "elapsed_seconds": time.monotonic() - started,
    }


def _execute_reform(
    states: Dict[int, Dict[str, Any]],
    downed: Set[int],
) -> Dict[str, Any]:
    global _last_reform, _last_move

    active_ids = _active_ids_from_states(states)
    if not active_ids:
        result = {"status": "no_active_drones", "downed": sorted(downed)}
        with _lock:
            _last_reform = result
            _last_move = result
        return result

    formation = _call_formation(len(downed))
    target_positions = _formation_world_targets(
        formation["slots_relative"],
        states,
        active_ids,
    )
    if len(target_positions) < len(active_ids):
        raise RuntimeError(
            f"Formation returned too few slots: {len(target_positions)} "
            f"for {len(active_ids)} active drones"
        )

    safe, reason = _check_pairwise_safety(
        target_positions[: len(active_ids)],
        SAFETY_GAP,
    )
    if not safe:
        raise RuntimeError(f"Unsafe target formation: {reason}")

    hungarian = _call_hungarian(active_ids, states, target_positions)
    assignments = sorted(
        hungarian["assignment"],
        key=lambda item: int(item.get("cascade_rank", 999999)),
    )

    reform_payload = {
        "at": time.time(),
        "downed": sorted(downed),
        "active_ids": active_ids,
        "formation": formation,
        "target_positions_world": [list(position) for position in target_positions],
        "hungarian": hungarian,
    }
    with _lock:
        _last_reform = reform_payload

    move_results = []
    for item in assignments:
        drone_id = int(item["drone_id"])
        target_xy = tuple(float(value) for value in item["target_position"])
        move_results.append(_move_drone_safely(drone_id, target_xy))

    move_payload = {"at": time.time(), "move_results": move_results}
    with _lock:
        _last_move = move_payload
    return {"reform": reform_payload, "move": move_payload}


def _execute_initial_formation(states: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    global _initial_formation_done

    downed = _detect_downed(states)
    if downed:
        raise RuntimeError(
            f"Cannot execute initial formation because drones are already down: {sorted(downed)}"
        )

    missing_pose = [
        drone_id
        for drone_id in _active_ids_from_states(states)
        if states[drone_id].get("position_received") is False
    ]
    if missing_pose:
        raise RuntimeError(f"No pose received for active drones: {missing_pose}")

    result = _execute_reform(states, set())
    with _lock:
        _initial_formation_done = True
    return {"status": "initial_formation_done", "result": result}


def _mission_loop(setup_hover: bool = True) -> None:
    global _running, _last_downed, _last_error, _setup_done, _initial_formation_done

    with _lock:
        _running = True
        _last_error = None

    try:
        _wait_for_control_ready()

        if setup_hover and not _setup_done:
            control.setup_hover(DRONE_IDS)
            _setup_done = True

        if not _initial_formation_done:
            _execute_initial_formation(control.get_states())

        _last_downed = _detect_downed(control.get_states())

        while not _stop_event.is_set():
            states = control.get_states()
            downed = _detect_downed(states)

            if downed != _last_downed:
                newly_downed = sorted(downed - _last_downed)
                _last_downed = set(downed)
                if newly_downed:
                    _execute_reform(states, downed)

            time.sleep(POLL_INTERVAL)
    except Exception as exc:
        with _lock:
            _last_error = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            _running = False


def _start_worker(setup_hover: bool = True) -> Dict[str, Any]:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return {"status": "already_running"}
        _stop_event.clear()
        _worker = Thread(
            target=_mission_loop,
            kwargs={"setup_hover": setup_hover},
            daemon=True,
        )
        _worker.start()
    return {"status": "started", "setup_hover": setup_hover}


@app.on_event("startup")
def startup() -> None:
    if AUTO_START:
        _start_worker(setup_hover=True)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "mission"}


@app.post("/start")
def start(req: StartRequest) -> Dict[str, Any]:
    return _start_worker(setup_hover=req.setup_hover)


@app.post("/stop")
def stop() -> Dict[str, Any]:
    _stop_event.set()
    return {"status": "stopping"}


@app.get("/status")
def status() -> Dict[str, Any]:
    with _lock:
        return {
            "service": "mission",
            "running": _running,
            "setup_done": _setup_done,
            "initial_formation_done": _initial_formation_done,
            "last_downed": sorted(_last_downed),
            "last_error": _last_error,
            "urls": {
                "drone_control": DRONE_CONTROL_URL,
                "formation": FORMATION_SERVICE_URL,
                "hungarian": HUNGARIAN_SERVICE_URL,
            },
        }


@app.post("/simulate_downed")
def simulate_downed(req: SimulateDownedRequest) -> Dict[str, Any]:
    invalid = [int(value) for value in req.drone_ids if int(value) not in DRONE_IDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown drone IDs: {invalid}. Valid IDs: {DRONE_IDS}",
        )
    try:
        result = control.down([int(value) for value in req.drone_ids], disarm=req.disarm)
        return {"status": "ok", "down_result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/reform_now")
def reform_now() -> Dict[str, Any]:
    try:
        states = control.get_states()
        return _execute_reform(states, _detect_downed(states))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/last_reform")
def last_reform() -> Dict[str, Any]:
    return _last_reform or {"status": "no_reform_yet"}


@app.get("/last_move")
def last_move() -> Dict[str, Any]:
    return _last_move or {"status": "no_move_yet"}


@app.post("/shutdown")
def shutdown(req: ShutdownRequest) -> Dict[str, Any]:
    _stop_event.set()
    try:
        result = control.shutdown(
            DRONE_IDS,
            land=req.land,
            disarm=req.disarm,
            release_api_control=req.release_api_control,
        )
        return {"status": "ok", "control_shutdown": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
