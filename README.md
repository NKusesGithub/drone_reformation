# Drone Reformation Six-Docker Stack: CrazySwarm API Edition

> This document is written in ASD-STE100 Simplified Technical English.

## Start here

This project has three documents. Use the document that fits your task.

| Your task | Read this |
|---|---|
| Learn what to run, and the layout of the stack | This document |
| Set up and fly real Crazyflie drones, step by step | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| Learn why each part exists, and where the traps are | [docs/README_EXPLAINED.md](docs/README_EXPLAINED.md) |

To find a fault, use the fault tables.
[README_EXPLAINED §15](docs/README_EXPLAINED.md#15-checklist-for-faults) is for the stack.
[QUICKSTART, Find faults](docs/QUICKSTART.md#find-faults) is for the radio, ROS and the bridge.

## Contents

- [Start here](#start-here)
- [The architecture](#the-architecture)
- [Important behavior of the API](#important-behavior-of-the-api)
- [Services and ports](#services-and-ports)
- [What to install, and where](#what-to-install-and-where)
  - [What starts each part](#what-starts-each-part)
- [The settings files](#the-settings-files)
  - [`anchor_policy`: what happens to the front when a drone goes down](#anchor_policy-what-happens-to-the-front-when-a-drone-goes-down)
  - [`front_axis`: which direction is the front?](#front_axis-which-direction-is-the-front)
  - [`MISSION_AUTO_START`: does the stack take off without a command?](#mission_auto_start-does-the-stack-take-off-without-a-command)
- [Start sequence](#start-sequence)
- [Do a test of Docker 1](#do-a-test-of-docker-1)
- [How to simulate a downed drone](#how-to-simulate-a-downed-drone)
- [Shutdown](#shutdown)
- [Layout of the repository](#layout-of-the-repository)

## The architecture

This stack keeps the first architecture of six services. It replaces the old direct AirSim
control path with the current CrazySwarm FastAPI contract for each drone.

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

## What to install, and where

This stack has parts in two folders. The two folders must be in the same parent folder, for
example `~/S_ENG`. Install the parts in the sequence of this table.

| Step | Part | Where it goes | How to install it |
|---|---|---|---|
| 1 | ROS 2: Humble on Ubuntu 22.04, or Jazzy on Ubuntu 24.04 | `/opt/ros/<distro>` | By hand. Refer to the CrazySwarm2-with-Mocap README, Setup Step 1 |
| 2 | The CrazySwarm2 workspace: the ROS 2 server, the mocap driver and the preflight GUI | `~/S_ENG/CrazySwarm2-with-Mocap` | `./scripts/setup.sh` in that folder |
| 3 | The bridge (`api/`) and its Python packages | `~/S_ENG/CrazySwarm2-with-Mocap/api` | `./scripts/install_bridge.sh --deps` in this folder, or **Install or update the bridge** on the **Stack** page |
| 4 | Docker Engine, the Docker Compose v2 plugin, and `curl` | The host | Refer to <https://docs.docker.com/engine/install/ubuntu/>. Then `sudo apt install -y curl` |
| 5 | Docker 1 to 6 | Docker images on the host | Nothing to do. `startup_all.sh` builds the images at the first start |
| 6 | The Python packages of the dashboard | The user packages of `/usr/bin/python3` | `/usr/bin/python3 -m pip install --user fastapi uvicorn requests PyYAML` |

Obey these rules for the installation:

- **Install the bridge again after a new clone.** The bridge is not in the CrazySwarm2-with-Mocap
  repository. `install_bridge.sh` copies it from the `kenneth` branch of the
  Kojk-STEngg/CrazySwarm2 fork. A new clone of CrazySwarm2-with-Mocap does not have the `api/`
  folder.
- **Use `/usr/bin/python3` for the bridge and the dashboard.** Do not use a conda Python.
  The bridge needs `rclpy`, and `rclpy` is only in the Python of ROS 2.
- **Do not install `requirements/dashboard.txt` on the host.** Its fixed versions are for the
  containers. On the host, they can replace the fastapi and uvicorn versions of the bridge.
- **Add your user to the `docker` group.** The dashboard runs `docker compose` as your user.
  Run `sudo usermod -aG docker $USER`. Then log out and log in again.
- **Use Docker Compose v2.** The scripts use `docker compose`, not the old `docker-compose`.
- **Docker 6 needs a desktop session.** Before a start with the visualizer, run
  `xhost +local:docker`.

If the CrazySwarm2 workspace is in a different folder, set `CRAZYFLIES_DIR` in `.env` to its
`src/crazyswarm2/crazyflie/config` folder. Give `--repo DIR` to `install_bridge.sh`.

### What starts each part

`ros2 launch` does not start the bridge. Start it from the dashboard or by hand.

| Part | What starts it |
|---|---|
| The ROS 2 server, the mocap driver and the preflight GUI | `ros2 launch crazyflie launch.py`, or **Start the stack** in the CrazySwarm2 mission console |
| The bridge on `127.0.0.1:8011` | **Start the bridge** on the **Stack** page of the dashboard, or you in its own terminal. Start it after the ROS 2 server |
| Docker 1 to 6 | The **Stack** page of the dashboard, or `./scripts/startup_all.sh` |
| The dashboard | `./scripts/dashboard.sh` |

## The settings files

Copy the default files:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

To change the settings, and to start and stop the stack, use the dashboard. Start it on the
host before the stack:

```bash
./scripts/dashboard.sh               # then open http://localhost:8006
```

The dashboard has four pages: **Stack**, **Status**, **Config** and **Debug**. All four are
available when the stack is stopped.

- **Stack** starts the stack with `startup_all.sh` and stops it with `shutdown_all.sh`. It
  shows each command before it runs, and it shows the output of the command.
- **Config** changes `config.yaml`. The stack reads the changes when it starts.

The Stack page sets `MISSION_AUTO_START=0` by default. Thus the drones do not take off until
you push **Start mission**. The dashboard stays available after you stop the stack.

Do not use `docker compose up dashboard` to get the dashboard. That command also starts
mission, and with `MISSION_AUTO_START=1` mission makes the drones take off.

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
system always builds the shape from the front. By default the front row has the highest y
value. `mission.front_axis` changes this (refer to the next section).

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

### `front_axis`: which direction is the front?

`mission.front_axis` in `config.yaml` sets the direction the formation points to.

| Value | Where the front row is | Where the other rows are |
|---|---|---|
| `+y` (default) | At the highest y value | Behind it, at `-spacing` steps in y. Each row is spread along x |
| `+x` | At the highest x value | Behind it, at `-spacing` steps in x. Each row is spread along y |

`+x` gives the same shape, but turned one quarter turn. The spacing between the spots and the
safety gaps do not change. Use it when the long side of your flight area is the x axis.

```yaml
mission:
  front_axis: +x
```

One value sets the direction for the full stack. Mission sends it to Docker 3, which builds
the spots, and to Docker 2, which uses the same direction for the forward-jump penalty, the
backward penalty, and the front-to-back cascade order.

The visualizer always shows +y at the top of the window. Thus with `front_axis: +x` the
formation points to the right of the window, not up.

Mission reads `config.yaml` one time, when it starts. Thus restart it after you change the
value:

```bash
docker compose restart mission
```

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

Do the one-time installation first. Refer to [What to install, and where](#what-to-install-and-where).

1. Start the CrazySwarm2 hardware stack. Use `ros2 launch crazyflie launch.py`, or the
   CrazySwarm2 mission console.

2. Start the dashboard. Then open **http://localhost:8006**.

   ```bash
   ./scripts/dashboard.sh
   ```

3. On the **Stack** page, push **Start the bridge**. The **Health** line must show `ready`.

4. On the **Stack** page, push **Start the stack**.

To start the bridge without the dashboard, run these lines in their own terminal. Keep the
terminal open.

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
cd ~/S_ENG/CrazySwarm2-with-Mocap
/usr/bin/python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8011
```

Then make sure that the bridge answers. `/health` must give `"ready": true`.

```bash
curl http://127.0.0.1:8011/health
curl http://127.0.0.1:8011/drones/status | python3 -m json.tool
```

The **Stack** page also stops a bridge that you started by hand. It stops a process on port
8011 only if that process is the bridge.

To start the stack without the dashboard, use the script. This also starts a dashboard
container on port 8006. That container has no Stack page.

```bash
./scripts/startup_all.sh --crazyswarm
```

The dashboard has buttons to start the mission, to
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
  dashboard_service/        web page: Stack (start and stop the stack), Status (buttons and
                            live state), Config (edit config.yaml) and Debug
  drone_common/             config loader and HTTP client for 1, 4 and 5
third_party/airsim/         vendored AirSim 1.8.1 client, for the old DRONE_MODE=airsim only
tests/                      pytest suite (pip install -r requirements/dev.txt; pytest)
docker/                     one Dockerfile for each service
requirements/               one requirements file for each service, and base.txt and dev.txt
scripts/                    dashboard.sh, startup_all.sh, shutdown_all.sh, install_bridge.sh,
                            swarm_config.py
docs/                       QUICKSTART.md (run-book for hardware),
                            README_EXPLAINED.md (internal operation)
artefacts/                  output of the visualizer, in .gitignore
config.example.yaml         copy to config.yaml (in .gitignore)
.env.example                copy to .env (in .gitignore)
```

Each container has the same layout below `/app`. The packages are in `/app/src`. The system
mounts the config file at `/app/config.yaml`.
