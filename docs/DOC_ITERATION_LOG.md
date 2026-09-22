# Documentation agent iteration log

Newest entry first.

---

## 2026-09-22

**Changed:** Task A only. `README.md` had no link to the other two documents anywhere in
its text, so a reader who lands there first had no way to find them without opening
`docs/` by hand.

- Added a "Where to go next" section near the top of `README.md`, right after the
  intro paragraph and before the architecture diagram. It tells the reader that
  `README.md` is the reference for the services, ports and settings, and gives a
  link to `docs/QUICKSTART.md` for the run-book and a link to
  `docs/README_EXPLAINED.md` for the reason each part works this way and the list
  of traps.
- No heading in `README.md` changed, and no other document links into `README.md`
  by anchor, so no link needed a fix for this change.
- `docs/QUICKSTART.md` and `docs/README_EXPLAINED.md` already cross-link to
  `README.md` and to each other at the top of each file, from earlier work. This
  entry only closes the one missing direction.
- Made no other change. Task B's panel needs no change today.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 169 passed, 1 xfailed.
- Wrote a script that reads every heading in the three documents, builds its
  anchor the way GitHub does, and checks each `[text](link)` in the three
  documents against it. Every internal link and anchor resolves. The links to
  the sibling `CrazySwarm2-with-Mocap` repository and to the gitignored
  `config.yaml` and `.env` files are outside this repository and were not part
  of the check, as in earlier runs.
- Checked the new sentences by hand against the ASD-STE100 limits: each sentence
  is under 20 words, each paragraph has one or two sentences, and no sentence uses
  a banned word, a gerund as a noun, an em dash or a slash.

**Verdict: CONTINUE.** `docs/README_EXPLAINED.md` is 1297 lines with 15 numbered
sections and no table of contents. A good next step: add a table of contents at
the top of `docs/README_EXPLAINED.md`, with one link for each of its 15 sections,
so a reader can jump to a section with no need to scroll.

---

## 2026-09-21

**Changed:** Built the Task B debugging panel on the dashboard (one time, as the
brief asks). Also fixed a pre-existing gap that blocked the whole test suite
from running.

- Added a `Debug` tab to `src/dashboard_service/static/index.html`, with a
  service-status table and a known-faults table.
- Added `GET /api/debug/status` to `src/dashboard_service/app.py`. It checks
  `/health` on drone-control (8001), hungarian (8002), formation (8003),
  mission (8004), downed-simulator (8005), the CrazySwarm bridge (8011), and
  reports the dashboard itself (8006) as up without a network call. Each
  check has a 2-second timeout and never raises, so one down service cannot
  block the panel. This is a read-only debug check, kept separate from
  `ALLOWED` and `UPSTREAMS`: it is never a user-triggered forward, only a
  probe.
- The panel also lists the seven known faults from the brief (the `/health`
  vs `/status` trap, the degraded-bridge case, the stuck `down` mark, the
  formation slot-count error, the stuck-waypoint shapes, the hungarian
  race at startup, and the one-time takeoff flags) so a user can find them
  without reading the code.
- Added `HUNGARIAN_SERVICE_URL`, `FORMATION_SERVICE_URL`, and
  `CRAZYSWARM_BRIDGE_URL` to the dashboard's environment in
  `docker-compose.yml` and documented `CRAZYSWARM_BRIDGE_URL` in
  `.env.example`. The bridge check needs its own URL because the dashboard
  container does not share `drone-control`'s `network_mode: host`, so
  `127.0.0.1:8011` from inside the dashboard is not the host's port 8011.
- Added `src/dashboard_service/static/app.js` polling for the new panel
  (every 4 seconds) and 6 new tests in `tests/test_dashboard.py`.
- Fixed a pre-existing bug unrelated to this task: `tests/conftest.py` has
  pinned `CONFIG_PATH` to `tests/fixtures/config.yaml` since before this
  agent's history began, but that file was never committed. This failed
  collection for `tests/test_drone_control_health.py` and
  `tests/test_mission_safety.py` and would have failed the checks below
  outright. The root cause was `.gitignore`: its `config.yaml` line was not
  anchored to the repo root, so it also matched and silently dropped
  `tests/fixtures/config.yaml` from every commit. Anchored the rule to
  `/config.yaml` and added `tests/fixtures/config.yaml` with 5 drones (ids
  1-5), to match what `tests/test_config.py` already asserted the fixture
  must have.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 161 passed, 1
  xfailed.
- No changes were made to `README.md`, `docs/QUICKSTART.md`, or
  `docs/README_EXPLAINED.md`, so their links, anchors, and ASD-STE100
  compliance are unchanged from the last time they were checked.

**Verdict: CONTINUE.** Task A (navigation and structure of the three
documents) has not been touched yet. A good next step: add a short "start
here" entry point and cross-links between `README.md`,
`docs/QUICKSTART.md`, and `docs/README_EXPLAINED.md`, per Task A in the
brief. The debugging panel should otherwise only get small improvements
from here, for example showing the dashboard's own `/health` upstream
targets next to the new debug table so the two do not drift apart.
