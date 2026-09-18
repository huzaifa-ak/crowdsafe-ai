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
from ..engine.pathfinding import distance_field
from ..analysis import metrics as metrics_module
from ..analysis.bottlenecks import detect as detect_bottlenecks
from ..analysis.improve import improve
from ..analysis.recommendations import recommend
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
    arriving = settings["mode"] == "arrival"
    total_width = grid.total_entrance_width if arriving else grid.total_exit_width
    walk_ticks = (report["longest_walk"] or 0) / settings["speed"]
    throughput_ticks = result.agent_count / total_width if total_width else None
    free_flow = max(walk_ticks, throughput_ticks) if throughput_ticks else None

    return {
        "status": result.status,
        "ticks": result.ticks,
        "agent_count": result.agent_count,
        "evacuated": result.evacuated,
        "stranded": result.stranded,
        "clearing_ticks": clearing,
        "clearing_seconds": round(clearing * Config.SECONDS_PER_TICK, 1) if clearing else None,
        "mode": settings["mode"],
        "exit_usage": {str(k): v for k, v in result.exit_usage.items()},
        "entrance_usage": {str(k): v for k, v in result.entrance_usage.items()},
        "checkpoint_usage": {str(k): v for k, v in result.checkpoint_usage.items()},
        "checkpoint_widths": {str(s_.id): s_.width for s_ in grid.checkpoints},
        "vip_count": result.vip_count,
        "vip_places": len(grid.restricted_spawn_cells) * settings["cell_capacity"],
        "general_places": len(grid.general_spawn_cells) * settings["cell_capacity"],
        "vip_cleared_seconds": (
            round(result.vip_clearing_ticks * Config.SECONDS_PER_TICK, 1)
            if result.vip_clearing_ticks else None
        ),
        "stopped_short": result.stopped_short,
        # How much rerouting the run needed, and how many searches that cost.
        # A large gap between them means the route cache is doing its job.
        "reroutes": result.reroutes,
        "searches": result.searches,
        "exit_widths": {str(e.id): e.width for e in grid.exits},
        "entrance_widths": {str(e.id): e.width for e in grid.entrances},
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

    # Refuse layouts that cannot be run, rather than spending 600 ticks to
    # produce a result whose only content is "nothing happened".
    report = inspect(grid)
    arriving = settings["mode"] == "arrival"

    # Nobody checks tickets on the way out, so the split is meaningless for an
    # evacuation. Ignored rather than refused: the setting belongs to the
    # venue, and switching mode to compare should not need it cleared first.
    if not arriving:
        settings["vip_count"] = 0

    if arriving:
        vips = settings["vip_count"]
        vip_capacity = len(grid.restricted_spawn_cells) * settings["cell_capacity"]
        general_capacity = len(grid.general_spawn_cells) * settings["cell_capacity"]

        if vips and not grid.checkpoints:
            raise ValidationError(
                "This venue has no checkpoints.",
                [{"field": "vip_count",
                  "message": "A VIP area is the part of the plan you can only "
                             "reach through a checkpoint, and there are none "
                             "here. Paint a checkpoint across the way into the "
                             "area you want restricted."}],
            )
        if vips and not grid.restricted_spawn_cells:
            raise ValidationError(
                "This venue has no VIP area.",
                [{"field": "vip_count",
                  "message": "There are checkpoints, but every part of the floor "
                             "can still be reached without passing one, so there "
                             "is nowhere only VIPs can go."}],
            )
        if vips > vip_capacity:
            raise ValidationError(
                "That many VIPs will not fit.",
                [{"field": "vip_count",
                  "message": f"The VIP area holds {vip_capacity} people at "
                             f"{settings['cell_capacity']} per m²."}],
            )
        if settings["num_agents"] - vips > general_capacity:
            raise ValidationError(
                "That many people will not fit in the general area.",
                [{"field": "num_agents",
                  "message": f"It holds {general_capacity} at "
                             f"{settings['cell_capacity']} per m², and "
                             f"{settings['num_agents'] - vips} are not VIPs."}],
            )
        if not grid.entrances:
            raise ValidationError(
                "This venue cannot be filled yet.",
                [{"field": "venue",
                  "message": "There are no entrances, so nobody can get in. "
                             "Paint some entrance cells and try again."}],
            )
        if not grid.spawn_cells:
            raise ValidationError(
                "This venue cannot be filled yet.",
                [{"field": "venue",
                  "message": "There is no spawn area, so there is nowhere for "
                             "people to go."}],
            )
        # Reachability is measured from the entrances for an arrival, so the
        # walking floor is the longest walk *in* rather than out.
        reach = distance_field(grid, grid.entrance_cells)
        walks = [reach[cell] for cell in grid.spawn_cells if cell in reach]
        if not walks:
            raise ValidationError(
                "This venue cannot be filled yet.",
                [{"field": "venue",
                  "message": "No part of the spawn area can be reached from an "
                             "entrance."}],
            )
        report = {**report, "longest_walk": max(walks)}
    elif not report["ok"]:
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
    findings = detect_bottlenecks(grid, result.density, mode=settings["mode"])
    advice = recommend(grid, measured, findings, settings)

    # No grade for an arrival. The score's thresholds were calibrated against
    # evacuations, where the clock is a safety limit; a venue taking four
    # minutes to fill is normal rather than dangerous. Grading one against the
    # other's scale would produce a number that looks authoritative and means
    # nothing. The measurements and the findings still stand on their own.
    assessment = None if settings["mode"] == "arrival" else score_run(measured)
    if assessment:
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
        bottlenecks_json=json.dumps(findings),
        recommendations_json=json.dumps(advice),
        trace_blob=blob,
    )

    payload = _payload(simulation_id, venue, settings, summary, result.trace,
                       density=result.density, metrics=measured, assessment=assessment,
                       bottlenecks=findings, recommendations=advice)
    response = jsonify(payload)
    response.status_code = 201
    response.headers["Location"] = url_for("simulations.get_simulation",
                                           simulation_id=simulation_id)
    return response


def load_run(simulation_id: int, with_trace: bool = True,
             with_density: bool = True) -> dict:
    """A stored run, assembled the same way the endpoint returns it.

    Shared with comparisons so the two can never drift apart in what they mean
    by "a run".
    """
    row = repository.get_simulation(simulation_id)
    if row is None:
        raise NotFoundError(f"No simulation with id {simulation_id}.")

    snapshot = json.loads(row["venue_snapshot"])
    venue = {"id": row["venue_id"], **snapshot}
    stored = json.loads(row["metrics_json"]) if row["metrics_json"] else {}

    return _payload(
        row["id"],
        venue,
        json.loads(row["config_json"]),
        {k: v for k, v in stored.items() if k not in ("metrics", "assessment")},
        trace_store.decode(row["trace_blob"]) if with_trace else None,
        density=json.loads(row["heatmap_json"]) if with_density and row["heatmap_json"] else None,
        metrics=stored.get("metrics"),
        assessment=stored.get("assessment"),
        bottlenecks=json.loads(row["bottlenecks_json"]) if row["bottlenecks_json"] else None,
        recommendations=(json.loads(row["recommendations_json"])
                         if row["recommendations_json"] else None),
        created_at=row["created_at"],
    )


@bp.get("/<int:simulation_id>")
def get_simulation(simulation_id: int):
    # Both are large. A caller that only wants the numbers can say so rather
    # than pulling a few hundred kilobytes it will throw away.
    return jsonify(load_run(
        simulation_id,
        with_trace=request.args.get("trace", "1") != "0",
        with_density=request.args.get("density", "1") != "0",
    ))


@bp.get("/<int:simulation_id>/proposal")
def get_proposal(simulation_id: int):
    """The venue with this run's buildable advice applied.

    Kept out of the run's own response because it is only wanted once somebody
    asks, and it costs a second layout inspection to produce.
    """
    run = load_run(simulation_id, with_trace=False, with_density=False)
    snapshot = run["venue_snapshot"]
    grid = Grid(snapshot["width"], snapshot["height"], snapshot["cells"])

    proposal = improve(grid, run.get("recommendations") or [])
    if proposal is None:
        return jsonify({
            "available": False,
            "reason": "Nothing in this run's advice is a change to the plan.",
        })

    venue = repository.get_venue(run["venue_id"]) if run.get("venue_id") else None
    base_name = venue["name"] if venue else "Venue"

    return jsonify({
        "available": True,
        "simulation_id": simulation_id,
        "venue_id": run.get("venue_id"),
        "suggested_name": f"{base_name} suggested",
        "config": run["config"],
        "before": snapshot,
        "after": {
            "width": proposal["width"],
            "height": proposal["height"],
            "cells": proposal["cells"],
        },
        "changed_cells": proposal["changed_cells"],
        "changes": proposal["changes"],
    })


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
             bottlenecks: list | None = None, recommendations: list | None = None,
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
    if bottlenecks is not None:
        payload["bottlenecks"] = bottlenecks
    if recommendations is not None:
        payload["recommendations"] = recommendations
    if assessment is not None:
        payload["assessment"] = assessment
    if trace is not None:
        payload["trace"] = trace
    if density is not None:
        payload["density"] = density
    if created_at:
        payload["created_at"] = created_at
    return payload
