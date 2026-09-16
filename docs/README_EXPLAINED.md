# README_EXPLAINED — How the Drone Reformation Stack Works

This is a companion to [README.md](README.md). The main README tells you **what to run**.
This one explains **why each piece exists, how data moves between them, what every
setting does, and where the traps are**.

This does not replace the main README. You still start everything with
`./scripts/startup_all.sh`.

---

## 1. The short version

Six containers work together to hold a group of Crazyflie drones in a formation.

When a drone "dies" (it lands and disarms), here is what happens:

1. The system notices the drone is gone.
2. It works out a new, smaller shape for the drones that are left.
3. It decides which surviving drone should move into which spot.
4. It walks each drone to its new spot in small steps, and refuses any step that would
   take it too close to another drone.

Only **one** container is allowed to talk to the drone hardware. Every other container
speaks plain HTTP and knows nothing about ROS 2, CrazySwarm, or AirSim.

---

## 2. Why the design looks like this

The main rule is **backend isolation**:

> Docker 1 (`drone-control`) is the *only* service that talks to a flight backend.
> Everything else is plain HTTP and does not care what the backend is.

You get three things from that rule:

1. **You can swap backends.** `DRONE_MODE` picks between `crazyswarm` (real drones, via
   ROS 2), `mock` (pure Python, no hardware) and `airsim` (older, kept for
   compatibility). The mission, formation, Hungarian, downed-simulator and visualizer
   services run exactly the same code in all three cases.
2. **You can test safely.** Set `DRONE_MODE=mock` and you can run the whole reformation
   algorithm with no drones, no simulator and no ROS.
3. **Commands never overlap.** Docker 1 holds one lock around every command, so two
   services can never send conflicting flight commands at the same time.

The downside: Docker 1 is a bottleneck, and if it dies everything stops. That was a
deliberate trade.

---

## 3. The six containers

| # | Service | Container port | Host port | Keeps state? | Talks to |
|---|---------|---------------|-----------|-----------|----------|
| 1 | `drone-control` | 8001 (host net) | `localhost:8001` | last command only | CrazySwarm API / AirSim / in-memory mock |
| 2 | `hungarian` | 8000 | `localhost:8002` | **no** | nobody (pure function) |
| 3 | `formation` | 8000 | `localhost:8003` | **no** | nobody (pure function) |
| 4 | `mission` | 8000 | `localhost:8004` | **yes — this is the brain** | Docker 1, 2, 3 |
| 5 | `downed-simulator` | 8000 | `localhost:8005` | no | Docker 4 |
| 6 | `visualizer` | — | OpenCV window | no | Docker 1 |

Services 2 and 3 are just functions behind an HTTP endpoint. You can `curl` them with
made-up numbers and they will answer correctly with no drones running. That is the
fastest way to understand the algorithm.

### How the networking works

This part confuses people, so here it is in full
([docker-compose.yml](docker-compose.yml)):

- **Docker 1 uses `network_mode: host`.** It has no `ports:` mapping because it does not
  need one. Uvicorn binds `0.0.0.0:8001` directly on your machine. That is what lets it
  reach the CrazySwarm API at `127.0.0.1:8011` on the host.
- **Docker 2 to 5 sit on the normal compose bridge network.** They find each other by
  service name: `http://formation:8000`, `http://hungarian:8000`, `http://mission:8000`.
- **Docker 4 and 6 reach Docker 1 at `host.docker.internal:8001`.** The
  `extra_hosts: host-gateway` line makes that name work. They cannot use the name
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

Every arrow points the way the **call** goes. Replies travel back up the same arrow, so
they are not drawn. Three things to take from it:

- **Nothing points into mission except you and Docker 5.** Mission is never told
  anything. It pulls what it needs on its own poll loop. That is why a real battery
  failure and a simulated kill go down exactly the same path.
- **The visualizer arrow points up.** Docker 6 calls Docker 1, not the other way round.
  Docker 1 does not know it exists.
- **Only Docker 1 touches the bottom box.** That single arrow is the whole hardware
  boundary.

---

## 4. The status model — the core idea

Every drone, in every backend, is reduced to one of three states:

| Status | What it means | Who sets it |
|--------|---------|--------|
| `idle` | No move command is running. The drone is holding its last position | upstream |
| `busy` | The move command is still running | upstream |
| `down` | The drone has landed or is marked lost | upstream, or `/down` |

This is the agreement that makes the rest of the system simple. Mission never looks at
altitude, speed, or AirSim's `landed_state`. It asks for one status word.

`CrazySwarmApiDroneClient._normalize_status_item()` in
[drone_control_service/clients.py:131](drone_control_service/clients.py#L131) is where
the upstream data is converted into this shape. It:

- turns any status it does not recognise into `idle`. This is safe, but it also means a
  typo upstream will be hidden rather than reported;
- works out `armed`, `landed` and `downed` from whether `status == "down"`;
- flattens `position: {x,y,z}` into plain `x`, `y`, `z` fields;
- always reports `vx/vy/vz` as `0.0`. **The CrazySwarm backend does not report speed at
  all.** Only the mock and AirSim backends fill these in.

Every backend produces this same dictionary, so nothing further up the stack can tell
them apart.

---

## 5. Docker 1 — the gateway

[drone_control_service/app.py](drone_control_service/app.py) is a thin FastAPI wrapper.
The real work happens in
[drone_control_service/clients.py](drone_control_service/clients.py).

### Routes

| Route | What it does |
|-------|---------|
| `GET /health` | Can it reach the backend? Returns `degraded` with a 200, not a 5xx, when the backend is down |
| `GET /status` | The last command sent through this gateway |
| `GET /states` | A `{drone_id: state}` map for every configured drone |
| `GET /states_vis` | The same as `/states`. It exists only so the visualizer has a stable name to call |
| `GET /drones/status` | The same data as a list: `{count, drones:[...]}` |
| `GET /drones/{id}/status` | One drone |
| `POST /setup_hover` | arm → sleep 2s → take off → sleep |
| `POST /hover` | **Does nothing on CrazySwarm** (see below) |
| `POST /move_to_xy_z` | Go to an absolute position |
| `POST /land` | Land, and optionally disarm |
| `POST /down` | Another name for land. This is how a drone is "killed" |
| `POST /shutdown` | Land, disarm and release everything |

The order the routes are declared in matters. `/drones/status` is registered **before**
`/drones/{drone_id}/status` at
[app.py:146](drone_control_service/app.py#L146). Otherwise FastAPI would try to read the
word `"status"` as a drone ID number and fail.

### The command wrapper

Every route that changes something goes through `_run()`
([app.py:91](drone_control_service/app.py#L91)):

```python
with _LOCK:                       # one lock for the whole process — commands run one at a time
    result = fn()
    return _record(command, "accepted", drone_ids, result=result)
```

If the backend raises an error, you get **HTTP 502**, and the failure is saved in
`_LAST_COMMAND` so `GET /status` can show you what went wrong. An unknown drone ID gets
**HTTP 400** before the backend is called at all.

### `/move_to_xy_z` becomes CrazySwarm's `/go-to`

Docker 1 keeps the old route name but rewrites the body
([clients.py:235](drone_control_service/clients.py#L235)):

```
POST /move_to_xy_z {drone_id, x, y, z, velocity}
   ↓
POST {CRAZYSWARM_API_URL}/drones/{id}/go-to
     {x, y, z, yaw: 0.0, velocity, relative: false, group_mask}
```

It **returns straight away**. It does not wait for the drone to arrive. Waiting is
Mission's job, and Mission does it by polling the status. (The mock backend is the
exception: it pauses briefly, then teleports the drone to the target.)

### `/setup_hover` is slow on purpose

```python
for id in ids: POST /drones/{id}/arm  {"arm": true}
time.sleep(2.0)                                  # <- the "added sleep after arm" commit
for id in ids: POST /drones/{id}/takeoff {target_height: hover_z, duration, group_mask}
time.sleep(takeoff_duration + command_settle_seconds)
```

That fixed 2-second sleep is there because the Crazyflie firmware needs a gap between
arming and taking off. You **cannot** change it from config, and it is held **inside the
global lock**. So `setup_hover` blocks every other Docker 1 command for about
`2.0 + takeoff_duration + command_settle_seconds`, which is roughly 4.25 seconds with the
default settings. `land` and `down` hold the lock in the same way for
`land_duration + command_settle_seconds`.

### `/hover` does nothing on CrazySwarm

The CrazySwarm HTTP API has no hover endpoint. Its high-level commands already hold their
final position on their own. So `hover()` returns
`{"status": "accepted", "command": "hold_current_setpoint", ...}` **without sending
anything at all**. Do not use it to stop a moving drone.

### The three backends

| | `crazyswarm` | `mock` | `airsim` |
|---|---|---|---|
| Chosen by | `DRONE_MODE=crazyswarm\|crazyflie\|ros2` | `DRONE_MODE=mock` | `DRONE_MODE=airsim\|colosseum` |
| Where positions come from | upstream `/drones/status` | a dictionary in memory | `getMultirotorState()` |
| Which way is up | **+Z is up** from the floor | +Z is up | **NED, so −Z is up** (old `hover_z: -20.0`) |
| How `busy` is tracked | upstream `remaining_seconds` | set and cleared inside `move_to_xy_z` | a local `_busy_until` timer |
| Speed reported | always 0 | calculated | real |
| How moves behave | fire and forget | sleeps 50 ms or less, then teleports | runs in the background, tracked by a timer |
| Auth | sends `X-API-Key` if `CRAZYSWARM_API_KEY` is set | — | — |

`make_drone_client()` at [clients.py:653](drone_control_service/clients.py#L653) picks
the backend. The `DRONE_MODE` environment variable beats `drones.mode` in config.yaml.

The AirSim path also shifts coordinates using `drones.initial_positions`. It adds each
drone's own origin to the positions it reports, and subtracts it from the positions you
command, because every AirSim vehicle reports relative to where it spawned. CrazySwarm
reports in one shared world frame, so no shift is applied there. That is why
`initial_positions` only matters in `mock` and `airsim` modes.

---
## 6. Docker 3 — formation (the geometry)

[formation_service/app.py](formation_service/app.py). About 74 lines. It keeps no state
and calls nothing else.

**You give it:** the "old formation" as a list of row widths, how many drones are down,
and a spacing.
**It gives you back:** the row widths for the new smaller shape, plus the XY position of
every spot.

### `compact_rows()`

```
total  = sum(old_formation)
active = total - downed_drones
```

Then it fills rows from the front, and never lets a row grow past its original width:

```
old_formation = [1, 2, 3, 2, 1]   (9 drones)

downed = 0 → [1, 2, 3, 2, 1]   (9 spots)
downed = 1 → [1, 2, 3, 2]      (8 spots)
downed = 3 → [1, 2, 3]         (6 spots)
downed = 6 → [1, 2]            (3 spots)
```

The formation always loses depth from the **back**. It never gets narrower at the front.
This is the `front_compact` policy, and it is the only one that exists. Any other
`policy` value returns HTTP 400.

### `make_slots()` — how the coordinates are laid out

The Hungarian service depends on this layout, so it is worth learning:

```
row 0 (front)  y =  0.0            •              ← bigger y = FRONT
row 1          y = -spacing      •   •
row 2          y = -2*spacing  •   •   •
row 3          y = -3*spacing    •   •            ← smaller y = BACK
row 4          y = -4*spacing      •
```

Every row is centred on `x = 0`. For a row of `n` spots, x starts at
`-0.5 * spacing * (n-1)` and goes up in steps of `spacing`. A row with one spot sits at
`x = 0.0`.

These numbers are **relative**. The origin is the centre of the front row. Mission is
what places them in the real world (§8).

### How the code says what shape it wants

There is exactly **one** place in the whole system where the shape is set:
`mission.old_formation` in [config.yaml](config.yaml#L48). It is a list of **row widths,
front row first**. Nothing else in the system knows or cares what shape the drones are
in.

Here is the full path the setting takes:

```
config.yaml   mission.old_formation: [1, 2]
      │
      ▼   read once when the service starts
mission_service/app.py:25       OLD_FORMATION = [1, 2]
      │
      ▼   _call_formation() → POST http://formation:8000/formation
formation_service/app.py:19     compact_rows([1,2], downed) → [1, 1]
formation_service/app.py:39     make_slots([1,1], 0.5)      → [[0,0], [0,-0.5]]
      │
      ▼   slots_relative (measured from the centre of the front row)
mission_service/app.py:135      _formation_world_targets() places them in the world
      │
      ▼   real-world XY targets
hungarian_service/app.py:34     works out which drone takes which target
      │
      ▼   sorted by cascade_rank
mission_service/app.py:250      _move_drone_safely(), one drone at a time
```

Read that list backwards and the design becomes clear. The Hungarian solver and the
mover **know nothing about shapes**. They are handed a list of XY targets and never find
out those targets were supposed to be a wedge. All the shape knowledge lives in the seven
lines of [make_slots()](formation_service/app.py#L39).

So `old_formation` is a tiny language of its own:

| You write | You get | Reforms safely? |
|---|---|---|
| `[1, 2]` | 3-drone wedge: one leader in front, two behind | ✅ |
| `[1, 2, 3]` | 6-drone solid wedge | ✅ |
| `[1, 2, 3, 4]` | 10-drone solid wedge | ✅ |
| `[4]` | 4 drones side by side in one row | ✅ |
| `[1, 2, 3, 2, 1]` | 9-drone diamond | ❌ hangs if drone 4 or 6 dies |
| `[3, 3, 3]` | 3×3 square grid | ❌ hangs on 3 of the 9 |
| `[3, 2, 1]` | upside-down wedge: wide at the front, one at the back | ❌ |
| `[2, 4, 2]` | hexagon shape | ❌ |
| `[1, 1, 1, 1]` | 4 drones in single file | ❌ always |

That last column is not a small detail. **Most shapes in this list get stuck during
reformation**, including the diamond used in every other example in this file. The test
results and the reason are below, under *Why you cannot fly a straight line*.

### How to change the formation

1. Edit `mission.old_formation` in [config.yaml](config.yaml#L48).
2. Make sure `sum(old_formation)` equals `len(drones.ids)`. Nothing checks this for you,
   and getting it wrong fails quietly. See §12.1.
3. Change `mission.formation_spacing` if you want. One number sets **both** the gap
   between drones in a row and the gap between rows.
4. Run `docker compose restart mission`. A `POST /stop` followed by `/start` is not
   enough, because `OLD_FORMATION` is read when the service starts and the one-time flags
   are never reset (§12.6).

You can check the geometry before flying anything, because Docker 3 keeps no state:

```bash
curl -s -X POST http://localhost:8003/formation \
  -H 'Content-Type: application/json' \
  -d '{"old_formation":[3,3,3],"downed_drones":2,"spacing":0.5}' \
  | python3 -m json.tool
```

Look at `new_formation` (the new row widths) and `slots_relative` (where the spots are).

### What this cannot do

`make_slots()` has four rules built into it, and you cannot change any of them from
config:

| Built-in rule | What it costs you |
|---|---|
| Row `r` sits at `y = -r * spacing` | Rows are always evenly spaced. You cannot make some rows closer than others |
| Every row is centred on `x = 0` | No lopsided, offset or diagonal shapes |
| One `spacing` number controls both directions | You cannot make a wide, shallow formation. The side-to-side gap and the front-to-back gap are always equal |
| The front is always `+y` | The formation has **no heading**. You cannot rotate it, and it will not turn to face the way it is travelling |

So without editing [formation_service/app.py](formation_service/app.py) you cannot have:
diagonal lines, circles, arcs, stepped (echelon) shapes, a grid with a hole in it, any
rotation, or hand-written per-drone coordinates. The API accepts row counts only. There
is no way to pass it a list of positions.

Shrinking is just as fixed. `policy` is checked at
[app.py:60](formation_service/app.py#L60), and `front_compact` is the only value that is
not an HTTP 400. Losses always come off the **back**. The shape never gets wider,
narrower, or re-proportioned.

### Why you cannot fly a straight line

Two different shapes get called "a straight line". They behave completely differently.

**Drones side by side — `[N]` — works.** When one dies the survivors re-centre and slide
inwards along the row. Tested against every possible single loss for `[3]`, `[4]`, `[5]`
and `[9]`: none of them fail.

**Drones in single file — `[1, 1, 1, ...]` — always gets stuck.** And it turns out single
file is not a special case. It is the worst example of a problem that affects **most**
shapes here, including the 9-drone diamond this README opens with.

#### What actually goes wrong

`front_compact` never rearranges the formation. It deletes the **last** spot and leaves
every other spot exactly where it was. So after a death:

- Every survivor who is already standing on a spot that still exists has nothing to do.
  Its travel distance is zero.
- Exactly one drone — whichever was standing on the spot that just got deleted — has to
  fill the gap left by the drone that died.
- The Hungarian solver picks the option with the smallest **total** distance. "One drone
  makes the whole trip" is cheaper than "everyone shuffles up one place", so that is what
  it picks. This is correct behaviour for the solver.

The result is that a single drone from the back makes **one long trip straight through
the middle of the formation**, while every drone it passes stays exactly where it is.

`_move_drone_safely()` flies that trip as a straight line, and it **cannot ask anyone to
move out of the way**. When the next step would be unsafe, the only thing it can do is
`time.sleep(...)` and check again
([app.py:288-292](mission_service/app.py#L288-L292)). But the drone in the way has
already arrived and its turn is over, so it will never move. The waiting continues until
`max_move_seconds_per_drone` (120 seconds) runs out, and the result comes back as
`status: "timeout"`.

So whether reformation works comes down to one question: **does that one straight trip
happen to fit between two occupied spots with at least `safety_gap` of room?**

For single file the answer is always no. The trip runs exactly along the line of the
drone in front, so the gap is `0.000`. Notice what that means: **making
`formation_spacing` bigger does not help single file at all.** The blocking drone sits on
the path no matter how far apart you spread them.

```
[1,1,1], drone 1 dies → new rows [1,1] → spots (0,0) and (0,-0.5)

  drone 2 (0,-0.5) → (0,-0.5)   travels 0.0  — stays put
  drone 3 (0,-1.0) → (0, 0.0)   travels 1.0  — has to fly through drone 2

  drone 3 creeps forward to (0,-0.75), then stops there forever
```

#### Which shapes actually work

Here is a full test. Every shape, every possible single drone loss, run against the real
`compact_rows`, `make_slots` and Hungarian cost code with `spacing: 0.5` and
`safety_gap: 0.25`:

| `old_formation` | Drones | Gets stuck if these die | Smallest gap during the trip |
|---|---|---|---|
| `[1, 2]` ← **what you have now** | 3 | never | 0.250 |
| `[3]`, `[4]`, `[5]`, `[9]` | any | never | 0.250 |
| `[1, 2, 3]` | 6 | never | 0.250 |
| `[1, 3]`, `[2, 4]`, `[2, 3, 4]`, `[1, 2, 3, 4]` | — | never | 0.250 |
| `[1, 2, 4]` | 7 | drone 1 | — |
| `[1, 2, 2]` | 5 | drone 1 | 0.122 |
| `[1, 2, 3, 2, 1]` ← the classic diamond | 9 | drones 4 and 6 | 0.059 |
| `[3, 2, 1]` | 6 | drones 1 and 3 | 0.059 |
| `[2, 4, 2]` | 8 | drones 1 and 2 | 0.000 |
| `[3, 3, 3]` | 9 | drones 1, 2 and 3 | 0.000 |
| `[1, 1, 1]` | 3 | drone 1 | 0.000 |

Look down the last column. **Every shape that works has a gap of exactly 0.250, which is
the same as `safety_gap`.** The check is `distance < SAFETY_GAP`
([app.py:191](mission_service/app.py#L191)). It uses "less than", not "less than or
equal", so a gap of exactly `safety_gap` is allowed and the drone squeezes past. There is
**no room to spare at all**. If you raise `safety_gap` to 0.3 without also raising
`formation_spacing`, every shape in that table gets stuck, including the ones that work
today.

The simple rule from those results:

> **Safe:** one row of drones (`[N]`), or a wedge that gets wider every row
> (`[1,2]`, `[1,2,3]`, `[2,3,4]`, `[1,2,3,4]`). Nothing sits directly behind anything
> else, so the trip through the middle passes through the half-spacing gap between rows.
>
> **Gets stuck:** any shape where a row width **repeats or gets smaller**. Rows of the
> same width put drones at the same x, so the trip runs straight down a line that is
> already occupied.

This is why the diamond `[1, 2, 3, 2, 1]` is not safe, even though it appears in
[config.example.yaml](config.example.yaml) and in every diagram in this file. Its front
half widens correctly, but the `3, 2, 1` at the back stacks drones directly behind each
other, and losing drone 4 or drone 6 hangs the mission.

#### If you really need single file

- **Try not to.** `[1, 2]` and `[1, 2, 3]` both work with no code changes.
- **Fix the assignment.** There is already a penalty designed to stop a drone jumping
  this far. Its limit is `forward_jump_threshold_multiplier * spacing`, which is
  `2.0 * 0.5 = 1.0`, and the test is `forward_delta > forward_jump_threshold`
  ([app.py:70](hungarian_service/app.py#L70)). A one-row jump moves the drone forward by
  exactly `1.0`, and `1.0 > 1.0` is false, so the penalty never fires. It misses by the
  smallest possible margin. Changing the multiplier to `1.5` makes the penalty fire and
  the solver then picks the correct "everyone shuffles up" plan. Tested and confirmed.
  But Mission never sends either of these fields
  ([`_call_hungarian`](mission_service/app.py#L210)), so this needs a code change. See
  §12.11.
- **Let drones give way.** Change the mover so a blocked drone can make the drone in
  front step aside, or move several drones at once instead of strictly one at a time.
  This is the proper fix, and by far the biggest one.

---

## 7. Docker 2 — Hungarian assignment (the matching)

[hungarian_service/app.py](hungarian_service/app.py). Also keeps no state. You give it
where the drones **are** and where the spots **are**, and it decides who goes where for
the lowest total cost, using `scipy.optimize.linear_sum_assignment`.

("Hungarian" is just the name of the classic algorithm for this kind of matching
problem.)

### The cost matrix

It starts with plain straight-line distance:

```python
cost[i][j] = ||current_position[i] - target_position[j]||
```

Then it adds two penalties on top.

**1. Forward-jump penalty (always on).** Because the front has the bigger y value, a
drone "moves forward" when `target_y > current_y`. If it would move forward by more than
`forward_jump_threshold_multiplier * spacing` (by default `2.0 * spacing`), the cost goes
up by `forward_jump_penalty` (by default `100.0`).

The point is to stop a drone at the back from jumping all the way to the front when a
front drone dies. Instead, the drone just behind the gap should step up, the one behind
it should take that spot, and so on. That chain is what the code calls a **cascade**.

**2. Backward penalty (off by default).** If `backward_penalty > 0`, any spot with
`target_y < current_y - backward_threshold` gets that penalty added. Both values are
`0.0` in [config.yaml](config.yaml), so this is **switched off**.

Both of these just add to the cost. They are not hard rules. A penalised choice can still
win if every other option is worse by more than `100.0`. Think of them as strong hints,
not bans.

### Cascade ordering

Once the matching is solved, if `cascade_front_first` is true (Mission always sends
`true`), the results are sorted by **current y, biggest first** — so front drones come
first. Each entry then gets a `cascade_rank` starting at 1.

Mission moves the drones **in that order, strictly one at a time**. The idea is that
reformation should look like a wave rolling forward rather than a scramble: the front
drone leaves its spot before the drone behind tries to take it.

**In practice this cascade almost never happens.** Because `front_compact` deletes the
*last* spot and leaves every other spot alone (§6), every survivor already on a surviving
spot has a travel distance of zero. The cheapest total distance is then "one drone from
the back flies the whole way", not a chain of short hops. The ordering makes no
difference when only one drone is moving. This is the root cause of the problem described
in §6 and §12.10. If you look at `last_reform.hungarian.assignment` on a real run, you
will usually see just one non-zero `travel_distance`.

Each entry contains `drone_id`, `slot_idx`, `current_position`, `target_position`,
`travel_distance`, `delta_y` and `cascade_rank`.

---
## 8. Docker 4 — mission (the brain)

[mission_service/app.py](mission_service/app.py). This is the only service that keeps
state, the only one that uses threads, and by far the most complicated. Read this section
twice.

### What happens, in order

When the service starts, if `MISSION_AUTO_START=1` (the default), `_start_worker()`
starts a background thread running `_mission_loop()`:

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

`_wait_for_control_ready()` is stricter than a normal health check. It needs
`status == "ok"` **and** the nested `backend.upstream.ready` field must not be exactly
`False`. If the `ready` key is missing that is fine. Only an explicit `false` blocks it.

### `_execute_reform()` — the six steps

This is the main routine ([app.py:329](mission_service/app.py#L329)):

1. **Find the living drones.** `_active_ids_from_states()` narrows `DRONE_IDS` down to
   the ones that appear in `/states` and are not `down`. If none are left it records
   `no_active_drones` and stops.
2. **Ask Docker 3 for the new shape**, sending `len(downed)` as `downed_drones`.
3. **Convert the relative spots into real-world coordinates**
   (`_formation_world_targets()`).
4. **Safety-check the new shape.** Every pair among the first `len(active_ids)` targets
   must be at least `safety_gap` apart, or it raises a `RuntimeError`.
5. **Ask Docker 2 who goes where**, then sort by `cascade_rank`.
6. **Move the drones one at a time**, in that order, using `_move_drone_safely()`.

Steps 1 to 5 are saved in `_last_reform` and step 6 in `_last_move`. You can read them at
`GET /last_reform` and `GET /last_move`. `_last_reform` is written **before** any drone
moves, so even if a move fails you still get to see the plan.

### Placing the formation — `mission.anchor_policy`

The formation service returns coordinates measured from the centre of the front row.
Mission has to decide where in the real world that centre should be. There are three
options ([app.py:135](mission_service/app.py#L135)):

| Policy | Where the centre goes | What that means |
|---|---|---|
| `active_centroid` | `mean(living drone positions) − mean(all spots)` | Worked out fresh every time. The formation drifts to wherever the drones currently are |
| `initial_anchor` | Same sum, but **saved the first time and reused** | The formation stays where the drones started. **This is the default in your config** |
| `origin` | `[0, 0]` | The formation is pinned to the world origin |

`initial_anchor` saves its answer in the global `_initial_anchor_xy`, which is only ever
cleared by restarting the container. Any other value raises a `RuntimeError`.

Note that the average is taken over **all** the spots returned, not just the ones that
will actually be used. That matters for the trap in §12.1.

### `_move_drone_safely()` — walking a drone to its spot

Mission never sends a drone straight to its target. It walks it there in small hops
([app.py:250](mission_service/app.py#L250)):

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

Four things worth knowing:

- **Height never changes.** Every hop is commanded at `drones.hover_z`. The whole
  reformation happens in 2-D. Altitude is a constant.
- **Safety is checked one hop at a time, not for the whole route.** The check asks: is
  the end of this *next* 0.25 m hop clear right now? Because only one drone moves at a
  time, everything else is stationary, so this snapshot is good enough in practice.
- **Being blocked is a wait, not a failure.** A blocked drone looks again and retries
  forever, until `MAX_MOVE_SECONDS_PER_DRONE` runs out and it returns `"timeout"`. Two
  drones can never block each other here, because they move one at a time. But a moving
  drone *can* be blocked forever by a stationary one — that is exactly the problem in §6.
- **`include_downed_in_safety`** (default `false`) decides whether a crashed drone still
  takes up space. `false` means survivors will happily fly straight over it.

Each entry in `move_results` has a `status` of `arrived`, `aborted_down` or `timeout`,
plus `steps`, `blocked_count` and timing.

### `_wait_for_terminal_status()`

Polls `GET /drones/{id}/status` every `movement_poll_interval` until the status is `idle`
or `down`, and raises `TimeoutError` if the deadline passes. This is the **only** thing
that keeps hops in order. There is no completion callback anywhere in the system.

### Mission's HTTP routes

| Route | What it does |
|---|---|
| `GET /health` | Only says the service is alive. Always returns `ok`, and tells you nothing about the worker |
| `GET /status` | `running`, `setup_done`, `initial_formation_done`, `last_downed`, `last_error`, and the URLs it resolved |
| `POST /start` | Start the worker (`{"setup_hover": true}`). Returns `already_running` if it is already going |
| `POST /stop` | Sets the stop flag. The loop exits after it finishes the current pass |
| `POST /simulate_downed` | Checks the IDs, then calls Docker 1 `/down`. **Does not reform.** The poll loop notices on its next pass |
| `POST /reform_now` | Force a reform immediately, using the current state |
| `GET /last_reform` | The last plan: shape, assignment, and world targets |
| `GET /last_move` | The last movement report |
| `POST /shutdown` | Stop the loop, then land and disarm everything through Docker 1 |

**A crashed worker does not show up in `/health`.** If `_mission_loop()` throws, the
error is stored in `_last_error`, `_running` flips to `false`, and the thread dies
quietly. Meanwhile `/health` keeps replying `{"status": "ok"}`. Always check
`GET /status` for `running` and `last_error`. Never trust `/health`.

---

## 9. Docker 5 — downed simulator

[downed_simulator_service/app.py](downed_simulator_service/app.py). The smallest service.
Its only job is to choose drone IDs and pass them to Mission.

```
POST /down {"drone_ids": [2]}       → kill drone 2
POST /down {"count": 2}             → pick two of the configured IDs at random
POST /land {...}                    → same thing as /down
```

The important design point, and the reason this service was rewritten: it calls
**Docker 4**, not Docker 1.

```
Docker 5 → POST /simulate_downed → Docker 4 → POST /down → Docker 1 → land + disarm
```

Going through Mission keeps one clear chain of command over the drones. Mission still
finds out about the death through its own status poll, not through the call itself. So a
drone that dies for real — flat battery, crash, lost radio — goes through exactly the
same code as a simulated one. The simulator gets no special treatment.

### Killing drones automatically at startup

Set these in `.env`:

```bash
AUTO_DOWN_IDS=2,5        # or AUTO_DOWN_COUNT=2 to pick at random
AUTO_DOWN_AFTER_SEC=45   # how long to wait first
```

If either `AUTO_DOWN_IDS` or `AUTO_DOWN_COUNT` is set, a background thread sleeps and
then fires once. `AUTO_DOWN_IDS` wins if both are set. Errors are printed rather than
raised, so check `docker compose logs downed-simulator`.

`AUTO_DOWN_AFTER_SEC` is counted from when *this container* starts, which is well before
Mission has finished taking off and forming up. Give it plenty of time, or you will kill
a drone in the middle of takeoff.

---

## 10. Docker 6 — visualizer

[visualizer_service/viewer.py](visualizer_service/viewer.py). An OpenCV window that polls
`GET /states_vis` at `VIS_FPS` times per second.

- Green filled dot = alive. Red X = dead. Faint circle = the `safety_gap` radius.
- World to pixels: `px = width/2 + x*scale`, `py = height/2 − y*scale`. Y is flipped, so
  **the front of the formation (bigger y) is drawn towards the top of the window**.
- `VIS_SCALE=500.0` means 500 pixels per metre, which suits Crazyflie distances
  (0.5 m spacing becomes 250 pixels). The default of `8.0` in the code is left over from
  the AirSim days. Compose always overrides it.
- If anything goes wrong it draws the error text into the frame instead of crashing. A
  window full of red error text means the visualizer is working and Docker 1 is not.
- Set `VIS_HEADLESS_OUTPUT=/app/artefacts/frame.png` to write PNG files instead of
  opening a window. This is useful over SSH. The [artefacts/](artefacts/) directory is
  mounted for exactly this.

It sits behind the `visualizer` compose profile, so it only starts with
`--with-visualizer`. It also needs `xhost +local:docker` and a working `DISPLAY`.

---
## 11. Every setting explained

There are two files. Environment variables always beat YAML where both set the same
thing.

### `.env` — how things are wired together

| Variable | What it does |
|---|---|
| `DRONE_MODE` | `crazyswarm` / `mock` / `airsim`. Beats `drones.mode` |
| `CRAZYSWARM_API_URL` | Where the upstream API lives. Beats `drones.crazyswarm_api_url` |
| `CRAZYSWARM_API_KEY` | If set, sent as an `X-API-Key` header on every upstream request |
| `MISSION_AUTO_START` | `1` means the mission starts flying as soon as the container boots |
| `AUTO_DOWN_IDS` / `AUTO_DOWN_COUNT` / `AUTO_DOWN_AFTER_SEC` | Kill drones automatically for testing |
| `VIS_*`, `SAFETY_GAP`, `DISPLAY` | Visualizer only |

### `config.yaml` — mounted read-only into Docker 1, 4 and 5

**`drones:`**

| Key | Default | What it does |
|---|---|---|
| `ids` | `[1..6]` | **Must exactly match the drones enabled in CrazySwarm's `crazyflies.yaml`.** Any ID not in this list is rejected with HTTP 400 |
| `mode` | `crazyswarm` | Which backend to use, unless `DRONE_MODE` overrides it |
| `hover_z` | `1.0` | Takeoff height, **and** the height of every single hop. Positive is up |
| `takeoff_duration` | `2.0` | Sent to CrazySwarm takeoff, and also how long `setup_hover` sleeps afterwards |
| `land_height` / `land_duration` | `0.04` / `2.0` | Landing settings |
| `command_settle_seconds` | `0.25` | Extra pause after takeoff and landing |
| `group_mask` | `0` | CrazySwarm broadcast group. `0` means all |
| `control_timeout` | `300.0` | HTTP timeout for upstream calls |
| `vehicle_names` | `1→cf1` … | Maps ID to Crazyflie name. Used by mock and AirSim |
| `initial_positions` | a grid | **Mock and AirSim only.** Starting XYZ and frame offsets. Ignored in crazyswarm mode |

**`mission:`**

| Key | Default | What it does |
|---|---|---|
| `old_formation` | `[1,2,3,2,1]` | The row widths of the full formation, front row first. **`sum()` should equal `len(drones.ids)`** (§12.1). This is the only place the shape is set. See §6 for the list of shapes and their limits |
| `formation_spacing` | `0.5` m | The gap between neighbouring spots. Controls **both** the side-to-side gap and the front-to-back gap |
| `poll_interval` | `1.0` s | How often the loop checks for deaths |
| `anchor_policy` | `initial_anchor` | Where the formation sits in the world (§8) |
| `safety_gap` | `0.25` m | Minimum separation. Enforced on both the target spots and every hop |
| `include_downed_in_safety` | `false` | Do dead drones still take up space? |
| `waypoint_step` | `0.25` m | How far each hop moves |
| `move_velocity` | `0.5` m/s | How fast each hop flies |
| `target_tolerance` | `0.05` m | Close enough. Stop here |
| `movement_poll_interval` | `0.1` s | How often to check status while a hop is in the air |
| `command_timeout_margin` | `3.0` s | Extra time allowed on top of each hop's expected duration |
| `control_ready_timeout` | `120.0` s | How long to wait for Docker 1 at startup |
| `max_move_seconds_per_drone` | `120.0` s | Give up on one drone's whole journey after this long |
| `backward_penalty` / `backward_threshold` | `0.0` / `0.0` | Optional Hungarian penalty. Switched off |

The relationship worth remembering: **`safety_gap` (0.25) = `waypoint_step` (0.25) =
half of `formation_spacing` (0.5)**. Spots are two safety-gaps apart, and one hop is
exactly one safety-gap long. If you scale one of these, scale all three.

This is tighter than it looks. In **every** formation that reforms successfully, the
closest a moving drone gets to a stationary one is **exactly 0.25 m** — the same as
`safety_gap`. The test is `distance < SAFETY_GAP`, which uses "less than" rather than
"less than or equal", so a gap of exactly `safety_gap` is allowed. There is literally no
room to spare. Raising `safety_gap` on its own to 0.3 will jam every shape in the
catalogue, including ones that flew fine yesterday. Always change the pair together. And
see §6 for the shapes that get stuck even at these values.

---

## 12. Traps and surprises

These are all real properties of the code as it stands today. Some are bugs. Some are
just surprising.

### 12.1 `sum(old_formation)` not matching `len(drones.ids)` — check this first

Your files are currently **correct**: [config.yaml](config.yaml) has `ids: [1,2,3]`
(3 drones) and `old_formation: [1,2]` (which adds up to 3). Keep it that way. Nothing in
the code checks this, and getting it wrong fails silently instead of loudly. The
commented-out alternatives in the file (`ids: [1..9]` with `old_formation: [1,2,3,2,1]`)
also add up correctly. The trap is uncommenting one line without the other.

Here is what goes wrong when they do not match, using the pairing this file used to ship
with: `ids: [1,2,3,4,5,6]` (6 drones) against `old_formation: [1,2,3,2,1]` (which adds up
to **9**).

The formation service calculates `active = sum(old_formation) - downed_drones`, where
`downed_drones` is a count of drones that have *actually* died, not a count of spots. So
with 6 drones and none dead, it hands back **9 spots for 6 drones**. Three spots are
always empty, and losing a drone shrinks the formation by one spot instead of rebuilding
it around the survivors.

With 6 drones, that gives you:

| Dead | Spots returned | Living drones | Empty spots |
|---|---|---|---|
| 0 | 9 | 6 | 3 |
| 1 | 8 | 5 | 3 |
| 2 | 7 | 4 | 3 |

Two things follow. The formation is placed using the average of all 9 spots, so the
drones end up sitting somewhere you did not expect. And the Hungarian solver is free to
pick any 6 of the 9 spots, including back-row ones you never meant to fill.

**Fix:** make `sum(old_formation)` equal `len(ids)`. Use `[1, 2, 3]` for six drones, or
`[6]`. Avoid `[2, 3, 1]` and `[3, 2, 1]`: they add up correctly but get stuck during
reformation (§12.10). Restoring `ids: [1..9]` as in
[config.example.yaml](config.example.yaml) fixes the count, but its `[1,2,3,2,1]` is one
of the shapes that hangs. §6 has the full list.

### 12.2 The safety check does not check the spots that actually get used

Step 4 of `_execute_reform` checks `target_positions[:len(active_ids)]`, which is the
*first N* spots in row order. But the Hungarian solver picks from the *whole* list. When
the counts do not match (12.1), the spots that were checked and the spots that get used
are different sets. The per-hop check inside `_move_drone_safely()` still protects the
actual flight, so this is a weakened pre-flight check rather than a crash risk.

### 12.3 A status race right after a move command

`_move_drone_safely()` sends `/move_to_xy_z` and then immediately calls
`_wait_for_terminal_status()`. If the upstream has not switched to `busy` yet, the first
check reads `idle`, Mission decides the hop is finished, and sends the next hop based on
a stale position. The symptom is a drone that creeps forward far more slowly than
`move_velocity` should allow, with a `steps` count much higher than
`distance / waypoint_step`. If you see that, add a short pause after the move command, or
make the upstream mark itself `busy` before replying.

### 12.4 Reforming happens on death, never on recovery

```python
if downed != _last_downed:
    newly_downed = sorted(downed - _last_downed)
    _last_downed = set(downed)
    if newly_downed:
        _execute_reform(states, downed)
```

If a drone goes from `down` back to `idle`, the set changes and `_last_downed` is
updated, but `newly_downed` is empty, so **no reform happens** and the recovered drone is
left out of the formation. Call `POST /reform_now` by hand. This is deliberate if you
assume death is permanent. It is a gap if your backend can bring drones back.

### 12.5 `/health` lies about Mission

Covered in §8. Mission's `/health` always returns `ok`. `startup_all.sh` waits on
`/health`, so **the startup script will report a healthy stack even when the mission
worker crashed during takeoff.** Always follow up with:

```bash
curl -s http://localhost:8004/status | python3 -m json.tool
```

and look at `running` and `last_error`.

### 12.6 One-time flags never reset

`_setup_done`, `_initial_formation_done` and `_initial_anchor_xy` are module-level
globals that are set once. `POST /stop` followed by `POST /start` will **not** redo the
takeoff or re-place the formation. For a genuinely fresh run use
`docker compose restart mission`.

### 12.7 The port number disagrees between files

This used to be three different values (8000, 8017 and 8017). They now all agree on
**8011**, chosen to stay clear of the many services that default to 8000:

| Source | `CRAZYSWARM_API_URL` |
|---|---|
| [.env.example](../.env.example), [.env](../.env) and the main README | `http://127.0.0.1:8011` |
| [docker-compose.yml](../docker-compose.yml) fallback | `http://127.0.0.1:8011` |
| `drones.crazyswarm_api_url` default in [clients.py](../drone_control_service/clients.py) | `http://127.0.0.1:8011` |

The bridge itself has no port setting: the port is whatever you pass to `uvicorn --port`.
The compose fallback is only used when `.env` leaves the variable out, so `.env` is what
actually applies. If you ever start the bridge on another port, change `.env` to match.

Your `.env` is also currently set to **`DRONE_MODE=mock`**, so no real drone will move until
you change it to `crazyswarm` (`./scripts/startup_all.sh --crazyswarm` does this for you).

### 12.8 Docker 1's lock is very coarse

Every route that changes something waits on one shared lock, and `setup_hover`, `land`
and `down` sleep *while holding it*. A `/down` request that arrives during `setup_hover`
will simply wait a few seconds rather than fail. Harmless normally, confusing under load.

### 12.9 CrazySwarm never reports speed

Anything you build that reads `vx/vy/vz` will quietly get `0.0` in crazyswarm mode. Use
`status` and changes in position instead.

### 12.10 Most formation shapes get stuck during reformation

This is the biggest problem in the stack, and it is not just about single file.

`front_compact` deletes the back spot and leaves everything else where it is. So one
drone from the back has to travel the whole depth of the formation to fill the gap, while
every drone it passes stays put. And `_move_drone_safely()` cannot ask anyone to move
aside.

Any `old_formation` where a row width **repeats or gets smaller** puts drones at the same
x position. That makes the trip run straight along a line that is already occupied, and
the mission hangs. This includes `[1,2,3,2,1]`, `[3,3,3]`, `[3,2,1]`, `[2,4,2]` and
`[1,1,1]`.

Only a single row (`[N]`) or a wedge that widens every row (`[1,2]`, `[1,2,3]`,
`[2,3,4]`) survives a full test of every possible single loss. And even those pass with a
gap of *exactly* `safety_gap`, so they have no margin at all.

The symptom: `last_move` shows `status: "timeout"` with a rising `blocked_count`, and
`last_block_reason` names a drone that the mover is trying to fly through. The full test
results, the reason, and three possible fixes are in §6, under *Why you cannot fly a
straight line*.

### 12.11 The Hungarian penalty settings cannot be reached from config

`forward_jump_penalty` (`100.0`) and `forward_jump_threshold_multiplier` (`2.0`) are
defaults on `AssignmentRequest`
([hungarian_service/app.py:21-22](hungarian_service/app.py#L21-L22)).
[`_call_hungarian`](mission_service/app.py#L210) never sends them, so nothing in
[config.yaml](config.yaml) or [.env](.env) can change them. Tuning either one means
editing the source. `backward_penalty` and `backward_threshold` *are* wired through from
`config.yaml` — they are simply set to `0.0`, which turns that penalty off.

---

## 13. A sensible order to read the code in

1. [formation_service/app.py](formation_service/app.py) — 74 lines, pure geometry.
2. [hungarian_service/app.py](hungarian_service/app.py) — 112 lines, pure matching.
3. [drone_common/control_client.py](drone_common/control_client.py) — the HTTP contract
   every service uses to reach Docker 1.
4. [drone_control_service/app.py](drone_control_service/app.py) — the list of routes.
5. [drone_control_service/clients.py](drone_control_service/clients.py) — start with
   `CrazySwarmApiDroneClient` and skip `AirSimDroneClient` the first time through.
6. [mission_service/app.py](mission_service/app.py) — read `_execute_reform` first, then
   `_move_drone_safely`, then `_mission_loop`.
7. [downed_simulator_service/app.py](downed_simulator_service/app.py) and
   [visualizer_service/viewer.py](visualizer_service/viewer.py) — leave these until last.

---

## 14. Understanding the algorithm with no hardware

The two pure services need nothing else running:

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

For the whole pipeline with no drones and no simulator:

```bash
./scripts/startup_all.sh --mock
curl -s -X POST http://localhost:8005/down \
  -H 'Content-Type: application/json' -d '{"drone_ids":[2]}'
sleep 5
curl -s http://localhost:8004/last_reform | python3 -m json.tool
curl -s http://localhost:8004/last_move   | python3 -m json.tool
```

Mock mode is also the cheapest way to test a new `old_formation` from end to end. Kill
each drone in turn and check `last_move` for `status: "timeout"`. That is exactly the
test behind the shape table in §6, and it is worth repeating for any shape not already
listed there.

In mock mode drones teleport (each hop sleeps 50 ms at most), so a full reformation
finishes in about a second. Every service except Docker 1's backend adapter runs exactly
the same code it would against real hardware.

---

## 15. Debugging checklist

| What you see | Where to look |
|---|---|
| Nothing takes off | `curl localhost:8004/status` → check `running` and `last_error`. Then `curl localhost:8001/health` → `status: degraded` means Docker 1 cannot reach the backend |
| Docker 1 says `degraded` | Is `CRAZYSWARM_API_URL` on the right port (§12.7)? Does `curl $CRAZYSWARM_API_URL/health` work from the **host**? |
| Takeoff works but nothing reforms | `curl localhost:8004/last_reform`. `no_reform_yet` means it never triggered. Check the dead drone actually reports `down` at `localhost:8001/drones/{id}/status` |
| Drones move but stop short | `last_move` showing `status: "timeout"` with a high `blocked_count` means `safety_gap` is too big for `formation_spacing` |
| A drone never moves at all | A rising `blocked_count` means a neighbour is inside `safety_gap`. `steps: 0` with `arrived` means it was already within `target_tolerance` |
| Reformation hangs, `blocked_count` rising, one drone has a huge `travel_distance` | §12.10 and §6. Does `old_formation` repeat or shrink a row width? Switch to `[1,2]`, `[1,2,3]` or `[N]` |
| Changed `old_formation` but nothing changed | `OLD_FORMATION` is read at startup. Use `docker compose restart mission`, not `/stop` and `/start` (§12.6) |
| Formation is in the wrong place | `anchor_policy` (§8), plus the spot-count mismatch (§12.1) |
| The wrong drone was picked for a spot | `last_reform.hungarian.assignment` → look at `travel_distance` and `delta_y`. The `forward_jump_penalty` may be firing |
| Visualizer blank, or dots off screen | `VIS_SCALE`. Use 500 px/m for Crazyflies, around 8 for AirSim distances |
| Visualizer will not open | Run `xhost +local:docker`, and check `DISPLAY` is set in the shell that ran the script |
| Restart did not redo the takeoff | §12.6 — use `docker compose restart mission` |

Per-service logs:

```bash
docker compose logs -f mission
docker compose logs -f drone-control
docker compose logs -f downed-simulator
```

Docker 1 runs on the host network, so it shows up in `docker compose ps` with no port
mapping listed. That is expected, not a fault.
