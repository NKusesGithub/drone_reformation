#!/usr/bin/env bash
# The drone_reformation dashboard, run on the host: http://localhost:8006
#
# Pages: Stack (start/stop the six-Docker stack), Status, Config, Debug -- all
# there from the start, whether the stack is up or not. It runs on the host,
# not as a container, so it can run `docker compose down` and stay up, and so
# config.yaml can be edited before the stack exists. Start/stop go through
# startup_all.sh / shutdown_all.sh, and the page shows each exact command.
#
# The stack started from here leaves out its own dashboard container
# (--no-dashboard): this process already serves port 8006.
#
# Usage: ./scripts/dashboard.sh [port]      (default 8006)
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8006}"
PY=/usr/bin/python3   # not conda: the host python is the one with fastapi/uvicorn

fail() { printf '[dashboard][error] %s\n' "$*" >&2; exit 1; }

# Same default as docker-compose.yml, and the same CRAZYFLIES_DIR override from .env.
CRAZYFLIES_DIR="$(grep -E '^CRAZYFLIES_DIR=' "$REPO/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
CRAZYFLIES_DIR="${CRAZYFLIES_DIR:-../CrazySwarm2-with-Mocap/src/crazyswarm2/crazyflie/config}"
[[ "$CRAZYFLIES_DIR" = /* ]] || CRAZYFLIES_DIR="$REPO/$CRAZYFLIES_DIR"

[[ -f "$REPO/config.yaml" ]] || fail "no config.yaml: cp config.example.yaml config.yaml"
[[ -f "$CRAZYFLIES_DIR/crazyflies.yaml" ]] ||
  printf '[dashboard] note: %s not found; the "Drone IDs from CrazySwarm" card will not work\n' \
    "$CRAZYFLIES_DIR/crazyflies.yaml"
"$PY" -c 'import fastapi, uvicorn, requests, yaml' 2>/dev/null ||
  fail "host python lacks the dashboard packages: $PY -m pip install --user fastapi uvicorn requests PyYAML"
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  fail "port $PORT is in use. If a stack started with plain ./scripts/startup_all.sh is up, its dashboard container holds it: docker compose stop dashboard (or pass another port)"
fi

mkdir -p "$REPO/config_backups"
export DASHBOARD_HOST=1 \
       DASHBOARD_REPO="$REPO" \
       DRONE_CONTROL_URL=http://127.0.0.1:8001 \
       HUNGARIAN_SERVICE_URL=http://127.0.0.1:8002 \
       FORMATION_SERVICE_URL=http://127.0.0.1:8003 \
       MISSION_SERVICE_URL=http://127.0.0.1:8004 \
       DOWNED_SIMULATOR_URL=http://127.0.0.1:8005 \
       PYTHONPATH="$REPO/src" \
       CONFIG_YAML="$REPO/config.yaml" \
       CRAZYFLIES_YAML="$CRAZYFLIES_DIR/crazyflies.yaml" \
       CONFIG_BACKUP_DIR="$REPO/config_backups" \
       SWARM_CONFIG_PY="$REPO/scripts/swarm_config.py"

printf '[dashboard] http://localhost:%s  (Ctrl-C to stop; the stack keeps running)\n' "$PORT"
exec "$PY" -m uvicorn dashboard_service.app:app --host 127.0.0.1 --port "$PORT"
