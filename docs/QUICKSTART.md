# Quickstart: drone_reformation + CrazySwarm2-with-Mocap (real hardware)

Two repos, three processes, one HTTP contract.

- `~/S_ENG/CrazySwarm2-with-Mocap`: ROS 2, the vendored mocap driver, and the **HTTP API bridge** (`api/app.py`) on **`127.0.0.1:8011`**
- `~/S_ENG/drone_reformation`: the six-Docker reformation stack on `:8001` to `:8005`

This guide covers **real Crazyflies with OptiTrack only**. It does not cover the simulator.
(The CrazySwarm2 simulator is `ros2 launch crazyflie launch.py backend:=sim` and needs
`scripts/setup_sim_firmware.sh`. It has nothing to do with AirSim. AirSim is only a legacy
backend inside drone_reformation, and you can ignore it.)

More detail:
CrazySwarm2-with-Mocap [RUNNING](../../CrazySwarm2-with-Mocap/docs/RUNNING.md) ·
[MOCAP](../../CrazySwarm2-with-Mocap/docs/MOCAP.md) ·
[TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md) ·
drone_reformation [README](../README.md) ·
[README_EXPLAINED](README_EXPLAINED.md)

---

## 0. Layout and ports

```text
~/S_ENG/
├── CrazySwarm2-with-Mocap/
│   ├── api/                          # the HTTP bridge, pulled from Kojk-STEngg/CrazySwarm2@kenneth (§1.2)
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── scripts/setup.sh              # deps + colcon build + mocap-driver check
│   ├── scripts/build.sh              # re-run after editing anything under src/ except config
│   ├── src/crazyswarm2/crazyflie/config/
│   │   ├── crazyflies.yaml           # which drones exist + initial_position
│   │   ├── motion_capture.yaml       # where Motive is
│   │   └── server.yaml
│   └── install/setup.bash            # created by the build; source it in every ROS terminal
└── drone_reformation/
    ├── .env                          # DRONE_MODE, CRAZYSWARM_API_URL, CRAZYSWARM_API_KEY
    ├── config.yaml                   # drone ids, formation, safety gap
    ├── docker-compose.yml
    ├── scripts/startup_all.sh / shutdown_all.sh
    ├── scripts/swarm_config.py       # edits crazyflies.yaml + config.yaml together (§2)
    └── docs/QUICKSTART.md            # this file
```

| Port | What | Who connects |
|---|---|---|
| `127.0.0.1:8011` | CrazySwarm2 HTTP bridge (`api/app.py`) | only Docker 1 |
| `:8001` | Docker 1 drone-control | mission, visualizer, you |
| `:8002` | Docker 2 hungarian | mission |
| `:8003` | Docker 3 formation | mission |
| `:8004` | Docker 4 mission | downed-simulator, you |
| `:8005` | Docker 5 downed-simulator | you |

Inside Docker, services 2 to 5 listen on `:8000` on Docker's private network. That port
never reaches the host, so it cannot collide with anything else on `:8000`.

---

## 1. One-time setup

### 1.1 ROS 2 Humble

Already installed on this machine (`/opt/ros/humble`). On a new machine, follow
[CrazySwarm2-with-Mocap README, Step 1](../../CrazySwarm2-with-Mocap/README.md).

> **Use ROS's Python.** If conda is active in a terminal, `python3` is conda's Python and
> `rclpy` won't import. Run `conda deactivate`, or write `/usr/bin/python3` explicitly
> as this guide does.

### 1.2 Get the bridge

The bridge is **not** in the AI-DA-STC repo. It lives on the `kenneth` branch of
`Kojk-STEngg/CrazySwarm2`. These commands copy just its `api/` folder into your checkout.
Nothing else in your repo changes.

```bash
cd ~/S_ENG/CrazySwarm2-with-Mocap
git remote add kojk https://github.com/Kojk-STEngg/CrazySwarm2.git   # once
git fetch kojk kenneth
git checkout kojk/kenneth -- api/        # stages api/; commit it so a re-clone keeps it
/usr/bin/python3 -m pip install --user -r api/requirements.txt       # fastapi + uvicorn
```

To pick up later bridge changes, re-run the `fetch` and `checkout` lines.

### 1.3 Build the ROS workspace

```bash
cd ~/S_ENG/CrazySwarm2-with-Mocap
/usr/bin/python3 -m pip install --user "setuptools==58.2.0"   # colcon breaks on >= 60
./scripts/setup.sh      # must end with "OK: motion_capture_tracking from .../install/..."
```

`install/` must exist afterwards. If it doesn't, the build failed. See
[TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md).

### 1.4 Crazyradio USB permissions (log out and back in afterwards)

```bash
sudo usermod -aG plugdev $USER
cat <<'EOF' | sudo tee /etc/udev/rules.d/99-bitcraze.rules > /dev/null
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="7777", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="0101", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", MODE="0664", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 1.5 drone_reformation files

`.env` and `config.yaml` are already in the repo. On a fresh machine without them:

```bash
cd ~/S_ENG/drone_reformation
cp .env.example .env
cp config.example.yaml config.yaml
```

Both files are **tracked by git**. Don't commit an API key in `.env`.

---

## 2. Configure: four places must agree

| Where | Decides |
|---|---|
| `crazyflies.yaml` | which drones exist, their radio URI, where they start |
| Motive rigid bodies | which mocap pose belongs to which drone, matched **by name** |
| `motion_capture.yaml` | where Motive is, and its stream rate |
| drone_reformation `config.yaml` | which IDs mission flies, and the formation |

Config is read **once at startup**. After any edit, restart `ros2 launch`, the bridge
and the stack. Config edits don't need a rebuild (the build uses symlinks). Other edits
under `src/` do need `./scripts/build.sh`.

**The fast way: `drone_reformation/scripts/swarm_config.py`** edits `crazyflies.yaml` and
`config.yaml` together and converts drone numbers to the bridge's hex IDs for you. Each write
prints a diff and leaves a `.bak`. Add `--dry-run` to preview without writing. It finds
`CrazySwarm2-with-Mocap` as long as both repos sit side by side, as in §0.

```bash
cd ~/S_ENG/drone_reformation
./scripts/swarm_config.py show                            # both configs side by side + any mismatch
./scripts/swarm_config.py set 1 2 4 5 8 --formation 2,3   # fly exactly these drones, on both sides
./scripts/swarm_config.py pos                             # initial_position of every enabled drone from /poses
./scripts/swarm_config.py pos 5=-0.95,-1.15,0             # or type one in
./scripts/swarm_config.py set 1 2 4 5 8 --formation 2,3 --from-mocap   # both steps at once
```

Reading from `/poses` needs `ros2 launch` running and the workspace sourced. It doesn't check
the formation-shape rule in §2.4 (rows must widen), so choose the shape yourself.
The sections below explain what it changes.

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

- **The numeric ID is the last URI byte read as hex** (`crazyflie_py/crazyflie.py`:
  `int(uri[-2:], 16)`). So `…E705` is 5, but `…E710` is **16** and `…E712` is **18**.
  drone_reformation must use these numbers. `curl -s 127.0.0.1:8011/drones` shows what
  the bridge uses.
- **`initial_position`** must be measured from `/poses` (mocap), never from `/cfX/pose`.
  Keep drones ≥ 1 m apart, each at **its own** position. Swapped positions cause crossed
  paths, and caused a real collision on 2026-08-04.
- **Every enabled drone must answer on the radio.** The server hangs silently on the first
  enabled drone that doesn't respond. Scan each address before launch (§8).

### 2.2 Motive

One rigid body per drone, named exactly like its yaml key (`cf5`, not `CF5`). Create it
with the drone's front pointing along global +X. Z-up, streaming on, **Multicast, 50 Hz**.

### 2.3 `motion_capture.yaml`

`hostname: "auto"` finds Motive by a discovery ping on the same LAN. To pin the address
instead: `ros2 launch crazyflie launch.py mocap_hostname:=<ipv4>`. `topics.poses.qos.deadline`
must match Motive's rate (50).

### 2.4 drone_reformation `config.yaml`

The IDs **must match the enabled drones exactly**. The current `crazyflies.yaml` enables
cf1, cf2, cf4, cf5 and cf8, so:

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

An ID in `config.yaml` that the bridge doesn't know makes mission's takeoff fail (the
bridge returns 404 on `/drones/<id>/arm`). Two formation rules are not checked at startup:

1. **`sum(old_formation)` must equal `len(ids)`.** Otherwise slots stay empty, or the
   reform fails with `Formation returned too few slots`.
2. **Every row must be wider than the one in front** (`[N]`, `[1,2]`, `[2,3]`, `[1,2,3]`).
   Shapes where a row repeats or narrows, such as `[1,2,3,2,1]` and `[3,2,1]`, get stuck
   during reformation. See [README_EXPLAINED §12.10](README_EXPLAINED.md).

### 2.5 `.env`: port, backend, API key

```bash
DRONE_MODE=crazyswarm                      # startup_all.sh --mock / --crazyswarm rewrites this
CRAZYSWARM_API_URL=http://127.0.0.1:8011   # must match the bridge's --port
CRAZYSWARM_API_KEY=                        # optional, see below
MISSION_AUTO_START=1                       # 1 = mission takes off as soon as the stack starts
```

**`CRAZYSWARM_API_KEY`** is an optional shared password between the bridge and Docker 1.

- **Empty on both sides** (the default): no authentication. Anything that can reach
  `127.0.0.1:8011` can fly the drones. This is acceptable when the bridge is bound to
  `127.0.0.1`, as below.
- **Set on both sides to the same value**: the bridge rejects any request without a
  matching `X-API-Key` header (`401`), and Docker 1 adds that header automatically.
  `/health` stays open. Use a key if you ever bind the bridge to `0.0.0.0`.

```bash
openssl rand -hex 16                       # generate one
# bridge terminal:     export CRAZYSWARM_API_KEY=<key>   (before starting uvicorn)
# drone_reformation:   CRAZYSWARM_API_KEY=<key> in .env, then restart the stack
```

---

## 3. Start (every session)

Open a terminal per step. Steps 1 to 3 need `source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash`.

### 3.1 Before launch: scan every enabled drone

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
for a in 01 02 04 05 08; do ros2 run crazyflie scan --address 0xE7E7E7E7$a; done
```

Every address must print a URI. Run this **before** `ros2 launch`, because the server
holds the radio while it runs.

### 3.2 Terminal 1: CrazySwarm2 server

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
ros2 launch crazyflie launch.py
```

Check the `mocap: Motive at <ip>` line. Then clear **every** drone on the preflight GUI:
battery not red, mocap about 50 Hz, `|err.yaw|` ≤ 5°, then **Reset Kalman (all)** (`r`) and
let it settle. **Know where E-STOP is** (`e` in the GUI). Full checklist:
[RUNNING §C](../../CrazySwarm2-with-Mocap/docs/RUNNING.md).

### 3.3 Terminal 2: the bridge

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
cd ~/S_ENG/CrazySwarm2-with-Mocap          # api.app must be importable from here
/usr/bin/python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8011
```

Verify before going further:

```bash
curl -s 127.0.0.1:8011/health                                # "ready": true
curl -s 127.0.0.1:8011/drones | python3 -m json.tool         # ids = config.yaml ids
curl -s 127.0.0.1:8011/drones/status | python3 -m json.tool  # position_received: true, positions live
```

If `/health` stays `"initializing"`, the bridge can't see the ROS services. Check that
terminal 1 is up and that both terminals sourced the same workspace.

### 3.4 Terminal 3: the stack

**Smoke test in mock mode first**, even on a hardware day. No hardware is touched:

```bash
cd ~/S_ENG/drone_reformation
./scripts/startup_all.sh --mock
curl -s localhost:8004/status | python3 -m json.tool     # running: true, last_error: null
./scripts/shutdown_all.sh
```

**Then for real.** With `MISSION_AUTO_START=1`, this **arms, takes off every drone in
`ids` and flies the initial formation immediately**:

```bash
./scripts/startup_all.sh --crazyswarm
```

To test Docker 1 by hand first (§4), set `MISSION_AUTO_START=0` in `.env` before starting.
When you're ready, start the mission yourself:

```bash
curl -X POST localhost:8004/start -H 'Content-Type: application/json' -d '{"setup_hover":true}'
```

**Always check that mission really started.** `startup_all.sh` reports "healthy" even when
the mission worker has died:

```bash
curl -s localhost:8004/status | python3 -m json.tool
```

`running` must be `true` and `last_error` must be `null`. A known startup race makes mission
fail with `Connection refused` to `hungarian` when it starts before hungarian is listening.
Fix it with `docker compose restart mission`.

---

## 4. Test Docker 1 alone (with `MISSION_AUTO_START=0`)

```bash
curl -X POST localhost:8001/setup_hover -H 'Content-Type: application/json' -d '{"drone_ids":[5]}'
curl -X POST localhost:8001/move_to_xy_z -H 'Content-Type: application/json' \
  -d '{"drone_id":5,"x":-0.5,"y":-1.0,"z":1.0,"velocity":0.5}'
curl -s localhost:8001/drones/5/status | python3 -m json.tool
curl -X POST localhost:8001/land -H 'Content-Type: application/json' -d '{"drone_ids":[5]}'
```

Pick a target close to the drone's own `initial_position`. `move_to_xy_z` uses absolute
world coordinates.

---

## 5. Test reformation (down a drone)

```bash
curl -X POST localhost:8005/down -H 'Content-Type: application/json' -d '{"drone_ids":[8]}'   # a specific drone
curl -X POST localhost:8005/down -H 'Content-Type: application/json' -d '{"count":1}'          # a random one
```

The drone lands and disarms. Mission notices within `poll_interval` and reforms the survivors.
Check:

```bash
curl -s localhost:8004/status      | python3 -m json.tool   # last_downed, last_error
curl -s localhost:8004/last_reform | python3 -m json.tool   # active_ids, targets, hungarian.assignment
curl -s localhost:8004/last_move   | python3 -m json.tool   # each drone: arrived | timeout | aborted_down
```

It worked if `last_reform.downed` lists the drone, `active_ids` lists everyone else, and every
`last_move` entry says `arrived`. For an automatic loss, set `AUTO_DOWN_IDS=8` (or
`AUTO_DOWN_COUNT=1`) and `AUTO_DOWN_AFTER_SEC=30` in `.env` before starting.

---

## 6. Stop

```bash
cd ~/S_ENG/drone_reformation
./scripts/shutdown_all.sh          # lands + disarms every drone, then removes the containers
```

Then Ctrl-C the bridge and `ros2 launch`.

### Emergency stop

The **preflight GUI E-STOP** (`e`, or **E-STOP (all)**) is the primary e-stop. It needs
only ROS and the radio. Backups:

```bash
ros2 service call /all/emergency std_srvs/srv/Empty      # every drone, straight through ROS
curl -X POST 127.0.0.1:8011/drones/5/emergency \
  -H 'Content-Type: application/json' -d '{"confirm": true}'   # one drone via the bridge
```

E-stop cuts the motors and the drone falls. The firmware then ignores everything until you
power-cycle the drone by hand. Docker 1 currently has **no** `/estop` route.

---

## 7. Between runs: restart the bridge and mission

- **The bridge never clears `down`.** Any land, including `shutdown_all.sh`, marks a drone
  `down` until the bridge process restarts. Re-arming doesn't clear it. Symptom: every drone
  is `down` on the second run. Fix: Ctrl-C and restart uvicorn (§3.3).
- **Mission's one-time flags never reset.** `/stop` then `/start` won't redo takeoff or the
  initial formation. Fix: `docker compose restart mission`, or rerun `startup_all.sh`.

---

## 8. Troubleshooting commands

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash   # every ROS terminal
```

**Radio** (stop `ros2 launch` first, because it holds the radio):

```bash
lsusb | grep 1915                                            # Crazyradio present? (1915:7777)
ros2 run crazyflie scan --address 0xE7E7E7E705               # URI(s) that answer
ros2 run crazyflie battery --uri radio://0/80/2M/E7E7E7E705
ros2 run crazyflie reboot  --uri radio://0/80/2M/E7E7E7E705
```

**ROS and mocap** (with `ros2 launch` running):

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

| Symptom | Check |
|---|---|
| `setup.sh` fails: `option --uninstall not recognized` | setuptools ≥ 60. `pip install --user setuptools==58.2.0`, `rm -rf build install log`, re-run |
| `ros2 launch` hangs, no `/all/*` services | An enabled drone doesn't answer, or its URI datarate is wrong. Scan every address (§3.1) |
| Launch aborts: `motion_capture_tracking resolves to the apt package` | `sudo apt remove ros-humble-motion-capture-tracking ros-humble-motion-capture-tracking-interfaces`, `./scripts/build.sh`, re-source |
| `position_received: false` for one drone | Motive rigid-body name ≠ yaml key. Compare `ros2 topic echo /poses --once` |
| `position_received: false` for all drones | Motive not streaming Multicast, or not on Motive's LAN |
| Bridge: `No module named 'crazyflie_py'` | Terminal not sourced with `install/setup.bash` |
| Bridge: `No module named 'api'` | uvicorn not started from `~/S_ENG/CrazySwarm2-with-Mocap` |
| Bridge: `rclpy` / `python3.1x` / miniconda errors | Use `/usr/bin/python3`, or `conda deactivate` |
| Bridge `/health` stuck at `initializing` | `ros2 launch` not up yet, or DDS discovery stalled. Restart the bridge after the server is up |
| Docker 1 `/health` shows `backend_error: ... 8011 ... refused` | Bridge not running, or `.env` `CRAZYSWARM_API_URL` ≠ bridge port |
| Docker 1 errors with `401 Invalid API key` | `CRAZYSWARM_API_KEY` differs between the bridge terminal and `.env` |
| Mission `last_error`: `Unknown drone IDs` or a 404 on `/drones/N/arm` | `config.yaml` `ids` ≠ `curl 127.0.0.1:8011/drones` |
| Mission `last_error`: `Connection refused` to hungarian | Startup race. `docker compose restart mission` |
| Every drone `down` on the second run | Restart the bridge (§7) |
| Reform fails: `Formation returned too few slots` | `sum(old_formation) < len(ids)` |
| `last_move` shows `timeout` with a rising `blocked_count` | Formation shape gets stuck (§2.4, rule 2) |
| Crossed paths / near-collision | Wrong or swapped `initial_position`. Fix before flying again |
| `Motion capture rate off` every second at 50 Hz | `server.yaml` warning range is `[80, 120]`; set it to `[40, 60]` |

---

## 9. How it fits together

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

**Status is the contract.** The bridge reports one field per drone:

- `idle`: no active go-to
- `busy`: a timer. The drone reads `busy` for exactly `distance / velocity` seconds after a
  go-to, whether or not it has arrived. Mission re-reads the position after every hop.
- `down`: the drone was landed through the bridge. Mission treats it as lost. It stays
  `down` until the bridge restarts.

**The reformation loop** (`_execute_reform` in `mission_service/app.py`): mission polls Docker 1.
When a drone flips to `down`, mission asks formation for the new shape and anchors it in the
world. It rejects the plan if targets are closer than `safety_gap`, asks Hungarian who goes
where, then flies each drone in `waypoint_step` hops, front row first. Before each hop it checks
that hop against every other drone's live position.

**Known limits.** There is no geofence, only the pairwise `safety_gap` between commanded
waypoints. Docker 1 and the bridge are single points of failure: if either dies mid-flight,
drones hold their last setpoint. That's why the preflight GUI E-STOP stays open.
