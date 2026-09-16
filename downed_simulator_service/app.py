from __future__ import annotations

import os
import random
import time
from threading import Thread
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from drone_common.config import get_drone_ids, load_config

MISSION_SERVICE_URL = os.getenv("MISSION_SERVICE_URL", "http://mission:8000").rstrip("/")
AUTO_DOWN_IDS = os.getenv("AUTO_DOWN_IDS", "").strip()
AUTO_DOWN_COUNT = os.getenv("AUTO_DOWN_COUNT", "").strip()
AUTO_DOWN_AFTER_SEC = float(os.getenv("AUTO_DOWN_AFTER_SEC", "0"))
CONFIG = load_config()
VALID_DRONE_IDS = get_drone_ids(CONFIG)

app = FastAPI(title="Docker 5 - Downed Drone Simulator")


class DownRequest(BaseModel):
    drone_ids: Optional[List[int]] = None
    count: Optional[int] = Field(default=None, ge=1)
    disarm: bool = True


def _choose_ids(req: DownRequest) -> List[int]:
    if req.drone_ids:
        ids = [int(value) for value in req.drone_ids]
    elif req.count:
        count = min(int(req.count), len(VALID_DRONE_IDS))
        ids = sorted(random.sample(VALID_DRONE_IDS, count))
    else:
        raise HTTPException(status_code=400, detail="Provide either drone_ids or count")

    invalid = [value for value in ids if value not in VALID_DRONE_IDS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown drone IDs: {invalid}. Valid IDs: {VALID_DRONE_IDS}",
        )
    return ids


def _call_mission(ids: List[int], disarm: bool) -> Dict[str, Any]:
    response = requests.post(
        f"{MISSION_SERVICE_URL}/simulate_downed",
        json={"drone_ids": [int(value) for value in ids], "disarm": bool(disarm)},
        timeout=300.0,
    )
    response.raise_for_status()
    return response.json()


def _auto_down_worker() -> None:
    time.sleep(max(0.0, AUTO_DOWN_AFTER_SEC))
    ids: List[int] = []
    if AUTO_DOWN_IDS:
        ids = [int(value) for value in AUTO_DOWN_IDS.replace(" ", "").split(",") if value]
    elif AUTO_DOWN_COUNT:
        count = min(int(AUTO_DOWN_COUNT), len(VALID_DRONE_IDS))
        ids = sorted(random.sample(VALID_DRONE_IDS, count))

    if ids:
        try:
            _call_mission(ids, disarm=True)
        except Exception as exc:
            print(f"[downed-simulator] auto-down failed: {exc}", flush=True)


@app.on_event("startup")
def startup() -> None:
    if AUTO_DOWN_IDS or AUTO_DOWN_COUNT:
        Thread(target=_auto_down_worker, daemon=True).start()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "downed-simulator",
        "mission_service_url": MISSION_SERVICE_URL,
    }


@app.post("/down")
def down(req: DownRequest) -> Dict[str, Any]:
    ids = _choose_ids(req)
    try:
        return {
            "status": "ok",
            "requested_downed_ids": ids,
            "mission_result": _call_mission(ids, req.disarm),
        }
    except requests.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"Mission service rejected the down request: {body}",
        ) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Mission service request failed: {exc}",
        ) from exc


@app.post("/land")
def land_alias(req: DownRequest) -> Dict[str, Any]:
    return down(req)
