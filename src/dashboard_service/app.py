from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from dashboard_service import configio, swarm_sync

STATIC_DIR = Path(__file__).resolve().parent / "static"

UPSTREAMS: Dict[str, str] = {
    "control": os.getenv("DRONE_CONTROL_URL", "http://host.docker.internal:8001").rstrip("/"),
    "mission": os.getenv("MISSION_SERVICE_URL", "http://mission:8000").rstrip("/"),
    "simulator": os.getenv("DOWNED_SIMULATOR_URL", "http://downed-simulator:8000").rstrip("/"),
}

# Checked by the debug panel only: never forwarded, and not in ALLOWED. The
# bridge URL points at the host, not the docker network, because the
# dashboard container does not share drone-control's network_mode: host.
DEBUG_URLS: Dict[str, str] = {
    "hungarian": os.getenv("HUNGARIAN_SERVICE_URL", "http://hungarian:8000").rstrip("/"),
    "formation": os.getenv("FORMATION_SERVICE_URL", "http://formation:8000").rstrip("/"),
    "bridge": os.getenv("CRAZYSWARM_BRIDGE_URL", "http://host.docker.internal:8011").rstrip("/"),
}

DEBUG_TIMEOUT = 2.0

# (name, port, health URL). A None URL is answered locally, for the dashboard
# itself. Order matches the brief: ports 8001 to 8006, then the bridge.
DEBUG_TARGETS: List[Tuple[str, int, Optional[str]]] = [
    ("drone-control", 8001, f"{UPSTREAMS['control']}/health"),
    ("hungarian", 8002, f"{DEBUG_URLS['hungarian']}/health"),
    ("formation", 8003, f"{DEBUG_URLS['formation']}/health"),
    ("mission", 8004, f"{UPSTREAMS['mission']}/health"),
    ("downed-simulator", 8005, f"{UPSTREAMS['simulator']}/health"),
    ("dashboard", 8006, None),
    ("crazyswarm-bridge", 8011, f"{DEBUG_URLS['bridge']}/health"),
]

# The known faults from docs/AGENT_BRIEF.md Task B, because a person cannot
# find them without help.
DEBUG_CHECKLIST: List[Dict[str, str]] = [
    {
        "symptom": "The mission /health route always answers ok, also when its worker is dead",
        "check": "Read /status and look at running and last_error. Never rely on /health",
    },
    {
        "symptom": "drone-control reports degraded",
        "check": "The CrazySwarm bridge on 8011 is not running, or CRAZYSWARM_API_URL gives the incorrect port",
    },
    {
        "symptom": "Each drone is down on the second run",
        "check": "The bridge never clears a down mark. Start the bridge again",
    },
    {
        "symptom": "The reform fails with Formation returned too few slots",
        "check": "sum(mission.old_formation) is not equal to len(drones.ids)",
    },
    {
        "symptom": "last_move gives timeout and blocked_count increases",
        "check": "The shape of the formation has a row that repeats or that gets narrower. "
        "Such a shape makes a drone stuck. Use [1,2], [1,2,3] or [N]",
    },
    {
        "symptom": "Mission last_error gives Connection refused to hungarian",
        "check": "A race at startup. Run docker compose restart mission",
    },
    {
        "symptom": "A restart did not do the takeoff again",
        "check": "The one-time flags never reset. Use docker compose restart mission",
    },
]

# (method, service, path) -> timeout in seconds.
#
# Only these requests are forwarded, so the page can do exactly what its buttons
# do and nothing else. In particular it cannot send /move_to_xy_z or /setup_hover
# straight to Docker 1.
ALLOWED: Dict[Tuple[str, str, str], float] = {
    ("GET", "control", "/health"): 5.0,
    ("GET", "control", "/drones/status"): 5.0,
    ("GET", "mission", "/status"): 5.0,
    ("GET", "mission", "/last_reform"): 5.0,
    ("GET", "mission", "/last_move"): 5.0,
    ("GET", "simulator", "/health"): 5.0,
    ("POST", "mission", "/start"): 10.0,
    ("POST", "mission", "/stop"): 10.0,
    # These three wait until drones have moved or landed, which can take minutes.
    ("POST", "mission", "/reform_now"): 600.0,
    ("POST", "mission", "/shutdown"): 330.0,
    ("POST", "simulator", "/down"): 330.0,
}

app = FastAPI(title="Dashboard - buttons for the common steps")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> Dict[str, object]:
    return {"status": "ok", "service": "dashboard", "upstreams": UPSTREAMS}


async def _json_body(request: Request) -> Dict[str, Any]:
    """Parse a button's body, insisting on JSON.

    A plain HTML form on another website can POST to localhost without the
    browser asking first, but it cannot send application/json. Requiring it means
    only this page's own buttons can trigger an action.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="Actions must be sent as application/json")
    raw = await request.body()
    try:
        return json.loads(raw) if raw else {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Request body is not valid JSON: {exc}") from exc


def _formation_from(payload: Dict[str, Any]) -> Optional[list]:
    formation = payload.get("formation")
    if formation in (None, "", []):
        return None
    if isinstance(formation, str):
        formation = [part for part in formation.replace(" ", "").split(",") if part]
    try:
        return [int(v) for v in formation]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="Rows must be whole numbers, for example 2, 3"
        ) from exc


# The dashboard's own actions, not forwarded anywhere. They must be declared
# before /api/{service}/{path}, which would otherwise swallow them.
@app.get("/api/config/file/{key}")
def config_file(key: str) -> Dict[str, Any]:
    """The raw text of config.yaml, or of CrazySwarm's crazyflies.yaml (read-only)."""
    try:
        return configio.read_file(key)
    except configio.ConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/config/raw")
async def config_write_raw(request: Request) -> Dict[str, Any]:
    payload = await _json_body(request)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Nothing to save")
    try:
        return configio.write_raw(text)
    except configio.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config/parameters")
def config_parameters() -> Dict[str, Any]:
    try:
        return configio.read_parameters()
    except configio.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/parameters")
async def config_write_parameters(request: Request) -> Dict[str, Any]:
    payload = await _json_body(request)
    edits = payload.get("edits")
    if not isinstance(edits, list) or not edits:
        raise HTTPException(status_code=400, detail="No settings were changed")
    try:
        return configio.write_parameters(edits, dry_run=bool(payload.get("dry_run")))
    except configio.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/config/drones")
def config_preview() -> Dict[str, Any]:
    """What would change in config.yaml if the CrazySwarm drone list were copied over."""
    try:
        return swarm_sync.preview()
    except swarm_sync.SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/config/drones")
async def config_apply(request: Request) -> Dict[str, Any]:
    payload = await _json_body(request)
    try:
        return swarm_sync.apply(_formation_from(payload))
    except swarm_sync.SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _check_target(name: str, port: int, url: Optional[str]) -> Dict[str, Any]:
    """Whether one service answers, for the debug panel. Never raises."""
    if url is None:
        return {"name": name, "port": port, "ok": True, "detail": "answering"}
    try:
        response = requests.request("GET", url, timeout=DEBUG_TIMEOUT)
    except requests.RequestException as exc:
        return {"name": name, "port": port, "ok": False, "detail": str(exc)}
    if response.status_code >= 400:
        return {"name": name, "port": port, "ok": False, "detail": f"HTTP {response.status_code}"}
    return {"name": name, "port": port, "ok": True, "detail": "answering"}


@app.get("/api/debug/status")
async def debug_status() -> Dict[str, Any]:
    """Which services answer, for the dashboard's debugging panel.

    Declared before /api/{service}/{path}, which would otherwise swallow it:
    "debug" is not a forwarding target in UPSTREAMS.
    """
    services = await asyncio.gather(
        *(run_in_threadpool(_check_target, name, port, url) for name, port, url in DEBUG_TARGETS)
    )
    return {"services": list(services), "checklist": DEBUG_CHECKLIST}


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST"])
async def forward(service: str, path: str, request: Request) -> JSONResponse:
    method = request.method
    timeout = ALLOWED.get((method, service, f"/{path}"))
    if timeout is None:
        raise HTTPException(status_code=404, detail=f"{method} /{service}/{path} is not a dashboard action")

    payload = await _json_body(request) if method == "POST" else None

    url = f"{UPSTREAMS[service]}/{path}"
    try:
        response = await run_in_threadpool(
            requests.request, method, url, json=payload, timeout=timeout
        )
    except requests.RequestException as exc:
        return JSONResponse(status_code=502, content={"detail": f"{service} is unreachable: {exc}"})

    try:
        content = response.json()
    except ValueError:
        content = {"detail": response.text}
    return JSONResponse(status_code=response.status_code, content=content)
