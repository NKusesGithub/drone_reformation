# Documentation agent iteration log

Newest entry first.

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
