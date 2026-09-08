"""Running simulations.

    POST /api/simulations       run a saved venue and store the result
    GET  /api/simulations/<id>  fetch a stored run, trace included
    GET  /api/simulations       list runs, newest first

Runs happen inline rather than on a queue. At the size limits in config a run
takes well under a second, and a background worker would mean polling, job
state and a second process to deploy — all cost, no benefit at this scale.
"""

import json

from flask import Blueprint, jsonify, request, url_for

from ..config import Config
from ..db import repository
from ..engine.grid import Grid
from ..engine.layout import inspect
from ..analysis import metrics as metrics_module
from ..analysis.score import score as score_run
from ..engine.simulation import SimulationConfig, simulate
from ..engine import trace as trace_store
from .errors import NotFoundError, ValidationError
from .schemas import validate_simulation_config

bp = Blueprint("simulations", __name__, url_prefix="/api/simulations")


def _json_body():
    body = request.get_json(silent=True)
    if body is None:
        raise ValidationError(
            "Expected a JSON body.",
            [{"field": "body", "message": "send JSON with Content-Type: application/json"}],
        )
    return body


def _summarise(result, grid: Grid, report: dict, settings: dict) -> dict:
    """The headline numbers, kept flat and small for listings and the rail."""
    clearing = result.clearing_ticks

    # Free-flow baseline: the faster of these two is impossible to beat, so the
    # slower one is the floor. Walking distance alone would punish any venue
    # with a narrow door regardless of how good its layout is
    # (docs/decisions.md, correction 1).
    walk_ticks = (report["longest_walk"] or 0) / settings["speed"]
    throughput_ticks = (
        result.agent_count / grid.total_exit_width if grid.total_exit_width else None
    )
    free_flow = max(walk_ticks, throughput_ticks) if throughput_ticks else None

    return {
        "status": result.status,
        "ticks": result.ticks,
        "agent_count": result.agent_count,
        "evacuated": result.evacuated,
        "stranded": result.stranded,
        "clearing_ticks": clearing,
        "clearing_seconds": round(clearing * Config.SECONDS_PER_TICK, 1) if clearing else None,
        "exit_usage": {str(k): v for k, v in result.exit_usage.items()},
        # How much rerouting the run needed, and how many searches that cost.
        # A large gap between them means the route cache is doing its job.
        "reroutes": result.reroutes,
        "searches": result.searches,
        "exit_widths": {str(e.id): e.width for e in grid.exits},
        "free_flow_ticks": round(free_flow, 1) if free_flow else None,
        "time_ratio": round(clearing / free_flow, 2) if clearing and free_flow else None,
    }


@bp.post("")
def run_simulation():
    body = _json_body()

    venue_id = body.get("venue_id")
    if not isinstance(venue_id, int) or isinstance(venue_id, bool):
        raise ValidationError(
            "A venue_id is required.",
            [{"field": "venue_id", "message": "venue_id must be the id of a saved venue"}],
        )

    venue = repository.get_venue(venue_id)
    if venue is None:
        raise NotFoundError(f"No venue with id {venue_id}.")

    settings = validate_simulation_config(body.get("config"))
    grid = Grid.from_venue(venue)

    # Refuse layouts that cannot be evacuated, rather than running for 600 ticks
    # to produce a result whose only content is "nothing happened".
    report = inspect(grid)
    if not report["ok"]:
        raise ValidationError(
            "This venue cannot be simulated yet.",
            [{"field": "venue", "message": p["message"]} for p in report["problems"]],
        )

    spawn_capacity = len(grid.spawn_cells) * settings["cell_capacity"]
    if settings["num_agents"] > spawn_capacity:
        raise ValidationError(
            "That many people will not fit in the spawn area.",
            [{
                "field": "num_agents",
                "message": f"{len(grid.spawn_cells)} spawn cells hold at most "
                           f"{spawn_capacity} people at {settings['cell_capacity']} per cell",
            }],
        )

    result = simulate(grid, SimulationConfig(**settings))
    summary = _summarise(result, grid, report, settings)

    blob = trace_store.encode(result.trace)
    summary["trace"] = trace_store.summarise(result.trace, blob)

    measured = metrics_module.compute(grid, result, settings, report["longest_walk"])
    assessment = score_run(measured)
    summary["score"] = assessment["score"]
    summary["grade"] = assessment["grade"]

    simulation_id = repository.create_simulation(
        venue_id=venue["id"],
        venue_snapshot=json.dumps({
            "width": venue["width"], "height": venue["height"], "cells": venue["cells"],
        }),
        config_json=json.dumps(settings),
        seed=settings["seed"],
        status=result.status,
    )
    repository.create_result(
        simulation_id=simulation_id,
        metrics_json=json.dumps({**summary, "metrics": measured, "assessment": assessment}),
        heatmap_json=json.dumps(result.density),
        trace_blob=blob,
    )

    payload = _payload(simulation_id, venue, settings, summary, result.trace,
                       density=result.density, metrics=measured, assessment=assessment)
    response = jsonify(payload)
    response.status_code = 201
    response.headers["Location"] = url_for("simulations.get_simulation",
                                           simulation_id=simulation_id)
    return response


@bp.get("/<int:simulation_id>")
def get_simulation(simulation_id: int):
    row = repository.get_simulation(simulation_id)
    if row is None:
        raise NotFoundError(f"No simulation with id {simulation_id}.")

    snapshot = json.loads(row["venue_snapshot"])
    venue = {"id": row["venue_id"], **snapshot}
    stored = json.loads(row["metrics_json"]) if row["metrics_json"] else {}

    # Both are large. A caller that only wants the numbers can say so rather
    # than pulling a few hundred kilobytes it will throw away.
    want_trace = request.args.get("trace", "1") != "0"
    want_density = request.args.get("density", "1") != "0"

    return jsonify(
        _payload(
            row["id"],
            venue,
            json.loads(row["config_json"]),
            {k: v for k, v in stored.items() if k not in ("metrics", "assessment")},
            trace_store.decode(row["trace_blob"]) if want_trace else None,
            density=json.loads(row["heatmap_json"]) if want_density and row["heatmap_json"] else None,
            metrics=stored.get("metrics"),
            assessment=stored.get("assessment"),
            created_at=row["created_at"],
        )
    )


@bp.get("")
def list_simulations():
    venue_id = request.args.get("venue_id", type=int)
    rows = repository.list_simulations(venue_id)
    return jsonify([
        {
            "id": row["id"],
            "venue_id": row["venue_id"],
            "status": row["status"],
            "seed": row["seed"],
            "created_at": row["created_at"],
            "summary": json.loads(row["metrics_json"]) if row["metrics_json"] else None,
        }
        for row in rows
    ])


def _payload(simulation_id: int, venue: dict, settings: dict, summary: dict,
             trace: list | None, density: dict | None = None,
             metrics: dict | None = None, assessment: dict | None = None,
             created_at: str | None = None) -> dict:
    payload = {
        "id": simulation_id,
        "venue_id": venue.get("id"),
        "config": settings,
        "summary": summary,
        # The venue as it was when this ran, so a saved result can be replayed
        # even after the venue has been edited.
        "venue_snapshot": {
            "width": venue.get("width"),
            "height": venue.get("height"),
            "cells": venue.get("cells"),
        },
    }
    if metrics is not None:
        payload["metrics"] = metrics
    if assessment is not None:
        payload["assessment"] = assessment
    if trace is not None:
        payload["trace"] = trace
    if density is not None:
        payload["density"] = density
    if created_at:
        payload["created_at"] = created_at
    return payload
