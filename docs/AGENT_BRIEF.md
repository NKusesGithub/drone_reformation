# Daily agent brief

A scheduled cloud agent reads this file each day and does one iteration of work.
The agent starts with no memory, so this file and `DOC_ITERATION_LOG.md` are its
only context.

---

## Step 0: read the log first, and honour the stop condition

Read [DOC_ITERATION_LOG.md](DOC_ITERATION_LOG.md). It records what each previous
run changed, and a quality verdict.

**If the newest entry says the documentation reached good quality and the work
must stop, then stop.** Make no changes. Open no pull request. End the run with a
statement that the documentation is already complete.

If the file does not exist, this is day 1. Make it.

---

## What this repository is

Six containers hold a group of Crazyflie drones in a formation. They build the
formation again when a drone is lost.

| Service | Port | Function |
|---|---|---|
| `drone-control` | 8001 | The only service that speaks to the hardware, through a CrazySwarm bridge on `127.0.0.1:8011` |
| `hungarian` | 8002 | Matches a drone to a slot |
| `formation` | 8003 | Calculates the geometry |
| `mission` | 8004 | The orchestrator, and the only service that keeps state |
| `downed-simulator` | 8005 | Injects faults |
| `visualizer` | none | An OpenCV window |
| `dashboard` | 8006 | A web page of buttons and live status, in `src/dashboard_service/` |

---

## Hard constraint: the documents are ASD-STE100

`README.md`, `docs/QUICKSTART.md` and `docs/README_EXPLAINED.md` are written in
ASD-STE100 Simplified Technical English. **They must stay compliant.** Obey these
rules in each edit:

- A descriptive sentence has a maximum of 25 words. A procedural sentence has a
  maximum of 20 words.
- A paragraph has a maximum of six sentences.
- Use the imperative and the active voice for each instruction.
- Use the approved words. Use "make sure" and not "ensure" or "verify". Use "do a
  check of" and not "inspect" or "examine". Use "start" and not "initiate". Use
  "use" and not "utilize". Use "before" and not "prior to". Use "to" and not "in
  order to". Use "enough" and not "sufficient". Use "show" and not "indicate".
- Do not use a gerund as a noun or as an adjective. Write "Before you start the
  engine", and not "Before starting the engine".
- Do not use an em dash. Do not use a slash in prose, but "and/or" is permitted.
- Use one term for one thing. Do not use synonyms.
- Put a WARNING before a step with a risk of injury. Put a CAUTION before a step
  with a risk of damage to equipment.
- **Never change a technical name, a number, a port, a route, a file path, a code
  block or a value to obey a rule.** If a rule and the technical accuracy have a
  conflict, keep the accuracy and record the conflict in the log.

---

## Task A: make the documents easier to traverse

This is the primary task each day. Make one focused improvement, and not a large
rewrite. Examples of good work:

- Add or improve a table of contents.
- Add navigation between the three documents, so a reader can move between them.
- Group the sections in a better sequence, so a reader finds an answer faster.
- Add a short "start here" or "find your problem" entry point.
- Improve the headings, so the reader can scan them.
- Remove data that is in two places, and put one cross-reference in its place.
- Make the tables easier to read.

Rules for this task:

1. Change the structure and the navigation. Do not change the technical content.
2. If you change a heading, update each link that points to it. The anchors must
   stay correct.
3. Make sure that each internal link and anchor resolves before you finish.
4. Keep each change small enough for a person to review in a few minutes.

---

## Task B: a debugging panel on the dashboard

The dashboard at `src/dashboard_service/` needs a panel that shows the user what
is wrong. Build this one time. After the panel exists, improve it only in a small
way each day, or leave it and do Task A.

The panel must show:

- Which services answer, and which do not: ports 8001 to 8006, and the bridge on
  `127.0.0.1:8011`.
- A clear indication when a service is down.
- A checklist of the next checks for the user.

Put these known faults in the checklist, because a person cannot find them
without help:

| Symptom | What the user must check |
|---|---|
| The mission `/health` route always answers `ok`, also when its worker is dead | Read `/status` and look at `running` and `last_error`. Never rely on `/health` |
| `drone-control` reports `degraded` | The CrazySwarm bridge on 8011 is not running, or `CRAZYSWARM_API_URL` gives the incorrect port |
| Each drone is `down` on the second run | The bridge never clears a `down` mark. Start the bridge again |
| The reform fails with `Formation returned too few slots` | `sum(mission.old_formation)` is not equal to `len(drones.ids)` |
| `last_move` gives `timeout` and `blocked_count` increases | The shape of the formation has a row that repeats or that gets narrower. Such a shape makes a drone stuck. Use `[1,2]`, `[1,2,3]` or `[N]` |
| Mission `last_error` gives `Connection refused` to hungarian | A race at startup. Run `docker compose restart mission` |
| A restart did not do the takeoff again | The one-time flags never reset. Use `docker compose restart mission` |

Rules for this task:

1. The dashboard forwards a request only if it is in the `ALLOWED` list in
   `src/dashboard_service/app.py`. Add each new route to that list.
2. The dashboard listens on `127.0.0.1` only. Keep it like this.
3. Do not add an emergency stop to the page. The dashboard cannot get to the
   bridge. The E-STOP in the preflight GUI is the only emergency stop.
4. Write a test in `tests/` for each new route.

---

## Before you finish: the checks

Run all of these. Do not open a pull request if one fails.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

Then make sure that each internal link and anchor in the three documents
resolves. Then make sure that each sentence and paragraph that you wrote obeys
the ASD-STE100 limits above.

---

## How to finish

1. Add an entry at the top of the log in `docs/DOC_ITERATION_LOG.md`. Give the
   date, what you changed, the result of the checks, and a quality verdict.
2. The quality verdict is one of two values:
   - `CONTINUE`: more useful work exists. Name it for the next run.
   - `COMPLETE: STOP`: the documents are good, and more changes would only add
     risk. Use this value when you cannot find a real improvement. Do not invent
     work to fill a day.
3. Open one pull request with your changes and the log entry. Use a title that
   gives the change. Do not push to `main`.
4. If your verdict is `COMPLETE: STOP`, say so first in the pull request body, so
   the user sees it.

**Be honest in the verdict.** It is a good result to stop after a few days. It is
a bad result to make the documents worse with changes that nobody needs.
