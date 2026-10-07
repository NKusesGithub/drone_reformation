# Documentation agent iteration log

Newest entry first.

---

## 2026-10-07

**Changed:** One focused Task A improvement. Nested the 11 subsections of
section 12 under its entry in the table of contents in
`docs/README_EXPLAINED.md`.

- Section 12 (`Traps and unexpected behavior`) is the debugging reference. Its
  subsections `12.1` to `12.11` are deep-linked from the other two documents
  (for example `README_EXPLAINED §12.1`, `§12.5`, `§12.6` and `§12.10`), but
  none of them were reachable from this document's own table of contents, which
  listed only the 15 top-level sections.
- Added a nested bulleted list under TOC item 12, with one link to each of the
  11 subsections. A reader can now jump straight to a trap.
- This is the parallel of the `README.md` change on 2026-10-06, which nested
  the two `###` subsections under `## The settings files`. The link text reuses
  the existing subsection heading text, so no heading changed and no other link
  needed an update.
- The four subsection anchors already in use across the three documents
  (`#121-...`, `#125-...`, `#126-...`, `#1210-...`) proved the anchor pattern,
  and the other seven follow the same rule.
- I weighed, and did not take, the candidate named by the 2026-10-06 entry (a
  cross-reference to replace a duplicated row between `README.md`'s
  `## Services and ports` table and the fault links). That table is the unique
  port list, not a copy of the fault tables, so a removal would change
  technical content, not navigation.
- No technical content changed: no route, port, path, number, or code block was
  touched. Navigation only.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 178 passed, 1
  xfailed. The change is documentation only, so the suite is unaffected.
- Internal links and anchors: a script checked every markdown link in the three
  documents (129 links). All 11 new TOC anchors resolve against real headings
  in `docs/README_EXPLAINED.md`, and every other in-document anchor still
  resolves. The only unresolved links are pre-existing and expected: the
  sibling `../../CrazySwarm2-with-Mocap` repository (not in this checkout), the
  gitignored runtime files `../config.yaml` and `../.env`, and the `#Lnnn`
  GitHub code line-anchors into `src/` files (these resolve on GitHub, not
  against markdown headings). None of these come from this change.
- ASD-STE100: the change is a list of navigation links. The link text is the
  existing, already-compliant subsection headings. No new prose sentence, no
  gerund as a noun, no em dash, and no slash in prose was added.

**Verdict: CONTINUE.** This completes the deep navigation of the most-referenced
section. The core of Task A (a table of contents, cross-links, and now reachable
traps) is in place, and the work is at the point of diminishing returns. The
other top-level sections (for example section 8, `Docker 4: mission, the brain`)
also have unnumbered `###` subsections that could be nested, but a table of
contents that lists every subsection loses its value as a compact scan. The next
run should weigh one such section against `COMPLETE: STOP`, and nest its
subsections only if that single section is long and central enough to need it.
If no such real, low-risk improvement is found, stop and record
`COMPLETE: STOP`.

---

## 2026-10-06

**Changed:** One focused Task A improvement. Added a compact table of contents
to `README.md`, the next step named by the 2026-09-24 entry. This is the
parallel of the `## Contents` section already in `docs/README_EXPLAINED.md`.

- Added a `## Contents` section between the `## Start here` section and
  `## The architecture` in `README.md`. It is a bulleted list that links to
  each of the 10 top-level `##` sections. The two `###` subsections under
  `## The settings files` (`anchor_policy` and `MISSION_AUTO_START`) are
  nested under it, so a reader can jump straight to either setting.
- A bulleted list fits here, because the `README.md` sections are not
  numbered (`docs/README_EXPLAINED.md` uses a numbered list, because its
  sections are numbered).
- The link text reuses the existing heading text, so no heading changed and
  no other link needed an update. The two subsection anchors keep their
  underscores (`#anchor_policy-...` and `#mission_auto_start-...`), which is
  how GitHub forms the anchor for those headings.
- No technical content changed: no route, port, path, number, or code block
  was touched. Navigation only.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 178 passed, 1
  xfailed. The change is documentation only, so the suite is unaffected.
- Internal links and anchors: a script checked every markdown link in the
  three documents. All 12 new TOC links (10 sections plus 2 subsections)
  resolve against real headings in `README.md`, and every other in-document
  anchor still resolves. The only unresolved links are pre-existing and
  expected: the sibling `../../CrazySwarm2-with-Mocap` repository (not in
  this checkout), the gitignored runtime files `../config.yaml` and
  `../.env`, and the `#Lnnn` GitHub code line-anchors into `src/` files
  (these resolve on GitHub, not against markdown headings). None of these
  come from this change.
- ASD-STE100: the change is a heading (`Contents`, one word) and a list of
  navigation links. The link text is the existing, already-compliant section
  headings. No new prose sentence, no gerund as a noun, no em dash, and no
  slash in prose was added.

**Verdict: CONTINUE.** The three documents now each have a table of contents
and a cross-link to the other two, so the core navigation of Task A is in
place. Smaller Task A work still exists, but it is now near the point of
diminishing returns, so the next run should weigh it carefully against
`COMPLETE: STOP`. One concrete, low-risk candidate, if judged useful: in
`README.md` the `## Services and ports` table and the `## Start here` fault
links both duplicate data that lives in the fault tables; a single
cross-reference could replace a duplicated row. If no such real, low-risk
improvement is found, stop and record `COMPLETE: STOP`.

---

## 2026-09-24

**Changed:** One focused Task A improvement. Added a compact table of contents
to `docs/README_EXPLAINED.md`, the next step named by the 2026-09-22 entry.

- Added a `## Contents` section between the intro and the first `---` in
  `docs/README_EXPLAINED.md`. It is a numbered list of the 15 top-level
  sections, each a link to its section anchor. A reader of this long document
  (about 1300 lines) can now jump to a topic.
- The link text reuses the existing heading text, so no heading changed and
  no other link needed an update. The anchors follow the same convention as
  the cross-links already in `README.md` and `docs/QUICKSTART.md` (for
  example `#15-checklist-for-faults`, which `README.md` already uses).
- No technical content changed: no route, port, path, number, or code block
  was touched. Navigation only.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 178 passed, 1
  xfailed. The change is documentation only, so the suite is unaffected.
- Internal links and anchors: a script checked every markdown link in the
  three documents. All 15 new TOC anchors resolve against real headings, and
  every other in-document anchor still resolves. The only unresolved links
  are pre-existing and expected: the sibling `../../CrazySwarm2-with-Mocap`
  repository (not in this checkout) and the gitignored runtime files
  `../config.yaml` and `../.env`. None of these come from this change.
- ASD-STE100: the change is a heading (`Contents`, one word) and a list of
  navigation links. The link text is the existing, already-compliant section
  headings. No new prose sentence, no gerund as a noun, no em dash, and no
  slash in prose was added.

**Verdict: CONTINUE.** Real Task A work is left. `README.md` (about 320 lines,
11 top-level sections and 2 subsections) still has no table of contents. A
good next step: add a compact table of contents to `README.md`, parallel to
the one added here, with a link to each of its `##` sections, and check that
each anchor resolves.

---

## 2026-09-22

**Changed:** One focused Task A improvement. Added cross-navigation from
`README.md`, which was the only one of the three documents with no links to the
other two.

- Added a `## Start here` section at the top of `README.md`, below the
  ASD-STE100 note. It has a small "Your task / Read this" table that points a
  reader to `docs/QUICKSTART.md` (fly real drones) and
  `docs/README_EXPLAINED.md` (why each part exists, and the traps). This
  completes the cross-link triangle: `QUICKSTART.md` and `README_EXPLAINED.md`
  already link back to `README.md` and to each other.
- The same section adds two direct links to the fault tables:
  `README_EXPLAINED §15` for the stack, and `QUICKSTART §8` for the radio, ROS
  and the bridge. Both anchors are already in use inside the other two
  documents, so they are proven.
- Gave the previously unheaded intro and architecture diagram a `##
  The architecture` heading, so the new `## Start here` section has a clean
  boundary and a reader can scan the top of the file.
- No technical content changed: no route, port, path, number, or code block was
  touched. Navigation and headings only.

**Checks:**

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 169 passed, 1
  xfailed. The change is documentation only, so the suite is unaffected.
- Internal links and anchors: a script checked every markdown link in the three
  documents. Each new link resolves, and both new anchors resolve. The only
  unresolved links are pre-existing and expected: the sibling
  `../../CrazySwarm2-with-Mocap` repository (not in this checkout) and the
  gitignored runtime files `../config.yaml` and `../.env`. None of these come
  from this change.
- ASD-STE100: each new sentence obeys the limits. "This project has three
  documents." (5 words) and "Use the document that fits your task." (7 words,
  imperative). The fault-table lines are three short sentences, the longest 10
  words. No gerund as a noun, no em dash, and no slash in prose.

**Verdict: CONTINUE.** Real Task A work is left. `README.md` and the 15-section
`docs/README_EXPLAINED.md` still have no table of contents, and
`README_EXPLAINED.md` is long enough that a short TOC of its numbered sections
would help a reader jump to a topic. A good next step: add a compact table of
contents to `docs/README_EXPLAINED.md`, with a link to each of its numbered
sections, and check that each anchor resolves.

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
