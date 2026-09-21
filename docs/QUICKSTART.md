# Quickstart: drone_reformation and CrazySwarm2-with-Mocap on real hardware

> This document is written in ASD-STE100 Simplified Technical English.

Two repositories, three processes, one HTTP contract.

- `~/S_ENG/CrazySwarm2-with-Mocap`: ROS 2, the vendored mocap driver, and the **HTTP API
  bridge** (`api/app.py`) on **`127.0.0.1:8011`**
- `~/S_ENG/drone_reformation`: the six-Docker reformation stack on `:8001` to `:8005`

This guide is for **real Crazyflies with OptiTrack only**. It is not for the simulator. The
command for the CrazySwarm2 simulator is `ros2 launch crazyflie launch.py backend:=sim`, and
it needs `scripts/setup_sim_firmware.sh`. The simulator has no relation to AirSim. AirSim is
only an old backend in drone_reformation, and you can ignore it.

More data:
CrazySwarm2-with-Mocap [RUNNING](../../CrazySwarm2-with-Mocap/docs/RUNNING.md) ·
[MOCAP](../../CrazySwarm2-with-Mocap/docs/MOCAP.md) ·
[TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md) ·
drone_reformation [README](../README.md) ·
[README_EXPLAINED](README_EXPLAINED.md)

Most of the steps below end with a **Why:** link. The link goes to the part of
README_EXPLAINED that gives the reason.

---

## 0. Layout and ports

```text
~/S_ENG/
├── CrazySwarm2-with-Mocap/
│   ├── api/                          # the HTTP bridge: NOT in this repo by default;
│   │                                 #   ./scripts/install_bridge.sh copies it in (§1.2)
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── scripts/setup.sh              # deps + colcon build + mocap-driver check
│   ├── scripts/build.sh              # run again after you edit src/, but not config
│   ├── src/crazyswarm2/crazyflie/config/
│   │   ├── crazyflies.yaml           # which drones exist + initial_position
│   │   ├── motion_capture.yaml       # where Motive is
│   │   └── server.yaml
│   └── install/setup.bash            # the build makes it; source it in each ROS terminal
└── drone_reformation/
    ├── .env                          # DRONE_MODE, CRAZYSWARM_API_URL, CRAZYSWARM_API_KEY
    ├── config.yaml                   # drone ids, formation, safety gap
    ├── docker-compose.yml
    ├── scripts/startup_all.sh / shutdown_all.sh
    ├── scripts/install_bridge.sh     # copies api/ into the CrazySwarm workspace (§1.2)
    ├── scripts/swarm_config.py       # edits crazyflies.yaml + config.yaml together (§2)
    └── docs/QUICKSTART.md        # this file
```

| Port | What | Who connects |
|---|---|---|
| `127.0.0.1:8011` | CrazySwarm2 HTTP bridge (`api/app.py`) | only Docker 1 |
| `:8001` | Docker 1 drone-control | mission, visualizer, you |
| `:8002` | Docker 2 hungarian | mission |
| `:8003` | Docker 3 formation | mission |
| `:8004` | Docker 4 mission | downed-simulator, you |
| `:8005` | Docker 5 downed-simulator | you |
| `127.0.0.1:8006` | dashboard: web page with buttons | you, in a browser |

In Docker, the services 2 to 5 and the dashboard listen on `:8000` on the private network of
Docker. That port never gets to the host. Thus it cannot have a conflict with another service
on `:8000`.
**Why:** [How the network works](README_EXPLAINED.md#how-the-network-works).

---

## 1. Setup, one time only

### 1.1 ROS 2 Humble

ROS 2 Humble is installed on this machine at `/opt/ros/humble`. On a new machine, obey
[CrazySwarm2-with-Mocap README, Step 1](../../CrazySwarm2-with-Mocap/README.md).

> **Use the Python of ROS.** If conda is active in a terminal, `python3` is the Python of
> conda, and `rclpy` does not import. Run `conda deactivate`, or write `/usr/bin/python3` as
> this guide does.

### 1.2 Get the bridge

The bridge is **not** in the AI-DA-STC repository. It is on the `kenneth` branch of
`Kojk-STEngg/CrazySwarm2`. A new clone of the workspace has **no `api/` folder**. This is the
usual reason that the bridge does not start.

**Use the script:**

```bash
cd ~/S_ENG/drone_reformation
./scripts/install_bridge.sh --deps      # copy api/ in, and install fastapi + uvicorn
```

The script finds the workspace next to this repository. It adds the remote, gets the branch,
and copies in **only** `api/`. Run it again at any time to get later changes to the bridge. It
does not write over your own edits to `api/` unless you give it `--force`.

The script leaves the files staged, and it does not commit to the other repository. Thus you
must commit them there if you want a new clone to keep them. `--dry-run` shows what the script
will do, and `--help` shows the other options.

After the script copies the files, it makes sure that the bridge has the seven routes that
Docker 1 calls. Thus you find an incorrect `--branch` here and not during a flight.

<details>
<summary>The same steps by hand</summary>

```bash
cd ~/S_ENG/CrazySwarm2-with-Mocap
git remote add kojk https://github.com/Kojk-STEngg/CrazySwarm2.git   # once
git fetch kojk kenneth
git checkout kojk/kenneth -- api/        # stages api/; commit it so a re-clone keeps it
/usr/bin/python3 -m pip install --user -r api/requirements.txt       # fastapi + uvicorn
```
</details>

### 1.3 Build the ROS workspace

```bash
cd ~/S_ENG/CrazySwarm2-with-Mocap
/usr/bin/python3 -m pip install --user "setuptools==58.2.0"   # colcon breaks on >= 60
./scripts/setup.sh      # must end with "OK: motion_capture_tracking from .../install/..."
```

The `install/` directory must exist after this step. If it does not exist, the build failed.
Refer to
[TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md).

### 1.4 USB permissions for the Crazyradio

Log out and log in again after this step.

```bash
sudo usermod -aG plugdev $USER
cat <<'EOF' | sudo tee /etc/udev/rules.d/99-bitcraze.rules > /dev/null
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="7777", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="0101", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", MODE="0664", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 1.5 Files for drone_reformation

Git ignores `.env` and `config.yaml`. Thus a new clone does not have them. Make them from the
example files:

```bash
cd ~/S_ENG/drone_reformation
cp .env.example .env
cp config.example.yaml config.yaml
```

`startup_all.sh` also makes them if they do not exist. Git ignores `.env`, thus you never
commit an API key in it.

**Why:** [README_EXPLAINED §11](README_EXPLAINED.md#11-each-setting-explained) gives each
setting in the two files.

---

## 2. The settings: four places must agree

| Where | What it sets |
|---|---|
| `crazyflies.yaml` | which drones exist, their radio URI, where they start |
| Motive rigid bodies | which mocap pose belongs to which drone, matched **by name** |
| `motion_capture.yaml` | where Motive is, and its stream rate |
| drone_reformation `config.yaml` | which IDs mission flies, and the formation |

The services read the config **one time at startup**. After each edit, restart `ros2 launch`,
the bridge and the stack. Edits to the config do not need a new build, because the build uses
symbolic links. Other edits below `src/` do need `./scripts/build.sh`.

**From the dashboard:** the **Config** tab edits `config.yaml` directly. It gives you a form
of named settings, or the text of the file. The "Drone IDs from CrazySwarm" card copies the
enabled drones into `config.yaml` for you, and shows a preview first. It does only that one
step, and it never edits `crazyflies.yaml`. To select which drones fly, or to set their
positions, use the script below.
**Why:** [The dashboard](README_EXPLAINED.md#the-dashboard-on-port-8006).

**The fast method is `drone_reformation/scripts/swarm_config.py`.** It edits `crazyflies.yaml`
and `config.yaml` together. It also changes the drone numbers into the hex IDs of the bridge
for you. Each write prints a diff and leaves a `.bak` file. Add `--dry-run` to see the result
before a write. The script finds `CrazySwarm2-with-Mocap` if the two repositories are next to
each other, as in §0.

```bash
cd ~/S_ENG/drone_reformation
./scripts/swarm_config.py show                            # both configs side by side + any mismatch
./scripts/swarm_config.py set 1 2 4 5 8 --formation 2,3   # fly exactly these drones, on both sides
./scripts/swarm_config.py pos                             # initial_position of every enabled drone from /poses
./scripts/swarm_config.py pos 5=-0.95,-1.15,0             # or type one in
./scripts/swarm_config.py set 1 2 4 5 8 --formation 2,3 --from-mocap   # both steps at once
```

To read from `/poses`, you must have `ros2 launch` running and the workspace sourced. The
script does not do a check of the rule for the shape of the formation in §2.4. That rule says
that each row must be wider than the row in front. Thus you must select the shape yourself.
The sections below tell you what the script changes.

### 2.1 `crazyflies.yaml`

`~/S_ENG/CrazySwarm2-with-Mocap/src/crazyswarm2/crazyflie/config/crazyflies.yaml`

```yaml
robots:
  cf5:                                     # must equal the Motive rigid-body name
    enabled: true                          # false = not connected, not in the API
    uri: radio://0/80/2M/E7E7E7E705        # dongle / channel / datarate / address
    initial_position: [-0.9562, -1.1519, 0]
    type: cf21
```

- **The numeric ID is the last byte of the URI, read as hex.** Refer to
  `crazyflie_py/crazyflie.py`: `int(uri[-2:], 16)`. Thus `…E705` is 5, but `…E710` is **16**
  and `…E712` is **18**. drone_reformation must use these numbers.
  `curl -s 127.0.0.1:8011/drones` shows the numbers that the bridge uses.
- **You must measure `initial_position` from `/poses`**, which is the mocap data. Never
  measure it from `/cfX/pose`.

  WARNING: KEEP THE DRONES 1 M OR MORE APART. GIVE EACH DRONE **ITS OWN** POSITION. POSITIONS
  THAT YOU EXCHANGE CAUSE CROSSED PATHS. A COLLISION OCCURRED FOR THIS REASON ON 2026-08-04.
  DRONES THAT HIT EACH OTHER CAN CAUSE INJURY.
- **Each enabled drone must answer on the radio.** The server stops with no message at the
  first enabled drone that does not answer. Scan each address before the launch (§8).

### 2.2 Motive

Make one rigid body for each drone. Give it the same name as its yaml key, for example `cf5`
and not `CF5`. When you make it, the front of the drone must point along the global +X
direction. Set Z-up, set the stream on, and set **Multicast, 50 Hz**.

The nose of the drone points along `+x`, but the front of the formation is `+y`. These are
different axes. Refer to [Which axis is the front](#which-axis-is-the-front).

### 2.3 `motion_capture.yaml`

`hostname: "auto"` finds Motive with a discovery ping on the same LAN. To set the address
directly, use `ros2 launch crazyflie launch.py mocap_hostname:=<ipv4>`. The value of
`topics.poses.qos.deadline` must agree with the rate of Motive, which is 50.

### 2.4 `config.yaml` of drone_reformation

The IDs **must agree with the enabled drones exactly**. To see which drones are enabled, run
`./scripts/swarm_config.py show`. Now these are cf1, cf2, cf3, cf5 and cf8. Thus:

```yaml
drones:
  ids: [1, 2, 4, 5, 8]
  vehicle_names: {"1": cf1, "2": cf2, "4": cf4, "5": cf5, "8": cf8}
  hover_z: 1.0
mission:
  old_formation: [2, 3]        # row widths, front first
  formation_spacing: 0.5
  safety_gap: 0.25
  move_velocity: 0.5
```

If `config.yaml` has an ID that the bridge does not know, the takeoff of mission fails. The
bridge returns 404 on `/drones/<id>/arm`. The system does not do a check of these two rules
for the formation at startup:

1. **`sum(old_formation)` must equal `len(ids)`.** If it does not, some slots stay empty, or
   the reform fails with `Formation returned too few slots`.
   **Why:** [README_EXPLAINED §12.1](README_EXPLAINED.md#121-sumold_formation-does-not-agree-with-lendronesids-do-this-check-first).
2. **Each row must be wider than the row in front of it.** Examples are `[N]`, `[1,2]`,
   `[2,3]`, `[1,2,3]`. Shapes with a row that repeats or that gets narrower become stuck
   during the reformation. Examples are `[1,2,3,2,1]` and `[3,2,1]`.
   **Why:** [README_EXPLAINED §12.10](README_EXPLAINED.md#1210-most-formation-shapes-become-stuck-during-the-reformation).

To change the shape, refer to
[How to change the formation](README_EXPLAINED.md#how-to-change-the-formation).
[README_EXPLAINED §11](README_EXPLAINED.md#configyaml-docker-1-4-and-5-read-this-file)
gives each setting in `config.yaml`.

#### Which axis is the front

The **y axis** gives the front. A larger y value is nearer to the front. A smaller y value is
nearer to the back. The **x axis** gives the width of a row only.

The formation service puts row `r` at `y = -r * formation_spacing`. Thus the front row is at
`y = 0.0`, and each row behind it has a negative y value. In each row, the spots go along x
around `x = 0`.

```text
row 0 (front)  y =  0.0            •              ← larger y = FRONT
row 1          y = -0.5          •   •
row 2          y = -1.0        •   •   •          ← smaller y = BACK
                             ←──── x ────→
```

Two results are important:

- **The formation has no heading.** The front is always `+y` in the world. You cannot rotate
  the formation, and it does not turn to the direction of travel. If the drones move along x,
  the formation continues to point at `+y`.
- **The front spot is a position, and not a drone.** The Hungarian solver matches the drones to
  the spots again at each reform. Thus the drone at the front can change. Refer to
  [the Hungarian service](README_EXPLAINED.md#7-docker-2-hungarian-assignment-the-matching).

CAUTION: THE FRONT OF THE FORMATION AND THE FRONT OF A DRONE USE DIFFERENT AXES. THE FORMATION
FRONT IS `+y`. THE NOSE OF EACH DRONE POINTS ALONG `+x` IN MOTIVE (§2.2). MISSION SENDS
`yaw: 0.0` WITH EACH GO-TO COMMAND, THUS A DRONE NEVER TURNS TO FACE THE FORMATION FRONT. IF
YOU CONFUSE THE TWO AXES, YOU CAN SET THE `initial_position` VALUES INCORRECTLY AND CAUSE A
COLLISION.

### 2.5 `.env`: port, backend, API key

```bash
DRONE_MODE=crazyswarm                      # startup_all.sh --mock / --crazyswarm rewrites this
CRAZYSWARM_API_URL=http://127.0.0.1:8011   # must match the bridge's --port
CRAZYSWARM_API_KEY=                        # optional, see below
MISSION_AUTO_START=1                       # 1 = mission takes off as soon as the stack starts
```

**`MISSION_AUTO_START`** decides if a start of the stack is also a takeoff command.

| Value | When the mission container starts |
|---|---|
| `1` | It waits for the backend. Then it **arms each drone, takes off and flies the first formation**. You do not push a button |
| `0` | It does nothing until you push **Start mission** on the dashboard, or until you send `POST /start` (§3.4) |

Use `0` on a day with hardware. Thus "the stack is running" and "the drones are flying" stay
separate. Two things are important:

- **A change to this value needs a new container, not a restart.** The container keeps the
  environment values from the time when you made it. `docker compose up -d mission` uses the
  new value. `docker compose restart mission` uses the old value again.
- WARNING: WITH `MISSION_AUTO_START=1`, A RESTART OF MISSION IS ALSO A TAKEOFF COMMAND. THE
  DRONES CAN MOVE WITHOUT A WARNING AND CAUSE INJURY. RESTART MISSION ONLY WHEN YOU ARE READY
  TO FLY. If the bridge is not up, mission waits `control_ready_timeout` seconds, 120 by
  default. Then it stops, and it puts the reason in `last_error`. It does not try again.

**`CRAZYSWARM_API_KEY`** is an optional shared password between the bridge and Docker 1.

- **Empty on the two sides**, which is the default: there is no authentication. Any program
  that can get to `127.0.0.1:8011` can fly the drones. This is satisfactory when the bridge is
  bound to `127.0.0.1`, as below.
- **The same value on the two sides**: the bridge rejects each request that does not have a
  correct `X-API-Key` header, and returns `401`. Docker 1 adds that header automatically.
  `/health` stays open. Use a key if you bind the bridge to `0.0.0.0`.

```bash
openssl rand -hex 16                       # generate one
# bridge terminal:     export CRAZYSWARM_API_KEY=<key>   (before starting uvicorn)
# drone_reformation:   CRAZYSWARM_API_KEY=<key> in .env, then restart the stack
```

**Why:** [README_EXPLAINED §11, `.env`](README_EXPLAINED.md#env-how-the-parts-connect)
gives each variable. If Docker 1 cannot get to the bridge, do a check of the port first:
[§12.7](README_EXPLAINED.md#127-the-port-number-is-different-in-different-files).

---

## 3. Start, at each session

Open one terminal for each step. The steps 1 to 3 need
`source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash`.

### 3.1 Before the launch: scan each enabled drone

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
for a in 01 02 04 05 08; do ros2 run crazyflie scan --address 0xE7E7E7E7$a; done
```

Each address must print a URI. Run this **before** `ros2 launch`, because the server holds the
radio while it runs.

### 3.2 Terminal 1: the CrazySwarm2 server

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
ros2 launch crazyflie launch.py
```

Do a check of the `mocap: Motive at <ip>` line.

WARNING: FIND THE E-STOP CONTROL BEFORE THE DRONES TAKE OFF. THE E-STOP IS THE `e` KEY IN THE
PREFLIGHT GUI. A DRONE THAT YOU CANNOT STOP CAN CAUSE INJURY.

Then clear **each** drone on the preflight GUI:

1. Make sure that the battery indication is not red.
2. Make sure that the mocap rate is near 50 Hz.
3. Make sure that `|err.yaw|` is 5° or less.
4. Push **Reset Kalman (all)** with the `r` key.
5. Let the drones become stable.

The full checklist is in [RUNNING §C](../../CrazySwarm2-with-Mocap/docs/RUNNING.md).

### 3.3 Terminal 2: the bridge

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
cd ~/S_ENG/CrazySwarm2-with-Mocap          # api.app must be importable from here
/usr/bin/python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8011
```

**All of the three lines are necessary.** If you do not do one line, you get a different
error:

| Line not done | What you get |
|---|---|
| `source` | `ModuleNotFoundError: No module named 'crazyflie_py'` |
| `cd` | `ModuleNotFoundError: No module named 'api'`. You can import `api` only from the root of the repository |
| `/usr/bin/python3` | `rclpy` is missing, or you get a conda or `python3.1x` error |

There is a fourth cause of `No module named 'api'`: nobody copied `api/` in. Refer to §1.2,
and do a check with `ls ~/S_ENG/CrazySwarm2-with-Mocap/api`.

Make sure of these items before you continue:

```bash
curl -s 127.0.0.1:8011/health                                # "ready": true
curl -s 127.0.0.1:8011/drones | python3 -m json.tool         # ids = config.yaml ids
curl -s 127.0.0.1:8011/drones/status | python3 -m json.tool  # position_received: true, positions live
```

If `/health` stays at `"initializing"`, the bridge cannot see the ROS services. Make sure that
terminal 1 is up. Also make sure that the two terminals sourced the same workspace.

### 3.4 Terminal 3: the stack

**Do a smoke test in mock mode first**, also on a day with hardware. This touches no hardware:

```bash
cd ~/S_ENG/drone_reformation
./scripts/startup_all.sh --mock
curl -s localhost:8004/status | python3 -m json.tool     # running: true, last_error: null
./scripts/shutdown_all.sh
```

**Why:** [What `startup_all.sh` does](README_EXPLAINED.md#what-startup_allsh-does) gives
each step and each option.

**Then do the real run.**

WARNING: WITH `MISSION_AUTO_START=1`, THIS COMMAND ARMS THE DRONES, TAKES OFF EACH DRONE IN
`ids`, AND FLIES THE FIRST FORMATION IMMEDIATELY. KEEP PERSONS AWAY FROM THE FLIGHT AREA.

```bash
./scripts/startup_all.sh --crazyswarm
```

[README_EXPLAINED §8, What occurs, in sequence](README_EXPLAINED.md#what-occurs-in-sequence)
gives the steps that mission does from here.

To do a test of Docker 1 by hand first (§4), set `MISSION_AUTO_START=0` in `.env` (§2.5). Then
make the container again with `docker compose up -d mission`. A `restart` keeps the old value.

#### How to start the mission by hand

This applies when `MISSION_AUTO_START=0`. Nothing flies until you give the command. There are
three methods, and they give the same result:

```bash
# 1. the dashboard: http://localhost:8006 -> "Start mission" (asks you to confirm)

# 2. curl
curl -X POST localhost:8004/start -H 'Content-Type: application/json' -d '{"setup_hover":true}'

# 3. mission's own page: http://localhost:8004/docs -> POST /start -> Try it out -> Execute
```

**Before you give the command**, make sure that `ros2 launch` and the bridge are up. Also make
sure that `curl -s 127.0.0.1:8011/health` gives `"ready": true` (§3.3). If it does not,
mission waits `control_ready_timeout` seconds, 120 by default. Then it stops, and it puts the
reason in `last_error`. It does not try again.

**Start does these steps in sequence:** it waits for the backend of Docker 1. It arms and
takes off each drone in `ids`, which is the function of `setup_hover: true`. It flies the
first formation. Then it monitors the drones for a loss.

**Start takes off one time only in each mission process.** After **Stop**, Start again
continues to monitor the drones. But it does **not** take off, and it does not fly the first
formation again. Refer to §12.6 in README_EXPLAINED. For a new run, use
`docker compose restart mission`. With `MISSION_AUTO_START=0` this does not take off either,
thus push Start again after it.

**Do you want buttons?** Open **http://localhost:8006**. The dashboard can start the mission,
down a drone, reform, and land all of the drones. It also shows the live drone status, a map,
and the last reform. It has **no** emergency stop.
**Why:** [The dashboard](README_EXPLAINED.md#the-dashboard-on-port-8006).

**Always make sure that mission started.** `startup_all.sh` reports "healthy" also when the
mission worker is dead:

```bash
curl -s localhost:8004/status | python3 -m json.tool
```

`running` must be `true`, and `last_error` must be `null`. There is a known race at startup:
mission fails with `Connection refused` to `hungarian` when mission starts before hungarian
listens. To correct this, run `docker compose restart mission`.

**Why:** [README_EXPLAINED §12.5](README_EXPLAINED.md#125-health-gives-incorrect-data-about-mission).

---

## 4. Do a test of Docker 1 alone

Set `MISSION_AUTO_START=0` for this test.

```bash
curl -X POST localhost:8001/setup_hover -H 'Content-Type: application/json' -d '{"drone_ids":[5]}'
curl -X POST localhost:8001/move_to_xy_z -H 'Content-Type: application/json' \
  -d '{"drone_id":5,"x":-0.5,"y":-1.0,"z":1.0,"velocity":0.5}'
curl -s localhost:8001/drones/5/status | python3 -m json.tool
curl -X POST localhost:8001/land -H 'Content-Type: application/json' -d '{"drone_ids":[5]}'
```

Select a target near to the `initial_position` of the drone. `move_to_xy_z` uses absolute
world coordinates.

**Why:** [README_EXPLAINED §5](README_EXPLAINED.md#5-docker-1-the-gateway) gives each
route of Docker 1. It includes
[why `setup_hover` is slow](README_EXPLAINED.md#setup_hover-is-slow-for-a-reason) and
[how `move_to_xy_z` becomes a go-to](README_EXPLAINED.md#move_to_xy_z-becomes-the-go-to-of-crazyswarm).

---

## 5. Do a test of the reformation

To down a drone:

```bash
curl -X POST localhost:8005/down -H 'Content-Type: application/json' -d '{"drone_ids":[8]}'   # a specific drone
curl -X POST localhost:8005/down -H 'Content-Type: application/json' -d '{"count":1}'          # a random one
```

The drone lands and disarms. Mission finds this in `poll_interval` seconds. Then it reforms
the drones that are left. Do these checks:

```bash
curl -s localhost:8004/status      | python3 -m json.tool   # last_downed, last_error
curl -s localhost:8004/last_reform | python3 -m json.tool   # active_ids, targets, hungarian.assignment
curl -s localhost:8004/last_move   | python3 -m json.tool   # each drone: arrived | timeout | aborted_down
```

The test is satisfactory if `last_reform.downed` gives the drone, if `active_ids` gives each
other drone, and if each `last_move` entry gives `arrived`. For an automatic loss, set
`AUTO_DOWN_IDS=8` or `AUTO_DOWN_COUNT=1` in `.env`. Also set `AUTO_DOWN_AFTER_SEC=30` before
you start.

**Why:**

- How mission builds the formation again:
  [`_execute_reform`, the six steps](README_EXPLAINED.md#_execute_reform-the-six-steps)
- What `arrived`, `timeout` and `aborted_down` mean:
  [`_move_drone_safely`](README_EXPLAINED.md#_move_drone_safely-how-a-drone-moves-to-its-spot)
- Why the simulator goes through mission, and when `AUTO_DOWN_AFTER_SEC` starts to count:
  [README_EXPLAINED §9](README_EXPLAINED.md#9-docker-5-the-downed-simulator)

---

## 6. Stop

```bash
cd ~/S_ENG/drone_reformation
./scripts/shutdown_all.sh          # lands + disarms every drone, then removes the containers
```

Then push Ctrl-C in the terminal of the bridge and in the terminal of `ros2 launch`.

### Emergency stop

WARNING: THE E-STOP STOPS THE MOTORS AND THE DRONE FALLS. KEEP PERSONS AWAY FROM THE AREA
BELOW THE DRONES. A DRONE THAT FALLS CAN CAUSE INJURY.

The **E-STOP in the preflight GUI** is the primary emergency stop. Push the `e` key, or push
**E-STOP (all)**. It needs only ROS and the radio. These are the alternative methods:

```bash
ros2 service call /all/emergency std_srvs/srv/Empty      # every drone, straight through ROS
curl -X POST 127.0.0.1:8011/drones/5/emergency \
  -H 'Content-Type: application/json' -d '{"confirm": true}'   # one drone via the bridge
```

After an emergency stop, the firmware ignores each command. To make the drone operate again,
remove and apply its power by hand. Docker 1 has **no** `/estop` route.

---

## 7. Between runs: restart the bridge and mission

- **The bridge never clears `down`.** Each land command, which includes `shutdown_all.sh`,
  marks a drone as `down` until the bridge process restarts. A new arm command does not clear
  it. The symptom is that each drone is `down` on the second run. To correct this, push Ctrl-C
  and start uvicorn again (§3.3).
- **The one-time flags of mission never reset.** `/stop` and then `/start` do not do the
  takeoff or the first formation again. To correct this, run `docker compose restart mission`,
  or run `startup_all.sh` again.
  **Why:** [README_EXPLAINED §12.6](README_EXPLAINED.md#126-the-one-time-flags-never-reset).

---

## 8. Commands to find faults

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash   # every ROS terminal
```

**Radio.** Stop `ros2 launch` first, because it holds the radio:

```bash
lsusb | grep 1915                                            # Crazyradio present? (1915:7777)
ros2 run crazyflie scan --address 0xE7E7E7E705               # URI(s) that answer
ros2 run crazyflie battery --uri radio://0/80/2M/E7E7E7E705
ros2 run crazyflie reboot  --uri radio://0/80/2M/E7E7E7E705
```

**ROS and mocap.** Use these commands while `ros2 launch` runs:

```bash
ros2 node list                            # /crazyflie_server, /motion_capture_tracking
ros2 pkg prefix motion_capture_tracking   # must be .../CrazySwarm2-with-Mocap/install/..., never /opt/ros
ros2 topic hz /poses                      # about 50
ros2 topic echo /poses --once             # rigid-body names + positions from Motive
ros2 topic echo /cf5/status --once        # battery_voltage, supervisor_info (16 flying, 32 tumbled, 64 locked)
ss -uanp | grep :1511                     # more than one mocap socket = leftover process starving the node
```

**Bridge and stack:**

```bash
curl -s 127.0.0.1:8011/drones/status | python3 -m json.tool  # idle|busy|down + positions
# http://127.0.0.1:8011/docs is Swagger UI for every bridge route
cd ~/S_ENG/drone_reformation
docker compose ps
docker compose logs -f drone-control      # or mission, formation, hungarian, downed-simulator
curl -s localhost:8001/health | python3 -m json.tool   # mode, and backend.upstream = bridge health
curl -s localhost:8001/states | python3 -m json.tool   # what mission sees
ss -ltnp | grep -E ':80(0[1-5]|11)\b'                  # who holds the ports
```

| Symptom | What to do |
|---|---|
| `setup.sh` fails: `option --uninstall not recognized` | setuptools is 60 or higher. Run `pip install --user setuptools==58.2.0` and `rm -rf build install log`, then run it again |
| `ros2 launch` stops, no `/all/*` services | An enabled drone does not answer, or the datarate in its URI is incorrect. Scan each address (§3.1) |
| Launch aborts: `motion_capture_tracking resolves to the apt package` | Run `sudo apt remove ros-humble-motion-capture-tracking ros-humble-motion-capture-tracking-interfaces`, then `./scripts/build.sh`, then source again |
| `position_received: false` for one drone | The Motive rigid-body name does not agree with the yaml key. Compare them with `ros2 topic echo /poses --once` |
| `position_received: false` for each drone | Motive does not stream Multicast, or you are not on the LAN of Motive |
| Bridge: `No module named 'crazyflie_py'` | You did not source the terminal with `install/setup.bash` |
| Bridge: `No module named 'api'` | You did not start uvicorn from `~/S_ENG/CrazySwarm2-with-Mocap`, **or** nobody copied `api/` in. Run `ls ~/S_ENG/CrazySwarm2-with-Mocap/api`, then `./scripts/install_bridge.sh` (§1.2) |
| Bridge: `rclpy`, `python3.1x` or miniconda errors | Use `/usr/bin/python3`, or run `conda deactivate` |
| Bridge `/health` stays at `initializing` | `ros2 launch` is not up, or the DDS discovery stopped. Start the bridge again after the server is up |
| Docker 1 `/health` shows `backend_error: ... 8011 ... refused` | The bridge is not running, or `CRAZYSWARM_API_URL` in `.env` does not agree with the port of the bridge |
| Docker 1 gives `401 Invalid API key` | `CRAZYSWARM_API_KEY` is different in the bridge terminal and in `.env` |
| Mission `last_error`: `Unknown drone IDs`, or a 404 on `/drones/N/arm` | The `ids` in `config.yaml` do not agree with `curl 127.0.0.1:8011/drones` |
| Mission `last_error`: `Connection refused` to hungarian | A race at startup. Run `docker compose restart mission` |
| Each drone is `down` on the second run | Start the bridge again (§7) |
| Reform fails: `Formation returned too few slots` | `sum(old_formation) < len(ids)` ([why](README_EXPLAINED.md#121-sumold_formation-does-not-agree-with-lendronesids-do-this-check-first)) |
| `last_move` shows `timeout` with a `blocked_count` that increases | The shape of the formation becomes stuck (§2.4, rule 2; [why](README_EXPLAINED.md#1210-most-formation-shapes-become-stuck-during-the-reformation)) |
| Crossed paths, or a near collision | The `initial_position` values are incorrect or exchanged. Correct them before you fly again |
| `Motion capture rate off` each second at 50 Hz | The warning range in `server.yaml` is `[80, 120]`. Set it to `[40, 60]` |

For problems in the stack, use
[README_EXPLAINED §15, Checklist for faults](README_EXPLAINED.md#15-checklist-for-faults).
Examples of these problems are: nothing reforms, the drones stop too soon, or the visualizer
is blank.

---

## 9. How the parts connect

```text
Motive ──NatNet 50 Hz──▶ motion_capture_tracking ──/poses──▶ crazyflie_server ──radio──▶ drones
                                                                   ▲ ROS 2 services
                                                     api/app.py bridge · 127.0.0.1:8011
                                                     (crazyflie_py; go-to duration = distance / velocity)
═══════════════════════════════════════ the one HTTP contract ═══════════════════════════════════
                                                     Docker 1 drone-control · :8001 (host network)
                                                                   ▲ /states: x, y, idle|busy|down
                                                     Docker 4 mission · :8004 ──▶ Docker 3 formation (geometry)
                                                                   │          ──▶ Docker 2 hungarian (matching)
                                   Docker 5 downed-simulator · :8005 ──▶ mission /simulate_downed ──▶ Docker 1 /down
                                   Docker 6 visualizer ──▶ Docker 1 /states_vis (read-only)
```

**The status is the contract.** Refer to
[the status model](README_EXPLAINED.md#4-the-status-model-the-core-idea). The bridge
reports one field for each drone:

- `idle`: there is no active go-to command.
- `busy`: this is a timer. The drone reads `busy` for exactly `distance / velocity` seconds
  after a go-to command. This is independent of the arrival of the drone. Mission reads the
  position again after each hop.
- `down`: the bridge landed the drone. Mission holds it as lost. The status stays at `down`
  until the bridge restarts.

**The reformation loop** is `_execute_reform` in `src/mission_service/app.py`. Mission polls
Docker 1. When a drone changes to `down`, mission asks formation for the new shape and puts it
in the world. It rejects the plan if the targets are nearer to each other than `safety_gap`.

Then mission asks Hungarian which drone goes to which spot. Then it flies each drone in hops
of `waypoint_step`, and it starts with the front row. Before each hop it does a check of that hop
against the live position of each other drone. Each part has more data:
[formation](README_EXPLAINED.md#6-docker-3-formation-the-geometry),
[Hungarian](README_EXPLAINED.md#7-docker-2-hungarian-assignment-the-matching),
[mission](README_EXPLAINED.md#8-docker-4-mission-the-brain).

**Known limits.** There is no geofence. There is only the `safety_gap` between two commanded
waypoints.

WARNING: DOCKER 1 AND THE BRIDGE ARE SINGLE POINTS OF FAILURE. IF ONE OF THEM STOPS DURING A
FLIGHT, THE DRONES KEEP THEIR LAST SETPOINT. KEEP THE E-STOP IN THE PREFLIGHT GUI OPEN AT ALL
TIMES. A DRONE THAT YOU CANNOT STOP CAN CAUSE INJURY.
