from __future__ import annotations

import os
import time
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from drone_common.config import get_drone_ids, load_config
from drone_control_service.clients import DroneClientBase, make_drone_client

CONFIG = load_config()
_DRONE_IDS = get_drone_ids(CONFIG)
_CLIENT: DroneClientBase = make_drone_client(CONFIG)
_LOCK = RLock()
_LAST_COMMAND: Dict[str, Any] = {
    "command": None,
    "at": None,
    "status": "idle",
    "drone_ids": [],
    "error": None,
}

app = FastAPI(
    title="Docker 1 - Central Drone Control Gateway",
    description=(
        "The only six-stack service allowed to call the CrazySwarm, AirSim, "
        "or mock backend."
    ),
)


class DroneIdsRequest(BaseModel):
    drone_ids: Optional[List[int]] = None


class LandRequest(BaseModel):
    drone_ids: List[int]
    disarm: bool = True


class MoveToRequest(BaseModel):
    drone_id: int
    x: float
    y: float
    z: float
    velocity: float = Field(default=0.5, gt=0.0, le=5.0)


class ShutdownRequest(BaseModel):
    drone_ids: Optional[List[int]] = None
    land: bool = True
    disarm: bool = True
    release_api_control: bool = True


def _ids_or_all(drone_ids: Optional[Iterable[int]]) -> List[int]:
    ids = [int(x) for x in drone_ids] if drone_ids is not None else list(_DRONE_IDS)
    invalid = [x for x in ids if x not in _DRONE_IDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown drone IDs: {invalid}. Valid IDs: {_DRONE_IDS}",
        )
    return ids


def _record(
    command: str,
    command_status: str,
    drone_ids: Iterable[int],
    *,
    error: Optional[str] = None,
    result: Any = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "command": command,
        "at": time.time(),
        "status": command_status,
        "drone_ids": [int(x) for x in drone_ids],
        "error": error,
    }
    if result is not None:
        payload["result"] = result
    _LAST_COMMAND.update(payload)
    return payload


def _run(command: str, drone_ids: List[int], fn: Callable[[], Any]) -> Dict[str, Any]:
    with _LOCK:
        try:
            result = fn()
            return _record(command, "accepted", drone_ids, result=result)
        except HTTPException:
            raise
        except Exception as exc:
            _record(command, "error", drone_ids, error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        backend = _CLIENT.health()
        return {
            "status": "ok",
            "service": "drone-control",
            "mode": os.getenv("DRONE_MODE", CONFIG.get("drones", {}).get("mode", "crazyswarm")),
            "valid_drone_ids": _DRONE_IDS,
            "backend": backend,
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "service": "drone-control",
            "valid_drone_ids": _DRONE_IDS,
            "backend_error": str(exc),
        }


@app.get("/status")
def service_status() -> Dict[str, Any]:
    return {
        "service": "drone-control",
        "valid_drone_ids": _DRONE_IDS,
        "last_command": _LAST_COMMAND,
    }


@app.get("/states")
def states() -> Dict[int, Dict[str, Any]]:
    try:
        return _CLIENT.get_states()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/states_vis")
def states_vis() -> Dict[int, Dict[str, Any]]:
    return states()


# Register the static collection route before /drones/{drone_id}/status.
@app.get("/drones/status")
def all_drone_statuses() -> Dict[str, Any]:
    current = states()
    drones = [current[drone_id] for drone_id in sorted(current)]
    return {"count": len(drones), "drones": drones}


@app.get("/drones/{drone_id}/status")
def drone_status(drone_id: int) -> Dict[str, Any]:
    _ids_or_all([drone_id])
    try:
        return _CLIENT.get_drone_status(int(drone_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/setup_hover")
def setup_hover(req: DroneIdsRequest) -> Dict[str, Any]:
    ids = _ids_or_all(req.drone_ids)
    return _run("setup_hover", ids, lambda: _CLIENT.setup_hover(ids))


@app.post("/hover")
def hover(req: DroneIdsRequest) -> Dict[str, Any]:
    ids = _ids_or_all(req.drone_ids)
    return _run("hover", ids, lambda: _CLIENT.hover(ids))


@app.post("/move_to_xy_z")
def move_to_xy_z(req: MoveToRequest) -> Dict[str, Any]:
    ids = _ids_or_all([req.drone_id])
    return _run(
        "move_to_xy_z",
        ids,
        lambda: _CLIENT.move_to_xy_z(
            req.drone_id,
            req.x,
            req.y,
            req.z,
            req.velocity,
        ),
    )


@app.post("/land")
def land(req: LandRequest) -> Dict[str, Any]:
    ids = _ids_or_all(req.drone_ids)
    return _run("land", ids, lambda: _CLIENT.land(ids, disarm=req.disarm))


@app.post("/down")
def down(req: LandRequest) -> Dict[str, Any]:
    ids = _ids_or_all(req.drone_ids)
    return _run("down", ids, lambda: _CLIENT.down(ids, disarm=req.disarm))


@app.post("/shutdown")
def shutdown(req: ShutdownRequest) -> Dict[str, Any]:
    ids = _ids_or_all(req.drone_ids)
    return _run(
        "shutdown",
        ids,
        lambda: _CLIENT.shutdown(
            ids,
            land=req.land,
            disarm=req.disarm,
            release_api_control=req.release_api_control,
        ),
    )
