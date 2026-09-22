# Quickstart: drone_reformation and CrazySwarm2-with-Mocap on real hardware

> This document is written in ASD-STE100 Simplified Technical English.

This guide is a run-book for **real Crazyflie drones with OptiTrack only**. It is not for the
simulator. The command for the simulator is `ros2 launch crazyflie launch.py backend:=sim`, and
it needs `scripts/setup_sim_firmware.sh`. Ignore AirSim. AirSim is only an old backend in
drone_reformation.

The guide has two parts. Do **Part 1** one time for each machine. Do **Part 2** at each test
session, in order, from Step 0 to Step 5.

Two repositories work together, and they connect through one HTTP contract:

- `~/S_ENG/CrazySwarm2-with-Mocap`: ROS 2, the mocap driver, and the **bridge** (`api/app.py`)
  on **`127.0.0.1:8011`**
- `~/S_ENG/drone_reformation`: the six-container reformation stack on `:8001` to `:8006`

More data:
CrazySwarm2-with-Mocap [RUNNING](../../CrazySwarm2-with-Mocap/docs/RUNNING.md) ·
[MOCAP](../../CrazySwarm2-with-Mocap/docs/MOCAP.md) ·
[TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md) ·
drone_reformation [README](../README.md) ·
[README_EXPLAINED](README_EXPLAINED.md)

---

## Contents

- [Terms](#terms)
- [Layout and ports](#layout-and-ports)
- [Part 1: One-time setup](#part-1-one-time-setup)
  - [1A. Install the CrazySwarm2 hardware stack](#1a-install-the-crazyswarm2-hardware-stack)
  - [1B. Set the hardware config, once per drone set](#1b-set-the-hardware-config-once-per-drone-set)
  - [1C. Install and configure drone_reformation](#1c-install-and-configure-drone_reformation)
- [Part 2: Every test session](#part-2-every-test-session)
  - [Step 0: Make the drone IDs agree](#step-0-make-the-drone-ids-agree)
  - [Step 1: Physical pre-flight check](#step-1-physical-pre-flight-check)
  - [Step 2: Start the CrazySwarm2 hardware stack](#step-2-start-the-crazyswarm2-hardware-stack)
  - [Step 3: Check the bridge, then start drone_reformation](#step-3-check-the-bridge-then-start-drone_reformation)
  - [Step 4: Fly](#step-4-fly)
  - [Step 5: Land and shut down](#step-5-land-and-shut-down)
- [Docker container commands](#docker-container-commands)
- [Find faults](#find-faults)

---

## Terms

This guide uses one term for each thing.

- **IRL test**: a flight test with a real Crazyflie drone, and not the simulator.
- **CrazySwarm2-with-Mocap**: the ROS 2 stack that speaks to the drone hardware over the radio.
  This repository holds the Crazyradio.
- **drone_reformation**: the six-container stack. It decides where each drone goes, and it
  sends the move commands to CrazySwarm2-with-Mocap.
- **the bridge**: `api/app.py` in CrazySwarm2-with-Mocap. It changes each HTTP request from
  drone_reformation into a ROS 2 call. Its default address is `http://127.0.0.1:8011`.
- **Motive**: the OptiTrack software on the mocap PC. It tracks each drone and streams the
  position to CrazySwarm2-with-Mocap.
- **Crazyradio**: the USB radio dongle. Only one program can hold it at a time.
- **E-STOP**: the emergency stop. It stops the power to the drone motors immediately.

---

## Layout and ports

```text
~/S_ENG/
├── CrazySwarm2-with-Mocap/
│   ├── api/app.py                    # the bridge on 127.0.0.1:8011 (install_bridge.sh copies it in)
│   ├── scripts/setup.sh              # deps + colcon build + mocap-driver check
│   └── src/crazyswarm2/crazyflie/config/
│       ├── crazyflies.yaml           # which drones exist + initial_position
│       └── motion_capture.yaml       # where Motive is
└── drone_reformation/
    ├── .env                          # DRONE_MODE, CRAZYSWARM_API_URL, MISSION_AUTO_START
    ├── config.yaml                   # drone ids, formation, safety gap
    ├── scripts/startup_all.sh        # starts the stack
    ├── scripts/install_bridge.sh     # copies api/ into the CrazySwarm workspace (1C)
    ├── scripts/swarm_config.py       # edits crazyflies.yaml + config.yaml together (Step 0)
    └── docs/QUICKSTART.md            # this file
```

| Port | What | Who connects |
|---|---|---|
| `127.0.0.1:8011` | the bridge (`api/app.py`) | only Docker 1 |
| `:8001` | Docker 1 drone-control | mission, visualizer, you |
| `:8002` | Docker 2 hungarian | mission |
| `:8003` | Docker 3 formation | mission |
| `:8004` | Docker 4 mission | downed-simulator, you |
| `:8005` | Docker 5 downed-simulator | you |
| `127.0.0.1:8006` | dashboard: web page with buttons | you, in a browser |

In Docker, the services 2 to 5 and the dashboard listen on `:8000` on the private network of
Docker. That port never gets to the host. Docker N uses the host port `800N`.
**Why:** [How the network works](README_EXPLAINED.md#how-the-network-works).

---

## Part 1: One-time setup

Do these steps one time for each machine. Do Part 1A first, because drone_reformation depends
on it.

### 1A. Install the CrazySwarm2 hardware stack

1. Go to the CrazySwarm2-with-Mocap folder.

   ```bash
   cd ~/S_ENG/CrazySwarm2-with-Mocap
   ```

2. Install the correct setuptools first. colcon fails on version 60 or higher.

   ```bash
   /usr/bin/python3 -m pip install --user "setuptools==58.2.0"
   ```

3. Run the setup script. It installs the apt and rosdep packages. Then it builds the code with
   colcon.

   ```bash
   ./scripts/setup.sh
   ```

   The `install/` directory must exist after this step. If it does not exist, the build failed.
   Refer to [TROUBLESHOOTING](../../CrazySwarm2-with-Mocap/docs/TROUBLESHOOTING.md).

4. Install the extra packages that the setup script does not cover.

   ```bash
   sudo apt install -y python3-matplotlib python3-tk python3-scipy ros-$ROS_DISTRO-joy
   pip3 install --user rowan "numpy<2"
   ```

5. Set up the USB permissions for the Crazyradio dongle. Run this block one time.

   ```bash
   sudo groupadd plugdev 2>/dev/null; sudo usermod -aG plugdev $USER
   cat <<'EOF' | sudo tee /etc/udev/rules.d/99-bitcraze.rules > /dev/null
   SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="7777", MODE="0664", GROUP="plugdev"
   SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="0101", MODE="0664", GROUP="plugdev"
   SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", MODE="0664", GROUP="plugdev"
   EOF
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

   > Log out and log in again after this step. The new USB group does not apply before you do
   > this.

6. Do not run the simulator firmware step (`setup_sim_firmware.sh`). It is only for the
   simulator, and not for an IRL test.

### 1B. Set the hardware config, once per drone set

Do this part before the first flight. Do it again when the drone set or the mocap PC changes.

**Four places must agree.** Each place holds a part of the same drone set.

| Where | What it sets |
|---|---|
| `crazyflies.yaml` | which drones exist, their radio URI, and where they start |
| Motive rigid bodies | which mocap pose belongs to which drone, matched **by name** |
| `motion_capture.yaml` | where Motive is, and its stream rate |
| drone_reformation `config.yaml` | which IDs mission flies, and the formation |

The two CrazySwarm files are in
`~/S_ENG/CrazySwarm2-with-Mocap/src/crazyswarm2/crazyflie/config/`.

1. Open `crazyflies.yaml`. Set `enabled: true` for each drone that you fly. Set
   `enabled: false` for each other drone.

   WARNING: GIVE EACH DRONE ITS OWN `initial_position`, MEASURED FROM `/poses`. KEEP THE DRONES
   1 M OR MORE APART. POSITIONS THAT YOU EXCHANGE CAUSE CROSSED PATHS. A COLLISION CAN CAUSE
   INJURY.

   > The numeric ID of a drone is the last byte of its URI, read as hex. Thus `…E705` is 5, but
   > `…E710` is 16. drone_reformation must use these numbers. `swarm_config.py` does this
   > conversion for you (Step 0).

2. Open `motion_capture.yaml`. Set the hostname or the IP address to the mocap PC that runs
   Motive. Set the QoS `deadline` Hz to the Motive frame rate.

3. On the mocap PC, open Motive. Make one rigid body for each drone, with the same name as its
   yaml key. Set the stream to **Multicast, 50 Hz**. This value must agree with the `deadline`
   Hz from step 2.

**The drone_reformation `config.yaml`.** The IDs must agree with the enabled drones exactly.
Two rules apply to the formation, and nothing in the code checks them:

1. **`sum(old_formation)` must equal `len(ids)`.** If it does not, the reform can fail with
   `Formation returned too few slots`.
   **Why:** [README_EXPLAINED §12.1](README_EXPLAINED.md#121-sumold_formation-does-not-agree-with-lendronesids-do-this-check-first).
2. **Each row must be wider than the row in front.** Use `[N]`, `[1,2]`, `[2,3]` or `[1,2,3]`.
   A row that repeats or that gets narrower makes a drone stuck.
   **Why:** [README_EXPLAINED §12.10](README_EXPLAINED.md#1210-most-formation-shapes-become-stuck-during-the-reformation).

The `swarm_config.py` script in Step 0 edits `crazyflies.yaml` and `config.yaml` together.

### 1C. Install and configure drone_reformation

1. Go to the drone_reformation folder.

   ```bash
   cd ~/S_ENG/drone_reformation
   ```

2. Install the bridge and its dependencies.

   ```bash
   ./scripts/install_bridge.sh --deps
   ```

   The bridge is **not** in the workspace by default. This script copies `api/` in, and it
   installs fastapi and uvicorn. A missing `api/` folder is the usual reason that the bridge
   does not start. Run the script again at any time to get later changes to the bridge.

3. Make your own config files from the example files.

   ```bash
   cp .env.example .env
   cp config.example.yaml config.yaml
   ```

4. Open `config.yaml`. Set `drones.hover_z` to the hover height in metres above the floor. A
   positive value is up.

5. Open `.env`. Find `MISSION_AUTO_START`. Set it to `0` for your first hardware tests.

   WARNING: WITH `MISSION_AUTO_START=1`, A START OR A RESTART OF THE MISSION CONTAINER ARMS THE
   DRONES AND TAKES OFF. THE DRONES MOVE WITH NO EXTRA WARNING. KEEP THIS VALUE AT `0` UNTIL YOU
   TRUST YOUR FULL SETUP.

   **A change to `.env` needs a new container, and not a restart.** Run
   `docker compose up -d mission` after you edit `.env`. A plain restart keeps the old value.

One-time setup is done. Use Part 2 for each test session after this.

---

## Part 2: Every test session

Do these steps in order at each IRL test.

### Step 0: Make the drone IDs agree

The IDs in `crazyflies.yaml` and `config.yaml` must be the same on the two sides. The
`swarm_config.py` script sets them together. It also changes the drone numbers into the hex IDs
of the bridge for you. Give the drone numbers with a space between each one.

```bash
cd ~/S_ENG/drone_reformation
./scripts/swarm_config.py show                     # both configs side by side + any mismatch
./scripts/swarm_config.py set 1 2 --formation 1,2  # fly exactly these drones, on both sides
```

Refer to [1B](#1b-set-the-hardware-config-once-per-drone-set) for the two formation rules. To
read the start positions from `/poses`, run `./scripts/swarm_config.py pos` after Step 2.

### Step 1: Physical pre-flight check

WARNING: FIND THE E-STOP BEFORE YOU ARM ANY DRONE. THE E-STOP IS THE `e` KEY IN THE PREFLIGHT
GUI. A DRONE THAT YOU CANNOT STOP CAN CAUSE INJURY.

1. Clear the flight area. Keep persons and objects out of the mocap volume.
2. Connect the host PC to the Motive network, by Ethernet or by WiFi.
3. Make sure that the Crazyradio dongle is in the host PC.
4. Power on each drone that you fly. Do a check of the LEDs against the table below.

| LED state | Meaning |
|---|---|
| Blue LEDs lit, front-right LED blinks red two times each second | Ready to fly |
| Blue LEDs lit, front-right LED blinks red every 2 seconds | Not calibrated. Put the drone on a level surface and keep it still |
| Front-left LED flickers red and green | Radio connected |
| Front-right LED fully red | Battery low. Land and recharge |
| Back-left blue LED blinks, back-right blue LED lit | Charging |
| Both back blue LEDs blink about one time each second | Boot loader mode |
| Front-right LED blinks 5 short red pulses, then pauses | Self-test failed. Do not fly this drone |

5. Do a check of each battery in the preflight GUI. A voltage above 3.8 V is good. A voltage of
   3.7 V to 3.8 V is low. A voltage below 3.7 V means do not fly.

   WARNING: DO NOT FLY A DRONE WITH A VOLTAGE BELOW 3.7 V. THE DRONE CAN LOSE POWER AND FALL. A
   DRONE THAT FALLS CAN CAUSE INJURY.

### Step 2: Start the CrazySwarm2 hardware stack

1. Open Terminal 1. Source the ROS 2 environment. Then start the server.

   ```bash
   source /opt/ros/$ROS_DISTRO/setup.bash
   source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
   ros2 launch crazyflie launch.py
   ```

   This one command starts the mocap node, the crazyflie server, RViz, the preflight GUI, and
   the bridge together.

2. Read the preflight GUI. Do a check of each item below before you arm any drone.

   - The mocap rate holds near 50 Hz, with steady latency.
   - The orientation error `err.yaw` stays at 5° or less. A red banner above 10° means stop. In
     Motive, delete the drone body. Then select it again and make a new rigid body.
   - The Kalman position estimate settles near zero while the drone is still. Push `r` on a
     drone that does not settle.
   - Each drone that you fly shows as connected and enabled.

The full checklist is in [RUNNING §C](../../CrazySwarm2-with-Mocap/docs/RUNNING.md).

### Step 3: Check the bridge, then start drone_reformation

1. Make sure that the bridge answers. Use a second terminal.

   ```bash
   curl http://127.0.0.1:8011/health
   curl http://127.0.0.1:8011/drones/status | python3 -m json.tool
   ```

   `/health` must give `"ready": true`. `/drones/status` must show live positions. If either
   command fails, stop here. Correct the CrazySwarm2-with-Mocap launch before you go on.

   If the bridge does not answer, start it by hand in its own terminal. All of the three lines
   are necessary:

   ```bash
   source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash
   cd ~/S_ENG/CrazySwarm2-with-Mocap          # api.app must be importable from here
   /usr/bin/python3 -m uvicorn api.app:app --host 127.0.0.1 --port 8011
   ```

   | Line not done | What you get |
   |---|---|
   | `source` | `ModuleNotFoundError: No module named 'crazyflie_py'` |
   | `cd` | `ModuleNotFoundError: No module named 'api'` |
   | `/usr/bin/python3` | `rclpy` is missing, or you get a conda error |

2. Go to the drone_reformation folder. Start the stack against the real hardware.

   WARNING: WITH `MISSION_AUTO_START=1`, THIS COMMAND ARMS THE DRONES, TAKES OFF, AND FLIES THE
   FIRST FORMATION IMMEDIATELY. KEEP PERSONS AWAY FROM THE FLIGHT AREA.

   ```bash
   cd ~/S_ENG/drone_reformation
   ./scripts/startup_all.sh --crazyswarm
   ```

   Add `--with-visualizer` to also open the OpenCV window. It needs an X11 display.

   ```bash
   xhost +local:docker
   ./scripts/startup_all.sh --crazyswarm --with-visualizer
   ```

3. Open the dashboard in a browser at `http://localhost:8006`.

4. Make sure that drone-control is healthy.

   ```bash
   curl http://localhost:8001/health | python3 -m json.tool
   curl http://localhost:8001/drones/status | python3 -m json.tool
   ```

### Step 4: Fly

With `MISSION_AUTO_START=0`, the mission does not start on its own. Start it by hand. Use the
dashboard, or send the request:

```bash
curl -X POST http://localhost:8004/start \
  -H 'Content-Type: application/json' \
  -d '{"setup_hover":true}'
```

WARNING: WITH `MISSION_AUTO_START=1`, THE MISSION TAKES OFF AS SOON AS THE MISSION CONTAINER
STARTS OR RESTARTS. USE THIS VALUE ONLY WHEN YOU TRUST YOUR FULL SETUP. KEEP PERSONS AWAY FROM
THE FLIGHT AREA.

Always make sure that the mission started. `/health` answers `ok` also when the worker is dead.

```bash
curl -s http://localhost:8004/status | python3 -m json.tool
```

`running` must be `true`, and `last_error` must be `null`. There is a known race at startup:
mission gives `Connection refused` to hungarian. To correct it, run
`docker compose restart mission`.
**Why:** [README_EXPLAINED §12.5](README_EXPLAINED.md#125-health-gives-incorrect-data-about-mission).

To test a drone loss and watch the reform, down a drone:

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":[2],"disarm":true}'
```

Then read the result:

```bash
curl http://localhost:8004/status      | python3 -m json.tool   # last_downed, last_error
curl http://localhost:8004/last_reform | python3 -m json.tool   # active_ids, targets, assignment
curl http://localhost:8004/last_move   | python3 -m json.tool   # each drone: arrived | timeout
```

The test is good if `last_reform.downed` gives the drone, if `active_ids` gives each other
drone, and if each `last_move` entry gives `arrived`.

### Step 5: Land and shut down

1. Land each drone. Use the dashboard, the preflight GUI, or the joystick.
2. Stop the drone_reformation stack.

   ```bash
   ./scripts/shutdown_all.sh
   ```

3. Go to Terminal 1. Push Ctrl-C to stop the CrazySwarm2-with-Mocap launch. Push Ctrl-C in the
   bridge terminal too, if you started the bridge by hand.
4. Make sure that each drone LED returns to green. A green LED means that no program holds the
   drone.
5. Power off each drone. Recharge each battery that you used.

#### Between two runs

- **The bridge never clears a `down` mark.** Each land command marks a drone as `down` until
  the bridge process restarts. The symptom is that each drone is `down` on the second run. To
  correct it, start the bridge again.
- **The one-time flags of mission never reset.** A `/stop` and then a `/start` do not take off
  again. To correct it, run `docker compose restart mission`.
  **Why:** [README_EXPLAINED §12.6](README_EXPLAINED.md#126-the-one-time-flags-never-reset).

#### Emergency stop

WARNING: THE E-STOP STOPS THE MOTORS AND THE DRONE FALLS. KEEP PERSONS AWAY FROM THE AREA BELOW
THE DRONES. A DRONE THAT FALLS CAN CAUSE INJURY.

The **E-STOP in the preflight GUI** is the primary emergency stop. Push the `e` key, or push
**E-STOP (all)**. These are the alternative methods:

```bash
ros2 service call /all/emergency std_srvs/srv/Empty      # every drone, straight through ROS
curl -X POST 127.0.0.1:8011/drones/5/emergency \
  -H 'Content-Type: application/json' -d '{"confirm": true}'   # one drone via the bridge
```

After an emergency stop, the firmware ignores each command. Remove and apply the drone power by
hand to make it operate again. Docker 1 has **no** `/estop` route, and the dashboard has no
emergency stop.

---

## Docker container commands

There is no single gateway port. Each container publishes its own port on the host, and Docker
N uses port `800N`. The visualizer (Docker 6) has no port, because it is a desktop window. The
dashboard is a later addition, and it took the next free number, 8006.

**Docker 1, drone-control (`:8001`).** The only container that speaks to CrazySwarm2-with-Mocap.
Mission calls it for you, but you can also call it directly.

```bash
curl http://localhost:8001/health          | python3 -m json.tool
curl http://localhost:8001/states          | python3 -m json.tool
curl http://localhost:8001/drones/status   | python3 -m json.tool
curl http://localhost:8001/drones/1/status | python3 -m json.tool
```

```bash
curl -X POST http://localhost:8001/setup_hover \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":null}'
```

```bash
curl -X POST http://localhost:8001/move_to_xy_z \
  -H 'Content-Type: application/json' \
  -d '{"drone_id":1,"x":0.5,"y":0.0,"z":1.0,"velocity":0.5}'
```

Watch the status of one drone during a flight:

```bash
watch -n 0.2 'curl -s http://localhost:8001/drones/1/status | python3 -m json.tool'
```

**Docker 2, hungarian (`:8002`) and Docker 3, formation (`:8003`).** Mission calls these two
for you: `POST /assign` on hungarian, and `POST /formation` on formation. Read
`curl http://localhost:8004/last_reform` to see what they decided.

**Docker 4, mission (`:8004`).** The orchestrator. Talk to this container to start, to check,
and to read a mission.

```bash
curl -X POST http://localhost:8004/start \
  -H 'Content-Type: application/json' \
  -d '{"setup_hover":true}'
```

```bash
curl http://localhost:8004/status      | python3 -m json.tool
curl http://localhost:8004/last_reform | python3 -m json.tool
curl http://localhost:8004/last_move   | python3 -m json.tool
```

**Docker 5, downed-simulator (`:8005`).** Down a drone by ID, or down a random count.

```bash
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"drone_ids":[2],"disarm":true}'
curl -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' \
  -d '{"count":2,"disarm":true}'
```

**Docker 6, visualizer.** No commands. It is a desktop OpenCV window. Start it with the
`--with-visualizer` flag in Step 3.

**Dashboard (`:8006`).** Open it in a browser at `http://localhost:8006`. Do not call it with
curl.

---

## Find faults

```bash
source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash   # every ROS terminal
```

**Radio.** Stop `ros2 launch` first, because it holds the radio:

```bash
lsusb | grep 1915                                            # Crazyradio present? (1915:7777)
ros2 run crazyflie scan --address 0xE7E7E7E705               # URI(s) that answer
ros2 run crazyflie battery --uri radio://0/80/2M/E7E7E7E705
```

**ROS and mocap.** Use these commands while `ros2 launch` runs:

```bash
ros2 node list                            # /crazyflie_server, /motion_capture_tracking
ros2 topic hz /poses                      # about 50
ros2 topic echo /poses --once             # rigid-body names + positions from Motive
```

**Bridge and stack:**

```bash
curl -s 127.0.0.1:8011/drones/status | python3 -m json.tool  # idle|busy|down + positions
cd ~/S_ENG/drone_reformation
docker compose ps
docker compose logs -f drone-control      # or mission, formation, hungarian, downed-simulator
curl -s localhost:8001/health | python3 -m json.tool   # mode, and backend.upstream = bridge health
```

| Symptom | What to do |
|---|---|
| `setup.sh` fails: `option --uninstall not recognized` | setuptools is 60 or higher. Run `pip install --user setuptools==58.2.0` and `rm -rf build install log`, then run it again (1A) |
| `ros2 launch` stops, no `/all/*` services | An enabled drone does not answer, or the datarate in its URI is incorrect. Scan each address (Step 1) |
| `position_received: false` for one drone | The Motive rigid-body name does not agree with the yaml key. Compare them with `ros2 topic echo /poses --once` |
| `position_received: false` for each drone | Motive does not stream Multicast, or you are not on the Motive network |
| Bridge: `No module named 'crazyflie_py'` | You did not source the terminal with `install/setup.bash` (Step 3) |
| Bridge: `No module named 'api'` | You did not start uvicorn from `~/S_ENG/CrazySwarm2-with-Mocap`, **or** nobody copied `api/` in. Run `ls ~/S_ENG/CrazySwarm2-with-Mocap/api`, then `./scripts/install_bridge.sh` (1C) |
| Bridge `/health` stays at `initializing` | `ros2 launch` is not up, or the DDS discovery stopped. Start the bridge again after the server is up |
| Docker 1 `/health` shows `backend_error: ... 8011 ... refused` | The bridge is not running, or `CRAZYSWARM_API_URL` in `.env` does not agree with the port of the bridge |
| Docker 1 gives `401 Invalid API key` | `CRAZYSWARM_API_KEY` is different in the bridge terminal and in `.env` |
| Mission `last_error`: `Unknown drone IDs`, or a 404 on `/drones/N/arm` | The `ids` in `config.yaml` do not agree with `curl 127.0.0.1:8011/drones` |
| Mission `last_error`: `Connection refused` to hungarian | A race at startup. Run `docker compose restart mission` |
| Each drone is `down` on the second run | Start the bridge again (Between two runs) |
| Reform fails: `Formation returned too few slots` | `sum(old_formation) < len(ids)` ([why](README_EXPLAINED.md#121-sumold_formation-does-not-agree-with-lendronesids-do-this-check-first)) |
| `last_move` shows `timeout` with a `blocked_count` that increases | The shape of the formation becomes stuck (1B; [why](README_EXPLAINED.md#1210-most-formation-shapes-become-stuck-during-the-reformation)) |
| Crossed paths, or a near collision | The `initial_position` values are incorrect or exchanged. Correct them before you fly again |

For problems in the stack, use
[README_EXPLAINED §15, Checklist for faults](README_EXPLAINED.md#15-checklist-for-faults).
Examples of these problems are: nothing reforms, the drones stop too soon, or the visualizer is
blank.
