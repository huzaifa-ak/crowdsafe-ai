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

Four-week build, one developer. **Week 1 complete** (day 4 of 20). Deployed at
https://crowdsafe-ai.onrender.com.

A venue can be drawn, named, saved, reopened and edited again. Behind that:
app factory, config, schema applied on boot, a shared error shape, the full
venue API with server-side validation, and the editor canvas with brush and
rectangle tools, drag painting, resize and undo/redo.

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
| 2 | Agents navigate obstacles to exits, live and from saved runs |
| 3 | Congestion identified and explained |
| 4 | Comparison, examples, docs, deployment |

Locked decisions and the reasoning behind them are in `docs/decisions.md`.
