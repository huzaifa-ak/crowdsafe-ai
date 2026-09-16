"""Metrics.

Everything measurable about a run, in one place, before any judgement is
applied to it. The scorer reads from here; so will the recommendations. Keeping
measurement and opinion apart means the thresholds can be retuned without
touching the arithmetic.

All times are in ticks unless a field says seconds.
"""

from ..cells import SPAWN, WALKABLE
from ..config import Config
from ..engine.density import DENSITY_THRESHOLD
from ..engine.grid import Grid

# How much of a run's length crowding may last and still count as the crowd
# dispersing from where it was placed rather than queueing.
DISPERSAL_FRACTION = 0.35


def compute(grid: Grid, result, settings: dict, longest_walk: int | None) -> dict:
    """Fold a run into the numbers everything downstream reads."""
    walkable = sum(1 for cell in grid.cells if cell in WALKABLE)

    return {
        "crowd": _crowd(result),
        "time": _time(grid, result, settings, longest_walk),
        "congestion": _congestion(grid, result, walkable),
        "exits": _exits(grid, result, settings),
        "trace": {"ticks": len(result.trace)},
    }


def _crowd(result) -> dict:
    return {
        "status": result.status,
        "agents": result.agent_count,
        "evacuated": result.evacuated,
        "stranded": result.stranded,
        "reroutes": result.reroutes,
    }


def _time(grid: Grid, result, settings: dict, longest_walk: int | None) -> dict:
    """Clearing time, and the two floors it should be read against.

    A raw clearing time means little on its own: twelve seconds is fine in a
    small room and remarkable in a large one. It needs a baseline, and the
    baseline is whichever of two limits binds — how long the walk takes, or how
    long the doors take to pass everybody. Neither alone is enough
    (docs/decisions.md, correction 1).
    """
    clearing = result.clearing_ticks
    walk_floor = (longest_walk or 0) / settings["speed"]
    door_floor = (
        result.agent_count / grid.total_exit_width if grid.total_exit_width else None
    )
    free_flow = max(walk_floor, door_floor) if door_floor else None

    return {
        "clearing_ticks": clearing,
        "clearing_seconds": round(clearing * Config.SECONDS_PER_TICK, 1) if clearing else None,
        "walk_floor_ticks": round(walk_floor, 1),
        "door_floor_ticks": round(door_floor, 1) if door_floor else None,
        "free_flow_ticks": round(free_flow, 1) if free_flow else None,
        "time_ratio": round(clearing / free_flow, 2) if clearing and free_flow else None,
        # Which limit binds is itself the finding. "Walking" means the layout
        # is the problem and a wider door buys almost nothing; "doors" means
        # the opposite. Recommendations turn on this.
        "binding_constraint": (
            None if not door_floor else ("doors" if door_floor >= walk_floor else "walking")
        ),
    }


def _congestion(grid: Grid, result, walkable: int) -> dict:
    """How much of the room got tight, and for how long.

    Share and duration are kept apart on purpose. A quarter of the floor
    briefly touching the threshold is a different venue from one cell that
    stayed jammed for a minute, and averaging them together would hide both.

    Crowding in the spawn area that is present from the first tick *and
    disperses* is excluded: that is the density the crowd was placed at, not
    congestion the venue caused, and counting it penalises a well laid out hall
    for having a crowd in it.

    Persistence is what separates the two, and it has to be part of the test.
    A spawn cell that is packed at tick 0 and clear a few seconds later is
    people spreading out. A spawn cell that is packed at tick 0 and still
    packed two thirds of the way through the run is a queue that happens to
    start where people were standing — which is exactly what a hall with one
    narrow door looks like. Excluding on spawn membership alone rated such a
    venue a B.

    The count of excluded cells is reported, so the exclusion can be checked
    rather than taken on trust.
    """
    density = result.density
    peak = density["peak_density"]
    above = density["ticks_above_threshold"]
    first = density.get("first_crowded_tick") or [-1] * len(above)
    last = density.get("last_crowded_tick") or [-1] * len(above)
    run_ticks = max(1, len(result.trace) - 1)

    placed = {
        i for i, ticks in enumerate(above)
        if ticks
        and grid.cells[i] == SPAWN
        and 0 <= first[i] <= 1
        and (last[i] - first[i]) <= DISPERSAL_FRACTION * run_ticks
    }

    crowded_indices = [i for i, ticks in enumerate(above) if ticks and i not in placed]
    crowded_cells = len(crowded_indices)
    total_crowded_ticks = sum(above[i] for i in crowded_indices)
    ticks = max(1, len(result.trace) - 1)

    return {
        "threshold": DENSITY_THRESHOLD,
        "peak_density": round(max(peak), 2) if peak else 0.0,
        "crowded_cells": crowded_cells,
        "walkable_cells": walkable,
        "crowded_share": round(crowded_cells / walkable, 4) if walkable else 0.0,
        "longest_crowded_spell": max((above[i] for i in crowded_indices), default=0),
        # Excluded as starting density, kept visible rather than silently dropped.
        "placed_dense_cells": len(placed),
        # Cell-ticks over the threshold as a fraction of every cell-tick
        # available. Low share with a high figure here means one place stayed
        # bad rather than many places briefly touching it.
        "crowded_intensity": round(total_crowded_ticks / (walkable * ticks), 5) if walkable else 0.0,
    }


def _exits(grid: Grid, result, settings: dict) -> dict:
    """Per-door usage, and how far that is from what the doors could carry.

    Share is compared against each door's share of the total width, not against
    an even split. A 3 m door beside a 1 m one *should* carry three quarters of
    the crowd; penalising that would be penalising the venue for working.
    """
    total_width = grid.total_exit_width
    evacuated = max(1, result.evacuated)

    doors = []
    worst_gap = 0.0
    for exit_ in grid.exits:
        used = result.exit_usage.get(exit_.id, 0)
        share = used / evacuated
        capacity_share = exit_.width / total_width if total_width else 0
        gap = share - capacity_share
        worst_gap = max(worst_gap, abs(gap))
        doors.append({
            "id": exit_.id,
            "width": exit_.width,
            "used": used,
            "share": round(share, 3),
            "capacity_share": round(capacity_share, 3),
            # Positive means this door carried more than its width justifies.
            "overload": round(gap, 3),
        })

    return {
        "total_width": total_width,
        "doors": doors,
        "imbalance": round(worst_gap, 3),
        "people_per_metre": round(result.agent_count / total_width, 1) if total_width else None,
    }
