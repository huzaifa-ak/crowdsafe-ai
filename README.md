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

Four-week build, one developer. Day 1 of 20 complete: app factory, config,
schema applied on boot, error shape, `GET /api/venues`, dashboard shell, test
harness.

| Week | Target |
|------|--------|
| 1 | Create, edit, save and reopen a venue; validation |
| 2 | Agents navigate obstacles to exits, live and from saved runs |
| 3 | Congestion identified and explained |
| 4 | Comparison, examples, docs, deployment |

Locked decisions and the reasoning behind them are in `docs/decisions.md`.
