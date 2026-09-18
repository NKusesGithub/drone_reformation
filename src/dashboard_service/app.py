from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
