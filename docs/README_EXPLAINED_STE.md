# README_EXPLAINED: How the Drone Reformation Stack Operates

> This document is written in ASD-STE100 Simplified Technical English.

This document is a companion to [README_STE.md](../README_STE.md). The main README tells you
**what to run**. This document tells you **why each part exists, how the data moves between
the parts, what each setting does, and where the traps are**.

This document does not replace the main README. You start the system with
`./scripts/startup_all.sh`. For the steps of a run on real drones, use
[QUICKSTART_STE.md](QUICKSTART_STE.md). Its steps link to this document.

---

## 1. A short description of the system

Six containers operate together. They hold a group of Crazyflie drones in a formation.

A drone "dies" when it lands and disarms. Then the system does these steps:

1. The system finds that the drone is gone.
2. It calculates a new, smaller shape for the drones that are left.
3. It decides which of these drones moves into which spot.
4. It moves each drone to its new spot in small steps. It rejects each step that would put the
   drone too near to another drone.

**One** container only can speak to the drone hardware. Each other container speaks plain
HTTP. The other containers know nothing about ROS 2, CrazySwarm, or AirSim.

---

## 2. Why the design is like this

The main rule is **backend isolation**:

> Docker 1 (`drone-control`) is the *only* service that speaks to a flight backend.
> Each other service speaks plain HTTP, and the backend has no importance to it.

That rule gives you three things:

1. **You can change the backend.** `DRONE_MODE` selects one of three backends. `crazyswarm`
   uses real drones through ROS 2. `mock` uses pure Python with no hardware. `airsim` is old,
   but the code keeps it for compatibility. The mission, formation, Hungarian,
   downed-simulator and visualizer services run the same code in the three conditions.
2. **You can do a safe test.** Set `DRONE_MODE=mock`. Then you can run the full reformation
   algorithm with no drones, no simulator and no ROS.
3. **Two commands never overlap.** Docker 1 holds one lock around each command. Thus two
   services can never send flight commands that have a conflict at the same time.

The disadvantage is that Docker 1 is a bottleneck. If it stops, the full system stops. This
was an intentional trade.

---

## 3. The six containers

| # | Service | Container port | Host port | Keeps state? | Speaks to |
|---|---------|---------------|-----------|-----------|----------|
| 1 | `drone-control` | 8001 (host net) | `localhost:8001` | last command only | CrazySwarm API, AirSim, or the mock in memory |
| 2 | `hungarian` | 8000 | `localhost:8002` | **no** | nobody (a pure function) |
| 3 | `formation` | 8000 | `localhost:8003` | **no** | nobody (a pure function) |
| 4 | `mission` | 8000 | `localhost:8004` | **yes: this is the brain** | Docker 1, 2, 3 |
| 5 | `downed-simulator` | 8000 | `localhost:8005` | no | Docker 4 |
| 6 | `visualizer` | none | OpenCV window | no | Docker 1 |
| none | `dashboard` | 8000 | `127.0.0.1:8006` | no | Docker 1, 4, 5 (it forwards requests only) |

The services 2 and 3 are functions behind an HTTP endpoint. You can send them a `curl` request
with invented numbers. They answer correctly with no drones. This is the fastest method to
learn the algorithm.

### How the network works

This part is difficult, thus here is the full description. Refer to
[docker-compose.yml](../docker-compose.yml):

- **Docker 1 uses `network_mode: host`.** It has no `ports:` entry, because it does not need
  one. Uvicorn binds `0.0.0.0:8001` directly on your machine. Thus Docker 1 can get to the
  CrazySwarm API at `127.0.0.1:8011` on the host.
- **The containers 2 to 5 are on the usual compose bridge network.** They find each other by
  the name of the service: `http://formation:8000`, `http://hungarian:8000`,
  `http://mission:8000`.
- **Docker 4 and Docker 6 get to Docker 1 at `host.docker.internal:8001`.** The
  `extra_hosts: host-gateway` line makes that name operate. They cannot use the name
  `drone-control`, because Docker 1 is not on the bridge network.

<pre style="color:#ffffff;background:#1b1b1b;border:1px solid #3a3a3a;padding:12px;border-radius:6px;overflow-x:auto;font-family:Menlo,Consolas,'DejaVu Sans Mono',monospace;font-size:12px;line-height:1.15">
  you                                     5  downed-simulator
  (curl / scripts)                            :8005
    ┃                                           ┃
    ┃ POST /start                               ┃ POST /simulate_downed
    ┃      /reform_now                          ┃
    ┃      /simulate_downed                     ┃
    ┗━━━━━━━━━━━┓                           ┏━━━┛
                ▼                           ▼
      ┌───────────────────────────────────────────────┐
      │              4   mission    :8004             │
      │                                               │
      │       the only service that gives orders      │
      └──┰───────────────┰───────────────────────┰────┘
         ┃ POST          ┃ POST                  ┃  GET  /states
         ┃ /formation    ┃ /assign               ┃  POST /setup_hover
         ┃               ┃                       ┃  POST /move_to_xy_z
         ┃               ┃                       ┃  POST /down
         ▼               ▼                       ▼
  ┌────────────┐  ┌────────────┐  ┌────────────────────────────┐
  │3 formation │  │2 hungarian │  │      1  drone-control      │
  │   :8003    │  │   :8002    │  │    :8001   host network    │
  └────────────┘  └────────────┘  └─────┰────────────────▲─────┘
                                        ┃                ┃ GET /states_vis
        arm · takeoff · go-to · land    ┃                ┃
                                        ▼                ┃
                                ┌──────────────┐ ┌───────┸──────┐
                                │  CrazySwarm  │ │6  visualizer │
                                │mock · AirSim │ │OpenCV window │
                                └──────────────┘ └──────────────┘
</pre>

Each arrow points in the direction of the **call**. The replies go back along the same arrow,
thus the diagram does not show them. The diagram shows three important points:

- **Only you and Docker 5 point into mission.** Nobody tells mission anything. Mission gets
  the data that it needs on its own poll loop. Thus a real battery failure and a simulated
  loss use exactly the same path.
- **The arrow of the visualizer points up.** Docker 6 calls Docker 1. Docker 1 does not call
  Docker 6, and it does not know that Docker 6 exists.
- **Only Docker 1 touches the bottom box.** That single arrow is the full hardware boundary.

### What `startup_all.sh` does

[scripts/startup_all.sh](../scripts/startup_all.sh) starts the stack for you. It does these
steps in sequence:

1. **It reads your options.** `--crazyswarm`, `--mock` and `--airsim` change `DRONE_MODE` in
   `.env`. **The change stays.** If you run `--mock` one time, the later runs are also mock,
   until you run `--crazyswarm`.
2. **It makes sure that `docker`, `curl` and `docker-compose.yml` exist.** If one is missing,
   the script stops.
3. **It makes the config files that are missing.** If there is no `.env`, it copies
   `.env.example`. If there is no `config.yaml`, it copies `config.example.yaml`. It prints
   one line when it does this, and you can miss that line. Thus a new clone runs 9 drones in
   `crazyswarm` mode.
4. **It builds** Docker 1 to Docker 5 and the dashboard. Add `--with-visualizer` to build
   Docker 6 also.
5. **It starts** the containers in the background. With `--foreground` you see the logs, and
   the script ends here.
6. **It waits** until the ports `:8001` to `:8006` answer `/health`. Each port gets 60
   seconds. If one port does not answer, the script stops with an error.
7. **It prints "Ready."** and the address of each service.

| Option | What it does |
|---|---|
| `--crazyswarm`, `--mock`, `--airsim` | Sets `DRONE_MODE` in `.env`. The value stays for the later runs |
| `--no-build` | Does not do the build |
| `--foreground` | Shows the logs. Does not wait for health |
| `--with-visualizer` | Starts Docker 6 also. Run `xhost +local:docker` first |
| `--no-wait` | Does not wait for health |
| `--compose FILE`, `--env FILE` | Uses a different compose file or env file |
| `--config FILE` | Makes sure that the file exists. Compose continues to use `./config.yaml` |

The script does **not** do these things:

- **It does not start the CrazySwarm bridge** on `:8011`. You must start the bridge first.
  Refer to [QUICKSTART §3.3](QUICKSTART_STE.md#33-terminal-2-the-bridge).
- **"Ready." does not mean that the mission is running.** It means only that each service
  answered. The `/health` route of mission gives `ok` also when its worker stopped with an
  error (§12.5). Do a check of `running` and `last_error` with
  `curl -s http://localhost:8004/status`.

`./scripts/shutdown_all.sh` does the opposite. It tells mission to land and disarm each drone.
Then it removes the containers. With `--no-land` it only stops the mission loop, and it does
not land the drones.

For the full start procedure on real drones, refer to
[QUICKSTART §3.4](QUICKSTART_STE.md#34-terminal-3-the-stack).

### The dashboard on port 8006

[src/dashboard_service/](../src/dashboard_service/) is a web page with buttons for the usual
steps. Open http://localhost:8006 after `startup_all.sh`.

The page refreshes each second. It shows:

- the status of each drone (`idle`, `busy` or `down`), its position, its battery, and a map
  from above
- the mission status, which includes `last_error`
- the last reform: which drone went to which spot, and how each move ended

Its buttons are **Start mission**, **Stop mission loop**, **Reform now**, **Land all & stop**,
**Down** (one for each drone) and **Down random**.

The page has two tabs. The layout is the same as the mission console in
CrazySwarm2-with-Mocap (`console/mission_console/`). **Status** holds the items above, and
**Config** holds the three cards below.

**Drone parameters.** This card is a form. It has each setting that the services read from
`config.yaml`:

- the hover height
- the takeoff time and the land time
- the spacing and the safety gap
- the hop length and the speed
- the position of the formation
- the other values

Each field tells you what it does and which service reads it. When you save, the card writes
only the lines that you changed. It keeps your comments. It makes sure that the result parses
as YAML, and it keeps a backup in `config_backups/`.

**config.yaml, as text.** This card shows the same file in a plain editor. Use it for the
items that the form does not have, for example `initial_positions`. The card does a parse
check before it writes, and it keeps the same backup.

The page also gives a warning about the conditions that no other part of the stack finds:

- rows that do not add up to the number of drones (§12.1)
- rows that repeat or that get narrower (§12.10)
- a safety gap that is wider than the spacing
- a hop that is longer than the safety gap
- a `vehicle_names` entry that is missing

The page shows **crazyflies.yaml** as read-only text at the bottom, for reference.

**Drone IDs from CrazySwarm.** This card copies the enabled drones in `crazyflies.yaml` into
`config.yaml`. This is the same edit that `./scripts/swarm_config.py set` makes, and the card
uses that script. It has two steps:

- **Check** reads the two files. It shows the enabled drones, their IDs, and a diff of the
  changes. It writes nothing.
- **Apply** writes `config.yaml`. It keeps a copy of the old file in `config_backups/`.

The IDs come from the radio address, read as hex. Thus `…E712` is **18**, and not 12. If the
number of drones changed, the card suggests new rows. The rows always get wider, thus 5 drones
become `2, 3`. A row that repeats or that gets narrower can make a drone stuck (§12.10).

You can type your own rows. The card rejects them if they do not add up, and it gives a warning if
they get narrower.

`crazyflies.yaml` is mounted read-only, thus this card never edits the CrazySwarm repository.
If the two repositories are not next to each other, point `CRAZYFLIES_DIR` in `.env` at the
config folder. The services read `config.yaml` at startup only. Thus you must run this command
after an edit:

```bash
docker compose restart drone-control mission downed-simulator
```

**How it operates.** The page speaks only to the dashboard. The dashboard sends each click to
Docker 1, Docker 4 or Docker 5, but **only for a fixed list of requests**. That list is
`ALLOWED` in [app.py](../src/dashboard_service/app.py). Thus the page cannot send another
request, for example a request to move a drone to a point. The dashboard is not one of the six
stack services, and no other service needs it.

**Safety:**

- WARNING: THERE IS NO EMERGENCY STOP ON THIS PAGE. THE DASHBOARD CANNOT GET TO THE BRIDGE.
  USE THE E-STOP IN THE PREFLIGHT GUI. A DRONE THAT YOU CANNOT STOP CAN CAUSE INJURY.
- The dashboard listens on `127.0.0.1` only. Thus other machines on the network cannot open
  it.
- The buttons must send JSON. Thus a different website in your browser cannot push them for
  you.
- **Land all & stop** sends the same request that `shutdown_all.sh` sends first. But it lets
  the containers continue to run.
- **Start** after **Stop** does not take off again (§12.6).

---

## 4. The status model: the core idea

The system reduces each drone in each backend to one of three states:

| Status | What it means | Who sets it |
|--------|---------|--------|
| `idle` | No move command is active. The drone holds its last position | upstream |
| `busy` | The move command is still active | upstream |
| `down` | The drone landed, or the system marked it as lost | upstream, or `/down` |

This agreement makes the other parts of the system simple. Mission never looks at the
altitude, the speed, or the AirSim `landed_state` field. It asks for one status word.

`CrazySwarmApiDroneClient._normalize_status_item()` in
[src/drone_control_service/clients.py:131](../src/drone_control_service/clients.py#L131)
changes the upstream data into this shape. The function:

- changes each status that it does not know into `idle`. This is safe. But it also hides an
  upstream typing error instead of a report of it;
- calculates `armed`, `landed` and `downed` from the test `status == "down"`;
- changes `position: {x,y,z}` into the plain fields `x`, `y` and `z`;
- always reports `vx`, `vy` and `vz` as `0.0`. **The CrazySwarm backend does not report the
  speed.** Only the mock backend and the AirSim backend give these values.

Each backend makes this same dictionary. Thus no service above this level can find a
difference between them.

---

## 5. Docker 1: the gateway

[src/drone_control_service/app.py](../src/drone_control_service/app.py) is a thin FastAPI
wrapper. The primary work occurs in
[src/drone_control_service/clients.py](../src/drone_control_service/clients.py).

### Routes

| Route | What it does |
|-------|---------|
| `GET /health` | Can Docker 1 get to the backend? It returns `degraded` with a 200, and not a 5xx, when the backend is down |
| `GET /status` | The last command that went through this gateway |
| `GET /states` | A `{drone_id: state}` map for each configured drone |
| `GET /states_vis` | The same as `/states`. It exists only to give the visualizer a stable name to call |
| `GET /drones/status` | The same data as a list: `{count, drones:[...]}` |
| `GET /drones/{id}/status` | One drone |
| `POST /setup_hover` | arm, then sleep 2 s, then take off, then sleep |
| `POST /hover` | **It does nothing on CrazySwarm.** Refer to the text below |
| `POST /move_to_xy_z` | Go to an absolute position |
| `POST /land` | Land, and disarm if you ask for it |
| `POST /down` | A different name for land. This is how the system "kills" a drone |
| `POST /shutdown` | Land, disarm, and release each resource |

The sequence of the route declarations is important. `/drones/status` is registered **before**
`/drones/{drone_id}/status` at
[app.py:146](../src/drone_control_service/app.py#L146). If it were not, FastAPI would try to
read the word `"status"` as a drone ID number, and it would fail.

### The command wrapper

Each route that changes something goes through `_run()`
([app.py:91](../src/drone_control_service/app.py#L91)):

```python
with _LOCK:                       # one lock for the whole process — commands run one at a time
    result = fn()
    return _record(command, "accepted", drone_ids, result=result)
```

If the backend gives an error, you get **HTTP 502**. Docker 1 saves the failure in
`_LAST_COMMAND`, thus `GET /status` can show you the error. If the drone ID is not known, you
get **HTTP 400**, and Docker 1 does not call the backend.

### `/move_to_xy_z` becomes the `/go-to` of CrazySwarm

Docker 1 keeps the old name of the route, but it rewrites the body. Refer to
[clients.py:235](../src/drone_control_service/clients.py#L235):

```
POST /move_to_xy_z {drone_id, x, y, z, velocity}
   ↓
POST {CRAZYSWARM_API_URL}/drones/{id}/go-to
     {x, y, z, yaw: 0.0, velocity, relative: false, group_mask}
```

The route **returns immediately**. It does not wait for the drone to arrive. To wait is the
task of mission, and mission does it when it polls the status. The mock backend is the
exception: it makes a short pause, and then it moves the drone to the target immediately.

### `setup_hover` is slow for a reason

```python
for id in ids: POST /drones/{id}/arm  {"arm": true}
time.sleep(2.0)                                  # <- the "added sleep after arm" commit
for id in ids: POST /drones/{id}/takeoff {target_height: hover_z, duration, group_mask}
time.sleep(takeoff_duration + command_settle_seconds)
```

That fixed sleep of 2 seconds is necessary, because the Crazyflie firmware needs a gap between
the arm command and the takeoff command. You **cannot** change it from the config, and the
code holds it **in** the global lock. Thus `setup_hover` blocks each other Docker 1 command
for `2.0 + takeoff_duration + command_settle_seconds`. With the default settings this is
about 4.25 seconds. `land` and `down` hold the lock in the same manner for
`land_duration + command_settle_seconds`.

### `/hover` does nothing on CrazySwarm

The CrazySwarm HTTP API has no hover endpoint. Its high-level commands hold their final
position without help. Thus `hover()` returns
`{"status": "accepted", "command": "hold_current_setpoint", ...}` and it sends **nothing**.

CAUTION: DO NOT USE `/hover` TO STOP A DRONE THAT MOVES. THE COMMAND DOES NOTHING, AND THE
DRONE CONTINUES. THE DRONE CAN HIT AN OBJECT AND CAUSE DAMAGE.

### The three backends

| | `crazyswarm` | `mock` | `airsim` |
|---|---|---|---|
| Selected by | `DRONE_MODE=crazyswarm`, `crazyflie` or `ros2` | `DRONE_MODE=mock` | `DRONE_MODE=airsim` or `colosseum` |
| Source of the positions | upstream `/drones/status` | a dictionary in memory | `getMultirotorState()` |
| Which direction is up | **+Z is up** from the floor | +Z is up | **NED, thus −Z is up** (the old `hover_z: -20.0`) |
| How it tracks `busy` | upstream `remaining_seconds` | set and cleared in `move_to_xy_z` | a local `_busy_until` timer |
| Speed reported | always 0 | calculated | real |
| How the moves behave | send and do not wait | sleeps 50 ms or less, then moves immediately | runs in the background, with a timer |
| Authentication | sends `X-API-Key` if `CRAZYSWARM_API_KEY` has a value | none | none |

`make_drone_client()` at [clients.py:653](../src/drone_control_service/clients.py#L653)
selects the backend. The `DRONE_MODE` environment variable has more importance than
`drones.mode` in config.yaml.

The AirSim path also moves the coordinates. It uses `drones.initial_positions`. It adds the
origin of each drone to the positions that it reports. It subtracts the origin from the
positions that you command.

This offset is necessary because each AirSim vehicle reports a position relative to its spawn
point. CrazySwarm reports in one shared world frame, thus the system
applies no offset there. For this reason, `initial_positions` has an effect in the `mock` and
`airsim` modes only.

---
## 6. Docker 3: formation, the geometry

[src/formation_service/app.py](../src/formation_service/app.py) has about 74 lines. It keeps
no state, and it calls no other service.

**You give it:** the "old formation" as a list of row widths, the number of drones that are
down, and a spacing value.
**It gives you:** the row widths of the new smaller shape, and the XY position of each spot.

### `compact_rows()`

```
total  = sum(old_formation)
active = total - downed_drones
```

Then the function fills the rows from the front. It never lets a row become wider than its
first width:

```
old_formation = [1, 2, 3, 2, 1]   (9 drones)

downed = 0 → [1, 2, 3, 2, 1]   (9 spots)
downed = 1 → [1, 2, 3, 2]      (8 spots)
downed = 3 → [1, 2, 3]         (6 spots)
downed = 6 → [1, 2]            (3 spots)
```

The formation always loses depth from the **back**. It never becomes narrower at the front.
This is the `front_compact` policy, and it is the only policy that exists. Each other value of
`policy` returns HTTP 400.

### `make_slots()`: the layout of the coordinates

The Hungarian service depends on this layout. Thus you must learn it:

```
row 0 (front)  y =  0.0            •              ← bigger y = FRONT
row 1          y = -spacing      •   •
row 2          y = -2*spacing  •   •   •
row 3          y = -3*spacing    •   •            ← smaller y = BACK
row 4          y = -4*spacing      •
```

Each row has its centre at `x = 0`. For a row of `n` spots, x starts at
`-0.5 * spacing * (n-1)`, and it increases in steps of `spacing`. A row with one spot is at
`x = 0.0`.

These numbers are **relative**. The origin is the centre of the front row. Mission puts the
spots in the real world (§8).

### How the code sets the shape

There is exactly **one** place in the full system where you set the shape. It is
`mission.old_formation` in [config.yaml](../config.yaml#L48). It is a list of **row widths,
front row first**. No other part of the system knows the shape of the drones.

Here is the full path of the setting:

```
config.yaml   mission.old_formation: [1, 2]
      │
      ▼   read once when the service starts
src/mission_service/app.py:25       OLD_FORMATION = [1, 2]
      │
      ▼   _call_formation() → POST http://formation:8000/formation
src/formation_service/app.py:19     compact_rows([1,2], downed) → [1, 1]
src/formation_service/app.py:39     make_slots([1,1], 0.5)      → [[0,0], [0,-0.5]]
      │
      ▼   slots_relative (measured from the centre of the front row)
src/mission_service/app.py:135      _formation_world_targets() places them in the world
      │
      ▼   real-world XY targets
src/hungarian_service/app.py:34     works out which drone takes which target
      │
      ▼   sorted by cascade_rank
src/mission_service/app.py:250      _move_drone_safely(), one drone at a time
```

Read that list from the bottom to the top, and the design becomes clear. The Hungarian solver
and the mover **know nothing about shapes**. The system gives them a list of XY targets. They
never learn that those targets are a wedge. All of the knowledge of the shape is in the seven
lines of [make_slots()](../src/formation_service/app.py#L39).

Thus `old_formation` is a small language:

| You write | You get | Reforms safely? |
|---|---|---|
| `[1, 2]` | 3-drone wedge: one leader in front, two behind | ✅ |
| `[1, 2, 3]` | 6-drone solid wedge | ✅ |
| `[1, 2, 3, 4]` | 10-drone solid wedge | ✅ |
| `[4]` | 4 drones side by side in one row | ✅ |
| `[1, 2, 3, 2, 1]` | 9-drone diamond | ❌ becomes stuck if drone 4 or drone 6 dies |
| `[3, 3, 3]` | 3×3 square grid | ❌ becomes stuck on 3 of the 9 |
| `[3, 2, 1]` | wedge that points back: wide at the front, one at the back | ❌ |
| `[2, 4, 2]` | hexagon shape | ❌ |
| `[1, 1, 1, 1]` | 4 drones in single file | ❌ always |

The last column is important. **Most of the shapes in this list become stuck during the
reformation.** This includes the diamond that each other example in this document uses. The
test results and the reason are below, in *Why you cannot fly a straight line*.

### How to change the formation

1. Edit `mission.old_formation` in [config.yaml](../config.yaml#L48).
2. Make sure that `sum(old_formation)` equals `len(drones.ids)`. Nothing does this check for
   you, and an error here fails quietly. Refer to §12.1.
3. Change `mission.formation_spacing` if you want. One number sets **both** the gap between
   the drones in a row and the gap between the rows.
4. Run `docker compose restart mission`. A `POST /stop` and then a `POST /start` are not
   enough. The service reads `OLD_FORMATION` when it starts, and it never resets the
   one-time flags (§12.6).

You can do a check of the geometry before a flight, because Docker 3 keeps no state:

```bash
curl -s -X POST http://localhost:8003/formation \
  -H 'Content-Type: application/json' \
  -d '{"old_formation":[3,3,3],"downed_drones":2,"spacing":0.5}' \
  | python3 -m json.tool
```

Look at `new_formation`, which gives the new row widths. Also look at `slots_relative`, which
gives the position of each spot.

### What this service cannot do

`make_slots()` has four rules in its code. You cannot change these rules from the config:

| Rule in the code | What it costs you |
|---|---|
| Row `r` is at `y = -r * spacing` | The rows always have equal spaces. You cannot make some rows nearer than others |
| Each row has its centre at `x = 0` | No shapes that are asymmetric, offset or diagonal |
| One `spacing` number controls the two directions | You cannot make a wide, shallow formation. The gap from side to side and the gap from front to back are always equal |
| The front is always `+y` | The formation has **no heading**. You cannot rotate it, and it does not turn to the direction of travel |

You cannot have these shapes if you do not edit
[src/formation_service/app.py](../src/formation_service/app.py):

- diagonal lines, circles and arcs
- echelon shapes
- a grid with a hole in it
- a rotation
- coordinates that you write for each drone

The API accepts row counts only. You cannot give it a list of positions.

The method to make the formation smaller is also fixed. The code does a check of `policy` at
[app.py:60](../src/formation_service/app.py#L60), and `front_compact` is the only value that
is not an HTTP 400. The losses always come off the **back**. The shape never becomes wider or
narrower, and its proportions never change.

### Why you cannot fly a straight line

Two different shapes have the name "a straight line". Their behavior is fully different.

**Drones side by side, `[N]`, operates correctly.** When one drone dies, the drones that are
left find a new centre and move along the row to it. A test of each possible single loss for
`[3]`, `[4]`, `[5]` and `[9]` gives no failure.

**Drones in single file, `[1, 1, 1, ...]`, always becomes stuck.** And single file is not a
special condition. It is the worst example of a problem that affects **most** of the shapes
here. This includes the 9-drone diamond at the start of this document.

#### What goes wrong

`front_compact` never rearranges the formation. It deletes the **last** spot, and it leaves
each other spot in its position. Thus after a loss:

- Each drone that is already on a spot that still exists has nothing to do. Its travel
  distance is zero.
- One drone only must fill the gap. It is the drone that was on the spot that the code
  deleted.
- The Hungarian solver selects the option with the smallest **total** distance. "One drone
  makes the full trip" costs less than "each drone moves one position". Thus the solver
  selects the first option. This is correct behavior for the solver.

The result is that one drone from the back makes **one long trip through the middle of the
formation**. Each drone that it passes stays in its position.

`_move_drone_safely()` flies that trip as a straight line. It **cannot ask another drone to
move out of the path**. When the next step is not safe, the function can only do
`time.sleep(...)` and do the check again. Refer to
[app.py:288-292](../src/mission_service/app.py#L288-L292).

But the drone in the path already arrived and its turn is complete, thus it never moves. The
wait continues until `max_move_seconds_per_drone`, which is 120 seconds. Then the result is
`status: "timeout"`.

Thus the reformation depends on one question: **is there a space of `safety_gap` or more for
that one straight trip between two occupied spots?**

For single file, the answer is always no. The trip goes exactly along the line of the drone in
front, thus the gap is `0.000`. This has an important result: **an increase of
`formation_spacing` does not help single file.** The drone in the path is on the path at each
value of the spacing.

```
[1,1,1], drone 1 dies → new rows [1,1] → spots (0,0) and (0,-0.5)

  drone 2 (0,-0.5) → (0,-0.5)   travels 0.0  — stays put
  drone 3 (0,-1.0) → (0, 0.0)   travels 1.0  — has to fly through drone 2

  drone 3 creeps forward to (0,-0.75), then stops there forever
```

#### Which shapes operate correctly

Here is a full test. It uses each shape and each possible loss of one drone. The test runs
against the real `compact_rows` and `make_slots` code and the real Hungarian cost code, with
`spacing: 0.5` and `safety_gap: 0.25`:

| `old_formation` | Drones | Becomes stuck if these die | Smallest gap during the trip |
|---|---|---|---|
| `[1, 2]` ← **what you have now** | 3 | never | 0.250 |
| `[3]`, `[4]`, `[5]`, `[9]` | any | never | 0.250 |
| `[1, 2, 3]` | 6 | never | 0.250 |
| `[1, 3]`, `[2, 4]`, `[2, 3, 4]`, `[1, 2, 3, 4]` | various | never | 0.250 |
| `[1, 2, 4]` | 7 | drone 1 | no data |
| `[1, 2, 2]` | 5 | drone 1 | 0.122 |
| `[1, 2, 3, 2, 1]` ← the classic diamond | 9 | drones 4 and 6 | 0.059 |
| `[3, 2, 1]` | 6 | drones 1 and 3 | 0.059 |
| `[2, 4, 2]` | 8 | drones 1 and 2 | 0.000 |
| `[3, 3, 3]` | 9 | drones 1, 2 and 3 | 0.000 |
| `[1, 1, 1]` | 3 | drone 1 | 0.000 |

Look at the last column. **Each shape that operates correctly has a gap of exactly 0.250,
which is equal to `safety_gap`.** The test is `distance < SAFETY_GAP`. Refer to
[app.py:191](../src/mission_service/app.py#L191). It uses "less than", and not "less than or
equal to". Thus a gap that is exactly `safety_gap` is permitted, and the drone goes through.

CAUTION: THERE IS NO MARGIN AT ALL. IF YOU INCREASE `safety_gap` TO 0.3 AND YOU DO NOT ALSO
INCREASE `formation_spacing`, EACH SHAPE IN THAT TABLE BECOMES STUCK. THIS INCLUDES THE SHAPES
THAT OPERATE CORRECTLY TODAY.

The simple rule from those results is:

> **Safe:** one row of drones (`[N]`), or a wedge that becomes wider at each row
> (`[1,2]`, `[1,2,3]`, `[2,3,4]`, `[1,2,3,4]`). No drone is directly behind another drone,
> thus the trip through the middle goes through the half-spacing gap between the rows.
>
> **Becomes stuck:** each shape with a row width that **repeats or that gets smaller**. Rows
> of the same width put the drones at the same x value, thus the trip goes along a line that
> is already occupied.

For this reason the diamond `[1, 2, 3, 2, 1]` is not safe. It is in
[config.example.yaml](../config.example.yaml) and in each diagram in this document. Its front
half becomes wider correctly. But the `3, 2, 1` rows at the back put the drones directly
behind each other. Thus the loss of drone 4 or drone 6 stops the mission.

#### If you must use single file

- **Try not to use it.** `[1, 2]` and `[1, 2, 3]` operate correctly with no change to the
  code.
- **Correct the assignment.** There is already a penalty to stop a drone that jumps this far.
  Its limit is `forward_jump_threshold_multiplier * spacing`, which is `2.0 * 0.5 = 1.0`. The
  test is `forward_delta > forward_jump_threshold`. Refer to
  [app.py:70](../src/hungarian_service/app.py#L70). A jump of one row moves the drone forward
  by exactly `1.0`, and `1.0 > 1.0` is false. Thus the penalty never operates, and it misses
  by the smallest possible value. If you change the multiplier to `1.5`, the penalty operates.
  Then the solver selects the correct plan, where each drone moves one position. A test
  confirms this. But mission never sends these two fields. Refer to
  [`_call_hungarian`](../src/mission_service/app.py#L210). Thus this correction needs a change
  to the code. Refer to §12.11.
- **Let the drones move out of the path.** Change the mover. Let a drone that is blocked make
  the drone in front move to the side. Or move more than one drone at the same time. This is
  the correct correction, and it is much larger than the others.

---

## 7. Docker 2: Hungarian assignment, the matching

[src/hungarian_service/app.py](../src/hungarian_service/app.py) also keeps no state. You give
it the positions of the drones and the positions of the spots. It decides which drone goes to
which spot for the lowest total cost. It uses `scipy.optimize.linear_sum_assignment`.

"Hungarian" is the name of the classic algorithm for this type of problem.

### The cost matrix

The code starts with the straight-line distance:

```python
cost[i][j] = ||current_position[i] - target_position[j]||
```

Then it adds two penalties.

**1. The forward-jump penalty, which is always on.** The front has the bigger y value. Thus a
drone "moves forward" when `target_y > current_y`. If the drone would move forward by more
than `forward_jump_threshold_multiplier * spacing`, the cost increases by
`forward_jump_penalty`. The default multiplier is `2.0`, and the default penalty is `100.0`.

The function of this penalty is to stop a drone at the back when it jumps to the front after a
front drone dies. In place of this, the drone behind the gap must move up. Then the drone
behind that drone takes the empty spot, and this continues. The code calls that chain a
**cascade**.

**2. The backward penalty, which is off by default.** If `backward_penalty` is more than 0,
the code adds that penalty to each spot with `target_y < current_y - backward_threshold`. The
two values are `0.0` in [config.yaml](../config.yaml), thus this penalty is **off**.

The two penalties only add to the cost. They are not absolute rules. A selection with a
penalty can win if each other option costs more than `100.0`. They are strong hints, and not
prohibitions.

### The cascade sequence

After the code solves the matching, it looks at `cascade_front_first`. Mission always sends
`true`. Then the code sorts the results by the current y value, the biggest value first. Thus
the front drones are first. Then each entry gets a `cascade_rank` that starts at 1.

Mission moves the drones **in that sequence, one at a time**. The intention is that the
reformation looks like a wave that moves forward, and not like a scramble. The front drone
leaves its spot before the drone behind it tries to take that spot.

**In operation this cascade almost never occurs.** `front_compact` deletes the *last* spot and
leaves each other spot in its position (§6). Thus each drone that is already on a spot that
still exists has a travel distance of zero. The smallest total distance is then "one drone
from the back flies the full distance", and not a chain of short hops.

The sequence has no effect when one drone only moves. This is the root cause of the problem in
§6 and §12.10. On a real run, `last_reform.hungarian.assignment` usually shows one
`travel_distance` only that is not zero.

Each entry contains `drone_id`, `slot_idx`, `current_position`, `target_position`,
`travel_distance`, `delta_y` and `cascade_rank`.

---
## 8. Docker 4: mission, the brain

[src/mission_service/app.py](../src/mission_service/app.py) is the only service that keeps
state. It is the only service that uses threads, and it is the most complex service. Read this
section two times.

### What occurs, in sequence

When the service starts, it looks at `MISSION_AUTO_START`. If the value is `1`, which is the
default, `_start_worker()` starts a background thread that runs `_mission_loop()`:

<pre style="color:#ffffff;background:#1b1b1b;border:1px solid #3a3a3a;padding:12px;border-radius:6px;overflow-x:auto;font-family:Menlo,Consolas,'DejaVu Sans Mono',monospace;font-size:12px;line-height:1.15">
        ┌────────────────────────────────────────────────────────────┐
        │ 1  _wait_for_control_ready()                               │
        │    poll Docker 1 /health, up to control_ready_timeout      │
        └──────────────────────────────┰─────────────────────────────┘
                                       ▼
        ┌────────────────────────────────────────────────────────────┐
        │ 2  control.setup_hover(DRONE_IDS)                          │
        │    runs once — guarded by _setup_done                      │
        └──────────────────────────────┰─────────────────────────────┘
                                       ▼
        ┌────────────────────────────────────────────────────────────┐
        │ 3  _execute_initial_formation()                            │
        │    runs once — guarded by _initial_formation_done          │
        └──────────────────────────────┰─────────────────────────────┘
                                       ▼
        ┌────────────────────────────────────────────────────────────┐
        │ 4  _last_downed = the drones that are down right now       │
        └──────────────────────────────┰─────────────────────────────┘
                                       ▼
   ┏━━━▶┌────────────────────────────────────────────────────────────┐
   ┃    │ 5  POLL LOOP — every poll_interval seconds                 │
   ┃    │    states = control.get_states()                           │
   ┃    │    downed = _detect_downed(states)                         │
   ┃    └──────────────────────────────┰─────────────────────────────┘
   ┃                                   ▼
   ┃    ┌────────────────────────────────────────────────────────────┐
   ┃    │ 6  has the downed set changed?                             │
   ┃    └───────┰──────────────────────┰─────────────────────────────┘
   ┃        no  ┃                 yes  ┃
   ┣━━━━━━━━━━━━┛                      ▼
   ┃    ┌────────────────────────────────────────────────────────────┐
   ┃    │ 7  newly_downed = downed - _last_downed                    │
   ┃    │    _last_downed = downed                                   │
   ┃    └──────────────────────────────┰─────────────────────────────┘
   ┃                                   ▼
   ┃    ┌────────────────────────────────────────────────────────────┐
   ┃    │ 8  is newly_downed empty?    (a drone came back — §12.4)   │
   ┃    └───────┰──────────────────────┰─────────────────────────────┘
   ┃       yes  ┃                  no  ┃
   ┣━━━━━━━━━━━━┛                      ▼
   ┃    ┌────────────────────────────────────────────────────────────┐
   ┃    │ 9  _execute_reform(states, downed)                         │
   ┃    └──────────────────────────────┰─────────────────────────────┘
   ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
</pre>

`_wait_for_control_ready()` is more strict than a usual health check. It needs
`status == "ok"`, **and** the nested `backend.upstream.ready` field must not be exactly
`False`. If the `ready` key is missing, that is satisfactory. An explicit `false` value blocks
it.

### `_execute_reform()`: the six steps

This is the primary routine. Refer to
[app.py:329](../src/mission_service/app.py#L329):

1. **Find the drones that are alive.** `_active_ids_from_states()` reduces `DRONE_IDS` to the
   drones that are in `/states` and that are not `down`. If no drone is left, it records
   `no_active_drones` and stops.
2. **Ask Docker 3 for the new shape.** It sends `len(downed)` as `downed_drones`.
3. **Change the relative spots into real-world coordinates.** This is
   `_formation_world_targets()`.
4. **Do a safety check of the new shape.** Each pair in the first `len(active_ids)` targets
   must be `safety_gap` apart or more. If not, the code raises a `RuntimeError`.
5. **Ask Docker 2 which drone goes to which spot.** Then sort the result by `cascade_rank`.
6. **Move the drones one at a time**, in that sequence, with `_move_drone_safely()`.

The code saves the steps 1 to 5 in `_last_reform`, and step 6 in `_last_move`. You can read
them at `GET /last_reform` and `GET /last_move`. The code writes `_last_reform` **before** a
drone moves. Thus you can see the plan also when a move fails.

### Where the formation goes: `mission.anchor_policy`

The formation service returns coordinates that are relative to the centre of the front row.
Mission must decide where that centre is in the real world. There are three options. Refer to
[app.py:135](../src/mission_service/app.py#L135):

| Policy | Where the centre goes | What that means |
|---|---|---|
| `active_centroid` | `mean(living drone positions) − mean(all spots)` | Mission calculates this again each time. The formation moves to the position of the drones |
| `initial_anchor` | The same sum, but mission **saves it the first time and uses it again** | The formation stays where the drones started. **This is the default in your config** |
| `origin` | `[0, 0]` | The formation is fixed to the world origin |

`initial_anchor` saves its result in the global `_initial_anchor_xy`. Only a restart of the
container clears this value. Each other value raises a `RuntimeError`.

Note that the code calculates the average across **all** of the spots that it receives, and
not across the spots that it will use. This is important for the trap in §12.1.

### `_move_drone_safely()`: how a drone moves to its spot

Mission never sends a drone directly to its target. It moves the drone in small hops. Refer to
[app.py:250](../src/mission_service/app.py#L250):

```
repeat until arrived, aborted, or MAX_MOVE_SECONDS_PER_DRONE runs out:
    states  = GET /states                      # fresh look every time round
    if this drone is down          → return "aborted_down"
    delta   = target - current
    if |delta| <= target_tolerance → return "arrived"

    waypoint = current + unit(delta) * min(waypoint_step, |delta|)

    if any other living drone is within safety_gap of that waypoint:
        blocked += 1 ; sleep(movement_poll_interval) ; continue     # think again, do not move

    POST /move_to_xy_z (waypoint.x, waypoint.y, hover_z, move_velocity)
    _wait_for_terminal_status(drone, timeout = step_distance/velocity + command_timeout_margin)
    if that status is "down"       → return "aborted_down"
```

Four points are important:

- **The height never changes.** Each hop uses `drones.hover_z`. The full reformation occurs in
  two dimensions. The altitude is a constant.
- **The code does a safety check of one hop, and not of the full route.** The check asks one
  question: is the end of this *next* hop of 0.25 m clear now? One drone only moves at a time,
  thus each other drone is stationary. Thus this one look is enough in operation.
- **A blocked drone waits. This is not a failure.** A blocked drone looks again and tries
  again. It continues until `MAX_MOVE_SECONDS_PER_DRONE` runs out, and then it returns
  `"timeout"`. Two drones can never block each other here, because they move one at a time.
  But a stationary drone *can* block a drone that moves, and the block continues. This is the
  problem in §6.
- **`include_downed_in_safety`**, which is `false` by default, decides if a drone that crashed
  still occupies space. `false` means that the other drones will fly directly above it.

Each entry in `move_results` has a `status` of `arrived`, `aborted_down` or `timeout`. It also
has `steps`, `blocked_count` and the times.

### `_wait_for_terminal_status()`

This function polls `GET /drones/{id}/status` at each `movement_poll_interval` until the status
is `idle` or `down`. It raises `TimeoutError` if the deadline passes. This is the **only**
mechanism that keeps the hops in sequence. There is no completion callback in the system.

### The HTTP routes of mission

| Route | What it does |
|---|---|
| `GET /health` | Says only that the service is alive. It always returns `ok`, and it tells you nothing about the worker |
| `GET /status` | `running`, `setup_done`, `initial_formation_done`, `last_downed`, `last_error`, and the URLs that it found |
| `POST /start` | Starts the worker with `{"setup_hover": true}`. It returns `already_running` if the worker is active |
| `POST /stop` | Sets the stop flag. The loop ends after it completes the current pass |
| `POST /simulate_downed` | Does a check of the IDs, then calls Docker 1 `/down`. **It does not reform.** The poll loop finds the change on its next pass |
| `POST /reform_now` | Does a reform immediately, with the current state |
| `GET /last_reform` | The last plan: the shape, the assignment, and the world targets |
| `GET /last_move` | The last movement report |
| `POST /shutdown` | Stops the loop. Then it lands and disarms each drone through Docker 1 |

**A worker that stopped with an error does not show in `/health`.** If `_mission_loop()`
raises an error, the code stores the error in `_last_error`. Then it sets `_running` to
`false`, and the thread ends quietly. But `/health` continues to answer `{"status": "ok"}`. Always do a
check of `GET /status` for `running` and `last_error`. Never rely on `/health`.

---

## 9. Docker 5: the downed simulator

[src/downed_simulator_service/app.py](../src/downed_simulator_service/app.py) is the smallest
service. Its only task is to select drone IDs and to send them to mission.

```
POST /down {"drone_ids": [2]}       → kill drone 2
POST /down {"count": 2}             → pick two of the configured IDs at random
POST /land {...}                    → same thing as /down
```

The important design point, and the reason for the rewrite of this service, is that it calls
**Docker 4**, and not Docker 1.

```
Docker 5 → POST /simulate_downed → Docker 4 → POST /down → Docker 1 → land + disarm
```

The path through mission keeps one clear chain of command over the drones. Mission learns
about the loss through its own status poll, and not through the call. Thus a drone that dies
for a real reason goes through exactly the same code as a simulated loss. Examples of a real
reason are an empty battery, a crash, or a lost radio link. The simulator gets no special
treatment.

### How to down drones automatically at startup

Set these variables in `.env`:

```bash
AUTO_DOWN_IDS=2,5        # or AUTO_DOWN_COUNT=2 to pick at random
AUTO_DOWN_AFTER_SEC=45   # how long to wait first
```

If `AUTO_DOWN_IDS` or `AUTO_DOWN_COUNT` has a value, a background thread sleeps and then
operates one time. If the two variables have values, `AUTO_DOWN_IDS` wins. The code prints the
errors and does not raise them. Thus do a check of
`docker compose logs downed-simulator`.

CAUTION: `AUTO_DOWN_AFTER_SEC` COUNTS FROM THE START OF *THIS CONTAINER*. THIS IS MUCH EARLIER
THAN THE END OF THE TAKEOFF AND THE FIRST FORMATION. GIVE IT ENOUGH TIME. IF YOU DO NOT,
YOU DOWN A DRONE DURING THE TAKEOFF AND THE DRONE CAN BE DAMAGED.

---

## 10. Docker 6: the visualizer

[src/visualizer_service/viewer.py](../src/visualizer_service/viewer.py) is an OpenCV window.
It polls `GET /states_vis` at `VIS_FPS` times each second.

- A green filled dot is a drone that is alive. A red X is a drone that is dead. A faint circle
  is the radius of the `safety_gap`.
- The conversion from the world to pixels is `px = width/2 + x*scale` and
  `py = height/2 − y*scale`. The code inverts y. Thus the window shows **the front of the
  formation, which has the bigger y value, at the top**.
- `VIS_SCALE=500.0` means 500 pixels for each metre. This value is correct for Crazyflie
  distances, thus a spacing of 0.5 m becomes 250 pixels. The default of `8.0` in the code is
  old and comes from the AirSim period. Compose always replaces it.
- If an error occurs, the code writes the error text into the frame. It does not stop. A window
  that is full of red error text means that the visualizer operates and that Docker 1 does not.
- Set `VIS_HEADLESS_OUTPUT=/app/artefacts/frame.png` to write PNG files in place of a window.
  This is of use through SSH. The system mounts the [artefacts/](../artefacts/) directory for
  this function.

The visualizer is behind the `visualizer` compose profile. Thus it starts only with
`--with-visualizer`. It also needs `xhost +local:docker` and a correct `DISPLAY` value.

---
## 11. Each setting explained

To set up these values for real drones, obey
[QUICKSTART §2](QUICKSTART_STE.md#2-the-settings-four-places-must-agree).

There are two files. If the two files set the same item, the environment variable always wins.

### `.env`: how the parts connect

| Variable | What it does |
|---|---|
| `DRONE_MODE` | `crazyswarm`, `mock` or `airsim`. It beats `drones.mode` |
| `CRAZYSWARM_API_URL` | The address of the upstream API. It beats `drones.crazyswarm_api_url` |
| `CRAZYSWARM_API_KEY` | If it has a value, Docker 1 sends it as an `X-API-Key` header on each upstream request |
| `MISSION_AUTO_START` | `1` means that the mission starts to fly as soon as the container starts |
| `AUTO_DOWN_IDS`, `AUTO_DOWN_COUNT`, `AUTO_DOWN_AFTER_SEC` | Down the drones automatically, for a test |
| `VIS_*`, `SAFETY_GAP`, `DISPLAY` | For the visualizer only |

### `config.yaml`: Docker 1, 4 and 5 read this file

The system mounts this file read-only into Docker 1, Docker 4 and Docker 5.

**`drones:`**

| Key | Default | What it does |
|---|---|---|
| `ids` | `[1..6]` | **It must agree exactly with the drones that are enabled in the CrazySwarm `crazyflies.yaml`.** Docker 1 rejects each ID that is not in this list with HTTP 400 |
| `mode` | `crazyswarm` | Which backend to use, if `DRONE_MODE` does not replace it |
| `hover_z` | `1.0` | The takeoff height, **and** the height of each hop. A positive value is up |
| `takeoff_duration` | `2.0` | Docker 1 sends it to the CrazySwarm takeoff. It is also the sleep time of `setup_hover` after the takeoff |
| `land_height`, `land_duration` | `0.04`, `2.0` | The values for the land command |
| `command_settle_seconds` | `0.25` | An extra pause after the takeoff and after the land |
| `group_mask` | `0` | The CrazySwarm broadcast group. `0` means all of the drones |
| `control_timeout` | `300.0` | The HTTP timeout for the upstream calls |
| `vehicle_names` | `1→cf1` … | Maps an ID to a Crazyflie name. The mock and AirSim backends use it |
| `initial_positions` | a grid | **For mock and AirSim only.** The start XYZ and the frame offsets. The crazyswarm mode ignores it |

**`mission:`**

| Key | Default | What it does |
|---|---|---|
| `old_formation` | `[1,2,3,2,1]` | The row widths of the full formation, front row first. **`sum()` must equal `len(drones.ids)`** (§12.1). This is the only place that sets the shape. Refer to §6 for the list of shapes and their limits |
| `formation_spacing` | `0.5` m | The gap between two spots that are next to each other. It controls **both** the gap from side to side and the gap from front to back |
| `poll_interval` | `1.0` s | How frequently the loop looks for a loss |
| `anchor_policy` | `initial_anchor` | Where the formation is in the world (§8) |
| `safety_gap` | `0.25` m | The minimum separation. It applies to the target spots and to each hop |
| `include_downed_in_safety` | `false` | Does a dead drone still occupy space? |
| `waypoint_step` | `0.25` m | The length of each hop |
| `move_velocity` | `0.5` m/s | The speed of each hop |
| `target_tolerance` | `0.05` m | Near enough. Stop here |
| `movement_poll_interval` | `0.1` s | How frequently to read the status while a hop is in the air |
| `command_timeout_margin` | `3.0` s | The extra time that is permitted after the calculated duration of each hop |
| `control_ready_timeout` | `120.0` s | How long to wait for Docker 1 at startup |
| `max_move_seconds_per_drone` | `120.0` s | Stop the full trip of one drone after this time |
| `backward_penalty`, `backward_threshold` | `0.0`, `0.0` | The optional Hungarian penalty. It is off |

Remember this relation: **`safety_gap` (0.25) = `waypoint_step` (0.25) = one half of
`formation_spacing` (0.5)**. Two spots are two safety gaps apart, and one hop is exactly one
safety gap long. If you scale one of these values, scale all of the three.

The margin is smaller than it looks. Look at **each** formation that reforms correctly. In
these formations, the smallest distance between a drone that moves and a drone that is
stationary is **exactly 0.25 m**. This distance is equal to `safety_gap`. The test is `distance
< SAFETY_GAP`. It uses "less than", and not "less than or equal to".

Thus a gap that is exactly `safety_gap` is permitted.

CAUTION: THERE IS NO MARGIN AT ALL. IF YOU INCREASE `safety_gap` ALONE TO 0.3, EACH SHAPE IN
THE CATALOGUE BECOMES STUCK. THIS INCLUDES THE SHAPES THAT FLEW CORRECTLY YESTERDAY. ALWAYS
CHANGE THE TWO VALUES TOGETHER. ALSO REFER TO §6 FOR THE SHAPES THAT BECOME STUCK AT THESE
VALUES.

---

## 12. Traps and unexpected behavior

These are real properties of the code as it is today. Some are bugs. Some are only
unexpected.

### 12.1 `sum(old_formation)` does not agree with `len(drones.ids)`: do this check first

Your files are **correct** now. [config.yaml](../config.yaml) has `ids: [1,2,3]`, which is 3
drones, and `old_formation: [1,2]`, which adds up to 3. Keep them like this. Nothing in the
code does this check, and an error here fails quietly. The alternatives in the comments in the
file are `ids: [1..9]` with `old_formation: [1,2,3,2,1]`, and they also add up correctly. The
trap is to remove the comment mark from one line only.

Here is the result when the values do not agree. The example is the pair that this file had
before: `ids: [1,2,3,4,5,6]`, which is 6 drones, against `old_formation: [1,2,3,2,1]`, which
adds up to **9**.

The formation service calculates `active = sum(old_formation) - downed_drones`. The value
`downed_drones` is a count of the drones that died, and not a count of the spots. Thus with 6
drones and no loss, it gives back **9 spots for 6 drones**. Three spots are always empty. The
loss of a drone makes the formation smaller by one spot. But it does not build the formation
again around the drones that are left.

With 6 drones, you get this result:

| Dead | Spots returned | Living drones | Empty spots |
|---|---|---|---|
| 0 | 9 | 6 | 3 |
| 1 | 8 | 5 | 3 |
| 2 | 7 | 4 | 3 |

Two results occur. Mission puts the formation with the average of all of the 9 spots, thus the
drones go to a position that you did not expect. And the Hungarian solver can select any 6 of
the 9 spots. This includes the spots in the back rows that you did not want.

**Correction:** make `sum(old_formation)` equal to `len(ids)`. Use `[1, 2, 3]` for six drones,
or use `[6]`. Do not use `[2, 3, 1]` or `[3, 2, 1]`. They add up correctly, but they become
stuck during the reformation (§12.10).

If you use `ids: [1..9]` as in
[config.example.yaml](../config.example.yaml), the count is correct. But its `[1,2,3,2,1]` is
one of the shapes that stops. §6 has the full list. The setup steps are in
[QUICKSTART §2.4](QUICKSTART_STE.md#24-configyaml-of-drone_reformation).

### 12.2 The safety check looks at the wrong spots

Step 4 of `_execute_reform` does a check of `target_positions[:len(active_ids)]`, which is the
*first N* spots in row sequence. But the Hungarian solver selects from the *full* list. When
the counts do not agree (§12.1), the spots that the code checked and the spots that the code
uses are different sets. The check for each hop in `_move_drone_safely()` still protects the
flight. Thus this is a weak check before the flight, and not a risk of a crash.

### 12.3 A status race after a move command

`_move_drone_safely()` sends `/move_to_xy_z`, and then it calls `_wait_for_terminal_status()`
immediately. If the upstream did not change to `busy` yet, the first check reads `idle`.
Then mission decides that the hop is complete, and it sends the next hop from an old position.
The symptom is a drone that moves forward much more slowly than the `move_velocity` value.

The `steps` count is much higher than `distance / waypoint_step`. If you see this, add a short
pause after the move command. Or make the upstream set itself to `busy` before it replies.

### 12.4 The system reforms after a loss, but not after a recovery

```python
if downed != _last_downed:
    newly_downed = sorted(downed - _last_downed)
    _last_downed = set(downed)
    if newly_downed:
        _execute_reform(states, downed)
```

If a drone changes from `down` to `idle`, the set changes and the code updates `_last_downed`.
But `newly_downed` is empty. Thus **no reform occurs**, and the formation does not include the
drone that came back. Send `POST /reform_now` by hand. This behavior is correct if you hold a
loss as permanent. It is a gap if your backend can return a drone to service.

### 12.5 `/health` gives incorrect data about mission

§8 gives this problem. The `/health` route of mission always returns `ok`. `startup_all.sh`
waits on `/health`. Thus **the startup script reports a healthy stack also when the mission
worker stopped with an error during the takeoff.** Always send this request after it:

```bash
curl -s http://localhost:8004/status | python3 -m json.tool
```

Then look at `running` and `last_error`.

### 12.6 The one-time flags never reset

`_setup_done`, `_initial_formation_done` and `_initial_anchor_xy` are global values at the
module level, and the code sets them one time. A `POST /stop` and then a `POST /start` will
**not** do the takeoff again, and they will not put the formation again. For a new run, use
`docker compose restart mission`.

### 12.7 The port number is different in different files

There were three different values before: 8000, 8017 and 8017. They now all agree on **8011**.
This number keeps the stack clear of the many services that use 8000 by default:

| Source | `CRAZYSWARM_API_URL` |
|---|---|
| [.env.example](../.env.example), [.env](../.env) and the main README | `http://127.0.0.1:8011` |
| the fallback in [docker-compose.yml](../docker-compose.yml) | `http://127.0.0.1:8011` |
| the default of `drones.crazyswarm_api_url` in [clients.py](../src/drone_control_service/clients.py) | `http://127.0.0.1:8011` |

The bridge has no port setting. The port is the value that you give to `uvicorn --port`. The
system uses the compose fallback only when `.env` does not have the variable. Thus `.env` is
the file that applies. If you start the bridge on a different port, change `.env` to the same
value.

Your `.env` is also set to **`DRONE_MODE=mock`** now. Thus no real drone will move until you
change it to `crazyswarm`. `./scripts/startup_all.sh --crazyswarm` does this for you.

### 12.8 The lock in Docker 1 applies to all of the commands

Each route that changes something waits on one shared lock. `setup_hover`, `land` and `down`
sleep *while they hold it*. Thus a `/down` request that comes during `setup_hover` waits some
seconds, but it does not fail. This is not a problem usually, but it is difficult to
understand when the load is high.

### 12.9 CrazySwarm does not report the speed

Each program that reads `vx`, `vy` or `vz` gets `0.0` in crazyswarm mode, with no message. Use
the `status` field and the changes in the position in place of the speed.

### 12.10 Most formation shapes become stuck during the reformation

This is the largest problem in the stack, and it is not only about single file.

`front_compact` deletes the spot at the back and leaves each other spot in its position. Thus
one drone from the back must travel the full depth of the formation to fill the gap. Each
drone that it passes stays in its position. And `_move_drone_safely()` cannot ask a drone to
move out of the path.

Each `old_formation` with a row width that **repeats or that gets smaller** puts the drones at
the same x position. Thus the trip goes along a line that is already occupied, and the mission
stops. This includes `[1,2,3,2,1]`, `[3,3,3]`, `[3,2,1]`, `[2,4,2]` and `[1,1,1]`.

Two types of shape pass a full test of each possible single loss. These are a single row
(`[N]`), and a wedge that becomes wider at each row (`[1,2]`, `[1,2,3]`, `[2,3,4]`). And these
shapes pass with a gap of *exactly* `safety_gap`, thus they have no margin.

The symptom is that `last_move` shows `status: "timeout"` with a `blocked_count` that
increases. Also, `last_block_reason` gives the name of a drone that the mover tries to fly
through. The full test results, the reason, and three possible corrections are in §6, in
*Why you cannot fly a straight line*.

### 12.11 You cannot set the Hungarian penalty values from the config

`forward_jump_penalty` (`100.0`) and `forward_jump_threshold_multiplier` (`2.0`) are defaults
on `AssignmentRequest`. Refer to
[src/hungarian_service/app.py:21-22](../src/hungarian_service/app.py#L21-L22).
[`_call_hungarian`](../src/mission_service/app.py#L210) never sends them. Thus nothing in
[config.yaml](../config.yaml) or [.env](../.env) can change them. To tune one of them, you
must edit the source.

`backward_penalty` and `backward_threshold` *do* come from `config.yaml`. They are set to
`0.0`, which makes that penalty off.

---

## 13. The best sequence to read the code

1. [src/formation_service/app.py](../src/formation_service/app.py): 74 lines, pure geometry.
2. [src/hungarian_service/app.py](../src/hungarian_service/app.py): 112 lines, pure matching.
3. [src/drone_common/control_client.py](../src/drone_common/control_client.py): the HTTP
   contract that each service uses to get to Docker 1.
4. [src/drone_control_service/app.py](../src/drone_control_service/app.py): the list of routes.
5. [src/drone_control_service/clients.py](../src/drone_control_service/clients.py): start with
   `CrazySwarmApiDroneClient`. Do not read `AirSimDroneClient` the first time.
6. [src/mission_service/app.py](../src/mission_service/app.py): read `_execute_reform` first,
   then `_move_drone_safely`, then `_mission_loop`.
7. [src/downed_simulator_service/app.py](../src/downed_simulator_service/app.py) and
   [src/visualizer_service/viewer.py](../src/visualizer_service/viewer.py): read these last.

---

## 14. How to learn the algorithm with no hardware

The two pure services need no other service:

```bash
# What shape do 6 survivors of a 9-drone wedge make?
curl -s -X POST http://localhost:8003/formation \
  -H 'Content-Type: application/json' \
  -d '{"old_formation":[1,2,3,2,1],"downed_drones":3,"spacing":0.5}' \
  | python3 -m json.tool

# Who should go where?
curl -s -X POST http://localhost:8002/assign \
  -H 'Content-Type: application/json' \
  -d '{
        "active_ids": [1, 2, 3],
        "old_positions": {"1": [0.0, 0.0], "2": [-0.25, -0.5], "3": [0.25, -0.5]},
        "target_positions": [[0.0, 0.0], [-0.25, -0.5], [0.25, -0.5]],
        "spacing": 0.5,
        "cascade_front_first": true
      }' \
  | python3 -m json.tool
```

To run the full pipeline with no drones and no simulator:

```bash
./scripts/startup_all.sh --mock
curl -s -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' -d '{"drone_ids":[2]}'
sleep 5
curl -s http://localhost:8004/last_reform | python3 -m json.tool
curl -s http://localhost:8004/last_move   | python3 -m json.tool
```

The mock mode is also the least expensive method to do a full test of a new `old_formation`.
Down each drone in sequence, and look at `last_move` for `status: "timeout"`. This is the test
that gives the table of shapes in §6. Do this test for each shape that is not in that table.

In mock mode the drones move immediately, because each hop sleeps 50 ms or less. Thus a full
reformation ends in about one second. Each service runs the same code as with real hardware.
The backend adapter of Docker 1 is the only exception.

---

## 15. Checklist for faults

This table is for the stack. For problems with the radio, ROS, the mocap or the bridge, refer
to [QUICKSTART §8](QUICKSTART_STE.md#8-commands-to-find-faults).

| What you see | Where to look |
|---|---|
| No drone takes off | Send `curl localhost:8004/status`, then look at `running` and `last_error`. Then send `curl localhost:8001/health`. `status: degraded` means that Docker 1 cannot get to the backend |
| Docker 1 says `degraded` | Is `CRAZYSWARM_API_URL` on the correct port (§12.7)? Does `curl $CRAZYSWARM_API_URL/health` operate from the **host**? |
| The takeoff operates, but no reform occurs | Send `curl localhost:8004/last_reform`. `no_reform_yet` means that no reform started. Make sure that the dead drone reports `down` at `localhost:8001/drones/{id}/status` |
| The drones move, but they stop too soon | `last_move` with `status: "timeout"` and a high `blocked_count` means that `safety_gap` is too large for `formation_spacing` |
| One drone does not move at all | A `blocked_count` that increases means that another drone is in the `safety_gap`. `steps: 0` with `arrived` means that the drone was already in `target_tolerance` |
| The reformation stops, `blocked_count` increases, one drone has a large `travel_distance` | §12.10 and §6. Does a row width in `old_formation` repeat or get smaller? Change to `[1,2]`, `[1,2,3]` or `[N]` |
| You changed `old_formation`, but the shape is the same | The service reads `OLD_FORMATION` at startup. Use `docker compose restart mission`, and not `/stop` and `/start` (§12.6) |
| The formation is in the incorrect position | `anchor_policy` (§8), and the count of the spots (§12.1) |
| The system selected the incorrect drone for a spot | Look at `last_reform.hungarian.assignment`, at `travel_distance` and `delta_y`. The `forward_jump_penalty` can be active |
| The visualizer is blank, or the dots are off the screen | `VIS_SCALE`. Use 500 px/m for Crazyflies, and about 8 for AirSim distances |
| The visualizer does not open | Run `xhost +local:docker`. Also make sure that `DISPLAY` has a value in the shell that ran the script |
| The restart did not do the takeoff again | §12.6. Use `docker compose restart mission` |

The logs of each service:

```bash
docker compose logs -f mission
docker compose logs -f drone-control
docker compose logs -f downed-simulator
```

Docker 1 runs on the host network. Thus `docker compose ps` shows it with no port mapping.
This is correct, and it is not a fault.
