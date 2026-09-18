#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
CONFIG_FILE="config.yaml"
BUILD=1
DETACHED=1
WAIT=1
WITH_VISUALIZER=0
SERVICES=(drone-control hungarian formation mission downed-simulator dashboard)

usage() {
  cat <<'EOF'
Usage: ./scripts/startup_all.sh [options]

Options:
  --crazyswarm        Set DRONE_MODE=crazyswarm in .env
  --mock              Set DRONE_MODE=mock in .env
  --airsim            Set DRONE_MODE=airsim in .env
  --no-build          Skip docker compose build
  --foreground        Run docker compose up in foreground
  --with-visualizer   Also start Docker 6 OpenCV visualizer profile
  --no-wait           Do not wait for health endpoints
  --compose FILE      Use a different compose file
  --env FILE          Use a different env file
  --config FILE       Use a different config file for existence check
  -h, --help          Show this help
EOF
}

log() { printf '[startup] %s\n' "$*"; }
fail() { printf '[startup][error] %s\n' "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

set_env_value() {
  local key="$1"
  local value="$2"
  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

wait_health() {
  local name="$1"
  local url="$2"
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name healthy: $url"
      return 0
    fi
    sleep 1
  done
  fail "$name did not become healthy: $url"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --crazyswarm) set_env_value DRONE_MODE crazyswarm; shift ;;
    --mock) set_env_value DRONE_MODE mock; shift ;;
    --airsim) set_env_value DRONE_MODE airsim; shift ;;
    --no-build) BUILD=0; shift ;;
    --foreground) DETACHED=0; shift ;;
    --with-visualizer) WITH_VISUALIZER=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --env) ENV_FILE="$2"; shift 2 ;;
    --config) CONFIG_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

need_cmd docker
need_cmd curl
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example "$ENV_FILE"
    log "Created $ENV_FILE from .env.example"
  else
    touch "$ENV_FILE"
    log "Created empty $ENV_FILE"
  fi
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  [[ -f config.example.yaml ]] || fail "Missing $CONFIG_FILE and config.example.yaml"
  cp config.example.yaml "$CONFIG_FILE"
  log "Created $CONFIG_FILE from config.example.yaml"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

if (( BUILD )); then
  log "Building six-Docker stack"
  "${COMPOSE[@]}" build "${SERVICES[@]}"
  if (( WITH_VISUALIZER )); then
    "${COMPOSE[@]}" --profile visualizer build visualizer
  fi
fi

UP_ARGS=(up)
if (( DETACHED )); then UP_ARGS+=(-d); fi
if (( WITH_VISUALIZER )); then
  log "Starting services including Docker 6 visualizer"
  "${COMPOSE[@]}" --profile visualizer "${UP_ARGS[@]}" "${SERVICES[@]}" visualizer
else
  log "Starting services"
  "${COMPOSE[@]}" "${UP_ARGS[@]}" "${SERVICES[@]}"
fi

if (( WAIT )) && (( DETACHED )); then
  wait_health "Docker 1 drone-control" "http://localhost:8001/health"
  wait_health "Docker 2 hungarian" "http://localhost:8002/health"
  wait_health "Docker 3 formation" "http://localhost:8003/health"
  wait_health "Docker 4 mission" "http://localhost:8004/health"
  wait_health "Docker 5 downed-simulator" "http://localhost:8005/health"
  wait_health "Dashboard" "http://localhost:8006/health"
fi

cat <<EOF
[startup] Ready.

Dashboard (buttons + live status): http://localhost:8006

Docker 1 drone-control:      http://localhost:8001/status
Docker 2 hungarian:          http://localhost:8002/health
Docker 3 formation:          http://localhost:8003/health
Docker 4 mission:            http://localhost:8004/status
Docker 5 downed simulator:   http://localhost:8005/health

Simulate downed drones through Docker 5:
  curl -X POST http://localhost:8005/down \
    -H 'Content-Type: application/json' \
    -d '{"drone_ids":[2],"disarm":true}'

Check mission reform:
  curl http://localhost:8004/last_reform | python -m json.tool
  curl http://localhost:8004/last_move | python -m json.tool
EOF
