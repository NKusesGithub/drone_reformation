# Drone Reformation Six-Docker Stack: CrazySwarm API Edition

> This document is written in ASD-STE100 Simplified Technical English.

This stack keeps the first architecture of six services. It replaces the old direct AirSim
control path with the current CrazySwarm FastAPI contract for each drone.

## Where to go next

This document gives the six services, the ports and the settings. Use it as your reference.

For the run-book on real hardware, refer to [QUICKSTART.md](docs/QUICKSTART.md). It gives one
step at a time, with a link to the reason for each step.

For the reason each part works this way, and the list of known traps, refer to
[README_EXPLAINED.md](docs/README_EXPLAINED.md).

```text
CrazySwarm ROS 2 + FastAPI (usually http://127.0.0.1:8011)
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

Only Docker 1 calls the CrazySwarm API. The mission, formation, Hungarian assignment, downed
simulation and visualization services use HTTP only. They do not import the ROS 2 libraries or
the CrazySwarm libraries.

## Important behavior of the API

Docker 1 uses the CrazySwarm status endpoint as the one correct source of data:

```text
idle  = no velocity-based go-to command is active
busy  = the calculated go-to duration did not expire
down  = the CrazySwarm API marked the drone as down or as landed
```

Mission does not use the AirSim `landed_state` field to find a lost drone. It finds
`status == "down"` through Docker 1.

Movement uses the current velocity-based command:

```text
POST /drones/{id}/go-to
```

Docker 1 changes its `/move_to_xy_z` gateway route into this request. Mission sends one
waypoint. Then it polls the status endpoint of the same drone until the status is `idle` or
`down`. Only then does it send the next waypoint.

## Services and ports

| Docker | Service | Host access |
|---|---|---|
| 1 | `drone-control` | `http://localhost:8001` |
| 2 | `hungarian` | `http://localhost:8002` |
| 3 | `formation` | `http://localhost:8003` |
| 4 | `mission` | `http://localhost:8004` |
| 5 | `downed-simulator` | `http://localhost:8005` |
| 6 | `visualizer` | Desktop OpenCV window |
| none | `dashboard` | `http://localhost:8006`: buttons for the usual steps |

The default address of the upstream CrazySwarm API is `http://127.0.0.1:8011`.

## The settings files

Copy the default files:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

The IDs in `config.yaml` must agree with the enabled drones in the CrazySwarm
`crazyflies.yaml` file:

```yaml
drones:
  ids: [1, 2, 3]
```

CrazySwarm uses a positive altitude above the floor. Thus the default is:

```yaml
drones:
  hover_z: 1.0
```

The default dimensions of the formation are in metres. They are scaled for Crazyflie
operation:

```yaml
mission:
  formation_spacing: 0.5
  safety_gap: 0.25
  waypoint_step: 0.25
  move_velocity: 0.5
```

### `anchor_policy`: what happens to the front when a drone goes down

`mission.anchor_policy` in `config.yaml` sets the position of the formation after a loss. The
system always builds the shape from the front. The front row has the highest y value.

| Value | After a drone goes down |
|---|---|
| `initial_anchor` (default) | The formation stays in the same position. Rows go away from the **back**. The front spot does not move |
| `active_centroid` | The formation gets a new centre on the drones that are left. Thus the front drone moves **forward** each time |
| `origin` | The middle of the front row is always at world (0, 0) |

With `initial_anchor`, the rows `[1, 2, 1]` and four drones give the same front spot each
time:

```text
4 flying  rows [1, 2, 1]   front spot (+0.24, +0.41)
3 flying  rows [1, 2]      front spot (+0.24, +0.41)   back row gone
2 flying  rows [1, 1]      front spot (+0.24, +0.41)
```

With `active_centroid`, the same case moves the front spot to (-0.05, +0.59), and then to
(+0.49, +0.73). The group keeps its middle above one point.

Two things change with `initial_anchor`:

- **Which drone is at the front.** The spots do not move. But the Hungarian solver matches the
  drones to the spots again at each reform. Thus a drone from the back flies into an empty
  front spot.
- **The width of the front row.** This changes only when few drones are left. The rows fill
  from the front at their first width. Thus a `[1, 2, 1]` front row keeps its single spot
  until only one drone is left.

### `MISSION_AUTO_START`: does the stack take off without a command?

This one setting in `.env` decides if a start of the stack is also a takeoff command.

| Value | What occurs when the mission container starts |
|---|---|
| `1` (default) | It waits for the backend of Docker 1. Then it **arms each drone, takes off, and flies the first formation**. You do not push a button |
| `0` | It does nothing until you push **Start mission** on the dashboard, or until you send `POST /start` |

Use `0` on a day with hardware. This keeps "the stack is running" and "the drones are flying"
separate. Thus you can look at `/status`, look at the dashboard, and do a test of Docker 1 by
hand before a drone leaves the ground:

```bash
curl -X POST localhost:8004/start -H 'Content-Type: application/json' -d '{"setup_hover":true}'
```

This is also important when the bridge is slow to start. With `1`, mission waits
`mission.control_ready_timeout` seconds (120 by default) for the backend. Then it stops and
writes the reason in `last_error`. It does not try again.

CAUTION: MAKE THE MISSION CONTAINER AGAIN AFTER YOU CHANGE THIS VALUE. DO NOT RESTART IT. THE
CONTAINER KEEPS THE ENVIRONMENT VALUES FROM THE TIME WHEN YOU MADE IT.

```bash
docker compose up -d mission        # uses the new value
docker compose restart mission      # does NOT: it uses the old value again
```

WARNING: WITH `MISSION_AUTO_START=1`, A RESTART OF MISSION IS ALSO A TAKEOFF COMMAND. THE
DRONES CAN MOVE WITHOUT A WARNING AND CAUSE INJURY. RESTART MISSION ONLY WHEN YOU ARE READY
TO FLY.

## Start sequence

The CrazySwarm bridge is not a part of that repository. Copy it in one time:

```bash
./scripts/install_bridge.sh --deps
```

Start the CrazySwarm simulator and API first. Then make sure that they answer:

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8011/drones/status | python3 -m json.tool
```

Then start this stack:

```bash
./scripts/startup_all.sh --crazyswarm
```

Then open **http://localhost:8006** for the dashboard. It has buttons to start the mission, to
down a drone, to reform, and to land all drones. It also shows the live drone status and a map.

To include Docker 6:

```bash
xhost +local:docker
./scripts/startup_all.sh --crazyswarm --with-visualizer
```

To do a smoke test without CrazySwarm:

```bash
./scripts/startup_all.sh --mock
```

## Do a test of Docker 1

```bash
curl http://localhost:8001/health | python3 -m json.tool
curl http://localhost:8001/states | python3 -m json.tool
curl http://localhost:8001/drones/status | python3 -m json.tool
curl http://localhost:8001/drones/1/status | python3 -m json.tool
```

To set up and take off all of the configured drones:

```bash
curl -X POST http://localhost:8001/setup_hover \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":null}'
```

To move one drone to an absolute position, send this request. Docker 1 changes it into the
current velocity-based CrazySwarm `/go-to` request:

```bash
curl -X POST http://localhost:8001/move_to_xy_z \
  -H 'Content-Type: application/json' \
  -d '{"drone_id":1,"x":0.5,"y":0.0,"z":1.0,"velocity":0.5}'
```

To look at the status of the drone:

```bash
watch -n 0.2 'curl -s http://localhost:8001/drones/1/status | python3 -m json.tool'
```

## How to simulate a downed drone

Docker 5 obeys the correct architecture:

```text
Docker 5 -> Docker 4 /simulate_downed -> Docker 1 /down -> CrazySwarm land and disarm
```

To down a selected drone:

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":[2],"disarm":true}'
```

To down two drones at random:

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"count":2,"disarm":true}'
```

Make sure that Docker 1 reports `down`:

```bash
curl http://localhost:8001/drones/2/status | python3 -m json.tool
```

Mission finds the change of status. Then it starts a new formation and a new Hungarian
assignment:

```bash
curl http://localhost:8004/status | python3 -m json.tool
curl http://localhost:8004/last_reform | python3 -m json.tool
curl http://localhost:8004/last_move | python3 -m json.tool
```

## Shutdown

```bash
./scripts/shutdown_all.sh
```

## Layout of the repository

```text
src/                        first-party Python, one package for each container
  drone_control_service/    Docker 1: gateway, the only caller of the CrazySwarm API
  hungarian_service/        Docker 2: assignment of a drone to a slot
  formation_service/        Docker 3: geometry of the formation
  mission_service/          Docker 4: orchestration
  downed_simulator_service/ Docker 5: fault injection
  visualizer_service/       Docker 6: OpenCV viewer
  dashboard_service/        web page: Status tab (buttons and live state) and Config tab
                            (edit config.yaml, copy drone IDs from CrazySwarm)
  drone_common/             config loader and HTTP client for 1, 4 and 5
third_party/airsim/         vendored AirSim 1.8.1 client, for the old DRONE_MODE=airsim only
tests/                      pytest suite (pip install -r requirements/dev.txt; pytest)
docker/                     one Dockerfile for each service
requirements/               one requirements file for each service, and base.txt and dev.txt
scripts/                    startup_all.sh, shutdown_all.sh, swarm_config.py
docs/                       QUICKSTART.md (run-book for hardware),
                            README_EXPLAINED.md (internal operation)
artefacts/                  output of the visualizer, in .gitignore
config.example.yaml         copy to config.yaml (in .gitignore)
.env.example                copy to .env (in .gitignore)
```

Each container has the same layout below `/app`. The packages are in `/app/src`. The system
mounts the config file at `/app/config.yaml`.
