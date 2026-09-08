"""Metrics.

Everything measurable about a run, in one place, before any judgement is
applied to it. The scorer reads from here; so will the recommendations. Keeping
measurement and opinion apart means the thresholds can be retuned without
touching the arithmetic.

All times are in ticks unless a field says seconds.
"""

from ..cells import WALKABLE
from ..config import Config
from ..engine.density import DENSITY_THRESHOLD
from ..engine.grid import Grid


def compute(grid: Grid, result, settings: dict, longest_walk: int | None) -> dict:
    """Fold a run into the numbers everything downstream reads."""
    walkable = sum(1 for cell in grid.cells if cell in WALKABLE)

    return {
        "crowd": _crowd(result),
        "time": _time(grid, result, settings, longest_walk),
        "congestion": _congestion(result, walkable),
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


def _congestion(result, walkable: int) -> dict:
    """How much of the room got tight, and for how long.

    Share and duration are kept apart on purpose. A quarter of the floor
    briefly touching the threshold is a different venue from one cell that
    stayed jammed for a minute, and averaging them together would hide both.
    """
    density = result.density
    peak = density["peak_density"]
    above = density["ticks_above_threshold"]

    crowded_cells = sum(1 for ticks in above if ticks)
    total_crowded_ticks = sum(above)
    ticks = max(1, len(result.trace) - 1)

    return {
        "threshold": DENSITY_THRESHOLD,
        "peak_density": round(max(peak), 2) if peak else 0.0,
        "crowded_cells": crowded_cells,
        "walkable_cells": walkable,
        "crowded_share": round(crowded_cells / walkable, 4) if walkable else 0.0,
        "longest_crowded_spell": max(above) if above else 0,
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
