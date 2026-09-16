#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
LAND=1
REMOVE_VOLUMES=0

usage() {
  cat <<'EOF'
Usage: ./scripts/shutdown_all.sh [options]

Options:
  --no-land        Stop mission but do not land drones
  --volumes        Also remove Docker volumes
  --compose FILE   Use a different compose file
  --env FILE       Use a different env file
  -h, --help       Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-land) LAND=0; shift ;;
    --volumes) REMOVE_VOLUMES=1; shift ;;
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --env) ENV_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if (( LAND )); then
  curl -fsS -X POST http://localhost:8004/shutdown \
    -H 'Content-Type: application/json' \
    -d '{"land":true,"disarm":true,"release_api_control":true}' >/dev/null || true
else
  curl -fsS -X POST http://localhost:8004/stop >/dev/null || true
fi

DOWN_ARGS=(down --remove-orphans)
if (( REMOVE_VOLUMES )); then DOWN_ARGS+=(-v); fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile visualizer "${DOWN_ARGS[@]}"
echo "[shutdown] Done."
