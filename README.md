# CrowdSafe AI

A web tool for testing whether a venue empties safely. Draw a floor plan on a
1 m grid, run a crowd of 20–300 people through it, and get back a density
heatmap, clearing time, exit usage, a safety score and specific suggestions for
what to change. Two layouts can be compared side by side.

The simulation runs server-side in Python; the browser draws the plan and
replays the run.

## Requirements

Python 3.12+.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                    # http://127.0.0.1:5000
```

The SQLite database is created and migrated on first boot. Point it somewhere
else with `DATABASE_PATH=/path/to/crowdsafe.db`.

## Tests

```bash
python -m pytest
```

## Layout

```
app/
  __init__.py     create_app(): config, database, blueprints
  config.py       limits, grid semantics, defaults — every tunable number
  db/             schema.sql, connection handling, repository functions
  api/            JSON routes and the shared error shape
  engine/         grid, A*, agents, tick loop, trace          (Week 2)
  analysis/       heatmap, bottlenecks, metrics, score, rules  (Week 3)
  seed/           example venues loaded on first boot
  templates/      server-rendered page shells
  static/         css and ES modules, no build step
tests/            pytest; ASCII-drawn grids as fixtures
docs/             decisions, architecture, algorithms, API
```

## Deployment

Render, auto-deploying from `main` via `render.yaml`:

```
gunicorn "app:create_app()" --workers 2 --timeout 60
```

The free tier's disk is ephemeral, so the database is rebuilt on every deploy.
Example venues are seeded on boot to keep a fresh instance demo-ready; saved
work does not survive a redeploy.

## Status

Four-week build, one developer. Day 16 of 20 complete. Deployed at
https://crowdsafe-ai.onrender.com.

A venue can be drawn, named, saved, reopened and edited again. Behind that:
app factory, config, schema applied on boot, a shared error shape, the full
venue API with server-side validation, and the editor canvas with brush and
rectangle tools, drag painting, resize and undo/redo.

The engine's foundations are in: a server-side grid model that groups adjacent
exit cells into doorways, multi-source BFS distance fields, and deterministic
A* that accepts a cost function so congestion can steer routes later. The tick loop runs: a seeded crowd spawns across the spawn area, routes to its
nearest exit, and walks out — slowed by the people ahead of it, capped at three
per square metre, and admitted through each doorway at one person per cell per
tick. A run ends when the room is clear, when the tick budget runs out, or when
nothing has moved for 25 ticks.

People who stay stuck behind a jam reroute around it, and will change which
door they are heading for when another one is clearly quicker. Exit choice has
two models: `nearest` (the default — an unsignposted crowd, and the one that
exposes a lopsided layout) and `balanced` (people weigh the queue as well as
the walk, modelling marshals or good signage). Running one venue both ways
measures what crowd management alone would be worth.

### Simulation API

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/simulations`      | Run a saved venue; returns summary and trace |
| `GET`  | `/api/simulations/{id}` | Fetch a stored run, trace included |
| `GET`  | `/api/simulations`      | List runs, newest first; `?venue_id=` to filter |

Runs happen inline — at the configured limits a worst-case run takes under a
second. Each stores the venue as it was at run time, so a result keeps meaning
its own layout after the venue is edited.

Add `?trace=0` or `?density=0` when fetching a run to leave the large parts out.

Measured at the largest venue the API accepts (80 × 60, 300 people, one narrow
door), against budgets asserted in the test suite. The run-time budget is set
to catch an order-of-magnitude regression, not to measure the machine — the
same run takes under a second on a fast desktop and a few seconds on a laptop:

| | Measured | Budget |
|---|---|---|
| Run time | 0.8 s | 10 s |
| Trace, raw | 260 KB | 2 MB |
| Trace, stored | 40 KB | 256 KB |

A venue can also be checked for whether it is *usable* — has exits, has a crowd, and
the crowd can reach a way out:

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/venues/validate`      | Layout report for an unsaved venue |
| `GET`  | `/api/venues/{id}/validate` | Layout report for a saved one |

### Playback

`/simulate/<id>` configures a run, sends it, and plays it back on the canvas.
The trace arrives with the response, so scrubbing is entirely local and never
waits on the network. Space plays and pauses, the arrow keys step a tick at a
time (hold shift for ten), and the rate button cycles 1× to 8× real time.

### Comparison

`/compare` puts two runs side by side: both plans with their heatmaps, a table
of deltas, and which bottlenecks went away, appeared, or are still there.

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/comparisons`      | Compare two stored runs and save the result |
| `GET`  | `/api/comparisons/{id}` | Fetch a saved comparison |
| `GET`  | `/api/comparisons`      | List saved comparisons |

The first thing a comparison does is check the two runs are comparable at all.
Different crowd sizes, seeds or routing models differ for reasons that have
nothing to do with the layout, and a table of deltas presented without that
caveat is worse than no table — it looks like evidence. Mismatches are listed
above the numbers, not below them.

### Calibration

`python calibrate.py` scores eight reference venues spanning obviously fine to
obviously dangerous and prints the table, with the grade band a person would
give each one. The thresholds in `app/analysis/score.py` are tuned against that
set, and `tests/test_calibration.py` fails if any venue leaves its band — so a
change that looks reasonable in isolation but breaks the ranking gets caught.

### Recommendations

Nine rules read the metrics and findings and say what to change, ordered by how
much time each would buy. Every one carries the evidence that produced it,
because a suggestion you cannot check is a suggestion you cannot trust.

Savings are labelled as estimates and derived openly — they extrapolate from
one run rather than measuring a second one. Where an estimate would be
guesswork the rule says what to try instead, since the app can simply run it
and a measured answer beats a modelled one. The capacity rule offers a starting
point to test rather than a calculated number, because crowded share does not
scale with the crowd in any way worth extrapolating.

The most important rule is a negative one: a venue limited by walking distance
is never told to widen its doors. Recommending building work that cannot help
is worse than recommending nothing.

### Bottlenecks

Crowded cells are grouped into contiguous regions and ranked by the time they
cost, each with a location and a description: *"2 m gap in the centre of the
plan — 52 m² reached 3.0 people per m² and stayed above 2.0 for up to 70
ticks."*

A region usually spans both the constriction and the crowd backed up behind it.
The reported coordinate is the narrowest cell, not the centroid, because the
centroid lands in the queue — which is the symptom rather than the cause.
Hovering a finding outlines it on the plan.

### Safety score

A score out of 100 with an A–F grade, built by subtracting three bounded
penalties from a clean sheet. Every penalty names what caused it.

| Component | Weight | Measures |
|---|---|---|
| Time | 35 | How long it took (25) plus how wasteful that was (10) |
| Congestion | 40 | How much of the floor got tight, and for how long |
| Exits | 25 | Whether there is enough door, and whether it is used evenly |

Anyone left inside caps the score at 35 regardless of the rest.

Two things the score deliberately avoids. It does not lean on the free-flow
ratio, because that baseline grows with the crowd once the doors are the
binding limit — a ratio-driven score rates 300 people safer than 120, and
flatters venues whose theoretical best is slow because their doors are narrow.
And exit balance is measured against each door's share of the total width, so a
3 m door carrying three quarters of the crowd is correct rather than penalised.

### Heatmap

Three views of the same run, answering different questions. **Worst crowding**
is peak people per m², scaled against the density cap rather than the observed
maximum, so a venue that never got busy looks calm instead of being rescaled
until it looks alarming. **Time spent crowded** counts ticks above the
threshold — a corner that briefly packed and a corridor that stayed packed are
different problems. **Busiest routes** is person-ticks per cell, which shows
where people went rather than where they suffered.

Warm colour is used nowhere else in the app, so anything warm on the canvas
means crowding and nothing else.

### Editor

Brush or rectangle, painting the cell type picked in the palette. Number keys
select a cell type, B and R switch tool, right-click erases back to floor, and
Ctrl+Z / Ctrl+Shift+Z step through history. A whole drag is one undo entry.

### Venue API

| Method | Path | Notes |
|--------|------|-------|
| `GET`    | `/api/venues`      | Listing, without cell data |
| `POST`   | `/api/venues`      | 201 with a `Location` header |
| `GET`    | `/api/venues/{id}` | Full venue including `cells` |
| `PUT`    | `/api/venues/{id}` | Replaces every field |
| `DELETE` | `/api/venues/{id}` | 204 |

A venue's grid is one flat string of digits, row-major, one per cell:
`0` floor, `1` wall, `2` barrier, `3` entrance, `4` exit, `5` spawn.

Validation failures return 422 and list every problem at once, so the editor
can show all of them in one pass:

```json
{"error": {"code": "VALIDATION", "message": "This venue could not be saved.",
           "details": [{"field": "width", "message": "width must be between 5 and 80"}]}}
```

| Week | Target |
|------|--------|
| 1 | Create, edit, save and reopen a venue; validation — **done** |
| 2 | Agents navigate obstacles to exits, live and from saved runs — **done** |
| 3 | Congestion identified and explained — **done** |
| 4 | Comparison, examples, docs, deployment |

Locked decisions and the reasoning behind them are in `docs/decisions.md`.
