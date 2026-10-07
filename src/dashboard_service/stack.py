"""Start and stop the six-Docker stack from the dashboard.

Only works when the dashboard runs on the host (scripts/dashboard.sh): a
dashboard container cannot run `docker compose down` on itself and survive it.

Modelled on the mission console in CrazySwarm2-with-Mocap: every button runs
the same script a person would type, and the page shows that exact command,
built here, before it runs. Nothing is re-implemented: startup_all.sh and
shutdown_all.sh stay the one way the stack is started and stopped.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

REPO = Path(os.getenv("DASHBOARD_REPO", Path(__file__).resolve().parents[2]))
ENV_FILE = REPO / ".env"
MAX_LINES = 3000
MAX_JOBS = 20

# .env keys the Stack page shows. Anything else in .env (the API key) stays unread.
ENV_SHOWN = ("DRONE_MODE", "MISSION_AUTO_START", "AUTO_DOWN_IDS", "AUTO_DOWN_COUNT",
             "AUTO_DOWN_AFTER_SEC", "CRAZYSWARM_API_URL")

MODES = ("crazyswarm", "mock", "airsim")

# The CrazySwarm2 workspace that holds the bridge (api/): beside this repo, as
# install_bridge.sh and swarm_config.py assume, unless CRAZYSWARM_REPO says otherwise.
CRAZYSWARM_REPO = Path(os.getenv("CRAZYSWARM_REPO", REPO.parent / "CrazySwarm2-with-Mocap"))
BRIDGE_PY = "/usr/bin/python3"   # never conda's: rclpy lives in ROS's python

# Job kinds that start or stop the Docker stack: only one of these at a time.
STACK_KINDS = ("start", "stop")


class StackError(Exception):
    """Something the user can fix, shown on the page instead of a 500."""


def read_env() -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        text = ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in ENV_SHOWN:
            values[key.strip()] = value.strip().strip("'\"")
    return values


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def start_argv(values: Dict[str, Any]) -> List[str]:
    mode = values.get("mode") or "crazyswarm"
    if mode not in MODES:
        raise StackError(f"unknown mode {mode!r}; use one of {', '.join(MODES)}")
    auto = str(values.get("auto_start", "0"))
    if auto not in ("0", "1"):
        raise StackError("auto take-off must be 0 or 1")
    # The shell environment beats --env-file in compose interpolation, so this
    # sets MISSION_AUTO_START for this start only and leaves .env as it is.
    argv = ["env", f"MISSION_AUTO_START={auto}", "./scripts/startup_all.sh", f"--{mode}",
            "--no-dashboard"]
    if str(values.get("build", "True")) != "True":
        argv.append("--no-build")
    if str(values.get("visualizer", "False")) == "True":
        argv.append("--with-visualizer")
    return argv


def stop_argv(values: Dict[str, Any]) -> List[str]:
    argv = ["./scripts/shutdown_all.sh"]
    if str(values.get("land", "True")) != "True":
        argv.append("--no-land")
    return argv


def bridge_port() -> int:
    """The port Docker 1 expects the bridge on (CRAZYSWARM_API_URL in .env)."""
    url = read_env().get("CRAZYSWARM_API_URL", "")
    tail = url.rsplit(":", 1)[-1].split("/", 1)[0] if ":" in url.split("//", 1)[-1] else ""
    return int(tail) if tail.isdigit() else 8011


def bridge_argv(values: Optional[Dict[str, Any]] = None) -> List[str]:
    """README "Start sequence" step 2, as one command.

    PYTHONPATH is cleared so this dashboard's own src/ does not leak into the
    bridge; install/setup.bash then sets it for ROS.
    """
    ws = shlex.quote(str(CRAZYSWARM_REPO))
    script = (f"source {ws}/install/setup.bash && cd {ws} && "
              f"exec {BRIDGE_PY} -m uvicorn api.app:app --host 127.0.0.1 --port {bridge_port()}")
    return ["env", "-u", "PYTHONPATH", "bash", "-c", script]


def install_argv(values: Optional[Dict[str, Any]] = None) -> List[str]:
    return ["./scripts/install_bridge.sh", "--deps", "--repo", str(CRAZYSWARM_REPO)]


# --------------------------------------------------------------------------
# Jobs: one script run, its output kept for the page
# --------------------------------------------------------------------------
class Job:
    _next = 1

    def __init__(self, kind: str, argv: List[str]) -> None:
        self.id = f"j{Job._next}"
        Job._next += 1
        self.kind = kind
        self.argv = argv
        self.cmdline = shlex.join(argv)
        self.lines: Deque[Tuple[int, float, str]] = deque(maxlen=MAX_LINES)
        self.seq = 0
        self.started = time.time()
        self.ended: Optional[float] = None
        self.returncode: Optional[int] = None
        self.cancelled = False
        self._lock = threading.Lock()
        self._add(f"$ {self.cmdline}")
        # Own session, so a cancel reaches docker compose and curl as well as bash.
        self.proc = subprocess.Popen(
            argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True,
            env={**os.environ, "COMPOSE_ANSI": "never", "COMPOSE_PROGRESS": "plain"},
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _add(self, text: str) -> None:
        with self._lock:
            self.seq += 1
            self.lines.append((self.seq, time.time(), text))

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._add(line.rstrip("\n"))
        self.returncode = self.proc.wait()
        self.ended = time.time()
        self._add(f"[exit {self.returncode}]" + (" (cancelled)" if self.cancelled else ""))

    @property
    def running(self) -> bool:
        return self.returncode is None

    def cancel(self) -> None:
        if not self.running:
            return
        self.cancelled = True
        self._add("[dashboard] cancelling: SIGTERM to the process group")
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def summary(self) -> Dict[str, Any]:
        state = "running" if self.running else ("cancelled" if self.cancelled
                                                else "done" if self.returncode == 0 else "failed")
        return {"id": self.id, "kind": self.kind, "cmdline": self.cmdline, "state": state,
                "returncode": self.returncode, "started": self.started, "ended": self.ended,
                "line_count": self.seq}

    def tail(self, after: int) -> List[Dict[str, Any]]:
        with self._lock:
            return [{"seq": s, "ts": t, "text": x} for s, t, x in self.lines if s > after]


_jobs: List[Job] = []
_jobs_lock = threading.Lock()


def _running(kinds: Tuple[str, ...] = STACK_KINDS) -> Optional[Job]:
    return next((j for j in _jobs if j.running and j.kind in kinds), None)


def _launch(kind: str, argv: List[str]) -> Job:
    job = Job(kind, argv)
    _jobs.append(job)
    del _jobs[:-MAX_JOBS]
    return job


def start(values: Dict[str, Any]) -> Dict[str, Any]:
    argv = start_argv(values)
    with _jobs_lock:
        busy = _running()
        if busy:
            raise StackError(f"{busy.kind} is still running ({busy.id}); wait for it or cancel it")
        return _launch("start", argv).summary()


def stop(values: Dict[str, Any]) -> Dict[str, Any]:
    """Stop always runs: a half-finished start is cancelled first, never waited on."""
    argv = stop_argv(values)
    with _jobs_lock:
        busy = _running()
        if busy and busy.kind == "stop":
            raise StackError(f"a stop is already running ({busy.id})")
        if busy:
            busy.cancel()
            try:
                busy.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(busy.proc.pid, signal.SIGKILL)
        return _launch("stop", argv).summary()


def bridge_start(values: Dict[str, Any]) -> Dict[str, Any]:
    with _jobs_lock:
        if _running(("bridge",)):
            raise StackError("the bridge is already running from this page")
        if _listener_pid(bridge_port()):
            raise StackError(f"port {bridge_port()} is already in use: a bridge started "
                             "elsewhere is probably running. Stop it first")
        if not (CRAZYSWARM_REPO / "api" / "app.py").exists():
            raise StackError(f"the bridge is not installed ({CRAZYSWARM_REPO}/api/app.py is "
                             "missing). Push Install or update the bridge first")
        if not (CRAZYSWARM_REPO / "install" / "setup.bash").exists():
            raise StackError(f"{CRAZYSWARM_REPO}/install/setup.bash is missing: build the "
                             "CrazySwarm2 workspace first (./scripts/setup.sh there)")
        return _launch("bridge", bridge_argv()).summary()


def bridge_stop(values: Dict[str, Any]) -> Dict[str, Any]:
    """Stop the bridge whether this page started it or someone started it by hand."""
    with _jobs_lock:
        job = _running(("bridge",))
        if job:
            job.cancel()
            return {"stopped": "job", **job.summary()}
        pid = _listener_pid(bridge_port())
        if not pid:
            raise StackError("the bridge is not running")
        cmd = _cmdline_of(pid)
        if "api.app" not in cmd:
            raise StackError(f"port {bridge_port()} is held by pid {pid}, which is not the "
                             f"bridge ({cmd or 'unknown'}); not stopping it")
        os.kill(pid, signal.SIGTERM)
        return {"stopped": "pid", "pid": pid, "cmdline": f"kill -TERM {pid}  # {cmd}"}


def install(values: Dict[str, Any]) -> Dict[str, Any]:
    with _jobs_lock:
        if _running(("install",)):
            raise StackError("an install is already running")
        return _launch("install", install_argv()).summary()


def _listener_pid(port: int) -> Optional[int]:
    """PID listening on 127.0.0.1:<port>, from `ss` (only our own processes show a pid)."""
    try:
        out = subprocess.run(["ss", "-Hltnp", f"sport = :{port}"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for token in out.replace(",", " ").split():
        if token.startswith("pid="):
            return int(token[4:])
    return -1 if out.strip() else None   # held, but by someone else's process


def _cmdline_of(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
    except OSError:
        return ""


_bridge_cache: Tuple[float, Dict[str, Any]] = (0.0, {})


def bridge_status() -> Dict[str, Any]:
    global _bridge_cache
    if time.time() - _bridge_cache[0] < 1.5:
        return _bridge_cache[1]
    port = bridge_port()
    job = _running(("bridge",))
    info: Dict[str, Any] = {
        "workspace": str(CRAZYSWARM_REPO), "port": port,
        "installed": (CRAZYSWARM_REPO / "api" / "app.py").exists(),
        "job": job.id if job else None, "listening": bool(_listener_pid(port)),
        "health": None, "error": None,
        "health_cmd": f"curl http://127.0.0.1:{port}/health",
    }
    if info["listening"]:
        try:
            import requests  # the dashboard already depends on it
            info["health"] = requests.get(f"http://127.0.0.1:{port}/health", timeout=1.0).json()
        except Exception as exc:              # noqa: BLE001 - shown on the page as text
            info["error"] = str(exc)
    _bridge_cache = (time.time(), info)
    return info


def cancel(job_id: str) -> Dict[str, Any]:
    job = get(job_id)
    job.cancel()
    return job.summary()


def get(job_id: str) -> Job:
    for job in _jobs:
        if job.id == job_id:
            return job
    raise StackError(f"no job {job_id}")


def jobs() -> List[Dict[str, Any]]:
    return [j.summary() for j in _jobs]


# --------------------------------------------------------------------------
# What is up right now
# --------------------------------------------------------------------------
PS_ARGV = ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml",
           "--profile", "visualizer", "ps", "--all", "--format", "json"]
_ps_cache: Tuple[float, Dict[str, Any]] = (0.0, {})


def containers() -> Dict[str, Any]:
    global _ps_cache
    if time.time() - _ps_cache[0] < 2.0:
        return _ps_cache[1]
    result: Dict[str, Any] = {"cmdline": shlex.join(PS_ARGV), "containers": [], "error": None}
    try:
        out = subprocess.run(PS_ARGV, cwd=REPO, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
    else:
        if out.returncode != 0:
            result["error"] = (out.stderr or out.stdout).strip() or f"exit {out.returncode}"
        else:
            result["containers"] = _parse_ps(out.stdout)
    _ps_cache = (time.time(), result)
    return result


def _parse_ps(text: str) -> List[Dict[str, Any]]:
    """Compose prints one JSON object per line (v2.21+) or one JSON array (older)."""
    text = text.strip()
    if not text:
        return []
    rows = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
    keep = ("Service", "Name", "State", "Status", "Health", "Publishers")
    out = []
    for row in rows:
        item = {k: row.get(k) for k in keep}
        item["Ports"] = ", ".join(
            f"{p.get('URL') or ''}:{p.get('PublishedPort')}->{p.get('TargetPort')}"
            for p in (row.get("Publishers") or []) if p.get("PublishedPort"))
        item.pop("Publishers")
        out.append(item)
    return sorted(out, key=lambda r: r.get("Service") or "")


def status() -> Dict[str, Any]:
    ps = containers()
    running = [c for c in ps["containers"] if c.get("State") == "running"]
    return {"env": read_env(), "containers": ps, "running_count": len(running),
            "jobs": jobs(), "repo": str(REPO), "bridge": bridge_status()}
