# Drone Reformation Six-Docker Stack — CrazySwarm API Edition

This stack preserves the original six-service architecture while replacing the legacy direct AirSim control path with the current per-drone CrazySwarm FastAPI contract.

```text
CrazySwarm ROS 2 + FastAPI (normally http://127.0.0.1:8011)
        ↑
Docker 1: drone-control gateway
        ↑
Docker 4: mission orchestrator
        ↑
Docker 5: downed-simulator

Docker 4 also calls:
  Docker 2: hungarian
  Docker 3: formation

Docker 6: visualizer polls Docker 1 /states_vis
```

Only Docker 1 calls the CrazySwarm API. Mission, formation, Hungarian assignment, downed simulation, and visualization remain HTTP-only and do not import ROS 2 or CrazySwarm libraries.

## Important API behavior

The CrazySwarm status endpoint is treated as authoritative:

```text
idle  = no velocity-based go-to command is active
busy  = the computed go-to duration has not expired
down  = the drone has been marked down/landed by the CrazySwarm API
```

Mission no longer infers a lost drone from AirSim `landed_state`. It detects `status == "down"` through Docker 1.

Movement now uses the current velocity-based command:

```text
POST /drones/{id}/go-to
```

Docker 1 translates its preserved `/move_to_xy_z` gateway route into this request. Mission sends one waypoint, polls the same drone status endpoint until `idle` or `down`, and only then sends the next waypoint.

## Services and ports

| Docker | Service | Host access |
|---|---|---|
| 1 | `drone-control` | `http://localhost:8001` |
| 2 | `hungarian` | `http://localhost:8002` |
| 3 | `formation` | `http://localhost:8003` |
| 4 | `mission` | `http://localhost:8004` |
| 5 | `downed-simulator` | `http://localhost:8005` |
| 6 | `visualizer` | Desktop OpenCV window |

The upstream CrazySwarm API is expected at `http://127.0.0.1:8011` by default.

## Configuration

Copy the defaults:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Set the IDs in `config.yaml` to exactly match the enabled drones in the CrazySwarm `crazyflies.yaml` file:

```yaml
drones:
  ids: [1, 2, 3]
```

CrazySwarm uses positive altitude above the floor, so the default is:

```yaml
drones:
  hover_z: 1.0
```

The default formation dimensions are expressed in metres and are scaled for Crazyflie operation:

```yaml
mission:
  formation_spacing: 0.5
  safety_gap: 0.25
  waypoint_step: 0.25
  move_velocity: 0.5
```

## Start order

Start the CrazySwarm simulator/API first and verify:

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8011/drones/status | python3 -m json.tool
```

Then start this stack:

```bash
./scripts/startup_all.sh --crazyswarm
```

Include Docker 6:

```bash
xhost +local:docker
./scripts/startup_all.sh --crazyswarm --with-visualizer
```

Smoke-test without CrazySwarm:

```bash
./scripts/startup_all.sh --mock
```

## Test Docker 1

```bash
curl http://localhost:8001/health | python3 -m json.tool
curl http://localhost:8001/states | python3 -m json.tool
curl http://localhost:8001/drones/status | python3 -m json.tool
curl http://localhost:8001/drones/1/status | python3 -m json.tool
```

Setup and take off all configured drones:

```bash
curl -X POST http://localhost:8001/setup_hover \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":null}'
```

Move one drone to an absolute position. Docker 1 converts this to the current velocity-based CrazySwarm `/go-to` request:

```bash
curl -X POST http://localhost:8001/move_to_xy_z \
  -H 'Content-Type: application/json' \
  -d '{"drone_id":1,"x":0.5,"y":0.0,"z":1.0,"velocity":0.5}'
```

Watch its status:

```bash
watch -n 0.2 'curl -s http://localhost:8001/drones/1/status | python3 -m json.tool'
```

## Simulate a downed drone

Docker 5 now follows the intended architecture:

```text
Docker 5 -> Docker 4 /simulate_downed -> Docker 1 /down -> CrazySwarm land/disarm
```

Down a selected drone:

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":[2],"disarm":true}'
```

Randomly down two drones:

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"count":2,"disarm":true}'
```

Confirm that Docker 1 reports `down`:

```bash
curl http://localhost:8001/drones/2/status | python3 -m json.tool
```

Mission detects the status change and triggers formation regeneration and Hungarian reassignment:

```bash
curl http://localhost:8004/status | python3 -m json.tool
curl http://localhost:8004/last_reform | python3 -m json.tool
curl http://localhost:8004/last_move | python3 -m json.tool
```

## Shutdown

```bash
./scripts/shutdown_all.sh
```

## Main modified files

```text
drone_control_service/clients.py
  - Adds CrazySwarm HTTP backend
  - Normalizes /drones/status into the existing state representation
  - Maps takeoff, go-to, land, arm, and down behavior

drone_control_service/app.py
  - Preserves Docker 1 gateway routes
  - Adds /drones/status and /drones/{id}/status
  - Removes AirSim-local coordinate conversion from the gateway

drone_common/control_client.py
  - Adds per-drone status methods used by Mission
mission_service/app.py
  - Uses status = idle/busy/down
  - Waits for each velocity-based waypoint to complete
  - Aborts movement immediately when status becomes down
downed_simulator_service/app.py
  - Calls Mission instead of bypassing it
docker-compose.yml
  - Removes the duplicate drone-control2 service
  - Routes Docker 5 to Docker 4
```
