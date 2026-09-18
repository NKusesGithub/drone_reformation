#!/usr/bin/env bash
# Put the CrazySwarm HTTP bridge (api/) into the CrazySwarm2 workspace.
#
# The bridge is not part of the CrazySwarm2-with-Mocap repo: it lives on a
# branch of another fork. This fetches just its api/ folder into the workspace,
# which is the one thing Docker 1 talks to. Re-run it to pick up later changes.
set -Eeuo pipefail

REMOTE="kojk"
URL="https://github.com/Kojk-STEngg/CrazySwarm2.git"
BRANCH="kenneth"
SUBDIR="api"
REPO="${CRAZYSWARM_REPO:-}"
INSTALL_DEPS=0
DRY_RUN=0
FORCE=0
PYTHON="/usr/bin/python3"   # never conda's python: rclpy lives in ROS's

usage() {
  cat <<'EOF'
Usage: ./scripts/install_bridge.sh [options]

Copies the CrazySwarm HTTP bridge (api/) from the Kojk-STEngg fork into your
CrazySwarm2 workspace. Safe to re-run: it updates to the latest commit.

Options:
  --repo DIR      CrazySwarm2 workspace (default: CrazySwarm2-with-Mocap beside
                  this repo, or $CRAZYSWARM_REPO)
  --deps          Also pip install --user -r api/requirements.txt
  --branch NAME   Branch to take api/ from (default: kenneth)
  --url URL       Fork to fetch from (default: Kojk-STEngg/CrazySwarm2)
  --remote NAME   Git remote name to use (default: kojk)
  --python PATH   Python for --deps (default: /usr/bin/python3)
  --dry-run       Say what would happen, change nothing
  --force         Overwrite local edits to api/, or a remote pointing elsewhere
  -h, --help      Show this help
EOF
}

log()  { printf '[bridge] %s\n' "$*"; }
warn() { printf '[bridge][warning] %s\n' "$*" >&2; }
fail() { printf '[bridge][error] %s\n' "$*" >&2; exit 1; }
run()  { if (( DRY_RUN )); then printf '[bridge][dry-run] %s\n' "$*"; else "$@"; fi; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --deps) INSTALL_DEPS=1; shift ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --url) URL="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)" ;;
  esac
done

command -v git >/dev/null 2>&1 || fail "git is not installed"

# ---------------------------------------------------------------- find the repo
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$REPO" ]]; then
  # Same rule as scripts/swarm_config.py: look beside this repo, then one level up.
  for candidate in "$HERE/../../CrazySwarm2-with-Mocap" "$HERE/../CrazySwarm2-with-Mocap" \
                   "$HOME/S_ENG/CrazySwarm2-with-Mocap"; do
    if [[ -d "$candidate/.git" ]]; then REPO="$candidate"; break; fi
  done
fi
[[ -n "$REPO" ]] || fail "CrazySwarm2 workspace not found. Pass --repo DIR or set CRAZYSWARM_REPO."
REPO="$(cd "$REPO" 2>/dev/null && pwd)" || fail "No such directory: $REPO"
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "Not a git repository: $REPO"
log "workspace: $REPO"

# --------------------------------------------------------- protect local edits
if [[ -d "$REPO/$SUBDIR" ]] && ! git -C "$REPO" diff --quiet -- "$SUBDIR" 2>/dev/null; then
  if (( FORCE )); then
    warn "$SUBDIR/ has uncommitted edits; overwriting because --force was given"
  else
    fail "$SUBDIR/ has uncommitted edits. Commit or stash them, or pass --force."
  fi
fi

# ----------------------------------------------------------------- git remote
if existing=$(git -C "$REPO" remote get-url "$REMOTE" 2>/dev/null); then
  if [[ "$existing" != "$URL" ]]; then
    if (( FORCE )); then
      log "repointing remote '$REMOTE': $existing -> $URL"
      run git -C "$REPO" remote set-url "$REMOTE" "$URL"
    else
      fail "remote '$REMOTE' already points at $existing (use --force, or --remote NAME)"
    fi
  else
    log "remote '$REMOTE' already set"
  fi
else
  log "adding remote '$REMOTE' -> $URL"
  run git -C "$REPO" remote add "$REMOTE" "$URL"
fi

log "fetching $REMOTE/$BRANCH"
run git -C "$REPO" fetch --quiet "$REMOTE" "$BRANCH"

if (( DRY_RUN )); then
  log "dry run: nothing was written"
  exit 0
fi

before=""
[[ -f "$REPO/$SUBDIR/app.py" ]] && before="$(git -C "$REPO" hash-object "$SUBDIR/app.py")"

log "copying $SUBDIR/ out of $REMOTE/$BRANCH"
git -C "$REPO" checkout "$REMOTE/$BRANCH" -- "$SUBDIR/"

[[ -f "$REPO/$SUBDIR/app.py" ]] || fail "$SUBDIR/app.py is missing after the copy; wrong branch?"

after="$(git -C "$REPO" hash-object "$SUBDIR/app.py")"
if [[ -n "$before" && "$before" == "$after" ]]; then
  log "already up to date"
else
  log "updated: $(git -C "$REPO" log -1 --format='%h %s' "$REMOTE/$BRANCH")"
fi

# ------------------------------------------------- does it still fit our stack?
missing=()
for route in "/health" "/drones/status" "/drones/{drone_id}/status" "/drones/{drone_id}/arm" \
             "/drones/{drone_id}/takeoff" "/drones/{drone_id}/go-to" "/drones/{drone_id}/land"; do
  grep -qF "\"$route\"" "$REPO/$SUBDIR/app.py" || missing+=("$route")
done
if (( ${#missing[@]} )); then
  warn "this bridge does not expose: ${missing[*]}"
  warn "Docker 1 calls those, so the stack will fail. Check --branch."
else
  log "all the routes Docker 1 uses are present"
fi

# ------------------------------------------------------------------ python deps
if (( INSTALL_DEPS )); then
  [[ -x "$PYTHON" ]] || fail "not executable: $PYTHON (pass --python PATH)"
  log "installing bridge requirements with $PYTHON"
  "$PYTHON" -m pip install --user -q -r "$REPO/$SUBDIR/requirements.txt"
  log "requirements installed"
else
  log "skipped requirements (pass --deps to install them)"
fi

# ----------------------------------------------------------------- what's next
port="8011"
env_file="$HERE/../.env"
if [[ -f "$env_file" ]] && grep -q '^CRAZYSWARM_API_URL=' "$env_file"; then
  port="$(sed -n 's#^CRAZYSWARM_API_URL=.*:\([0-9]\+\).*#\1#p' "$env_file" | head -1)"
  port="${port:-8011}"
fi

cat <<EOF

[bridge] Done. $SUBDIR/ is staged in $REPO (not committed).

Start it in its own terminal, after the CrazySwarm server is up:

  source $REPO/install/setup.bash
  cd $REPO
  $PYTHON -m uvicorn api.app:app --host 127.0.0.1 --port $port

Then check it before starting this stack:

  curl -s 127.0.0.1:$port/health          # "ready": true
  curl -s 127.0.0.1:$port/drones/status   # positions, one entry per enabled drone

Your .env expects the bridge on port $port (CRAZYSWARM_API_URL).
EOF
