"""Layout inspection.

Day 2's validation checks that a venue is *well formed* — right number of cells,
sane dimensions. This checks whether it is *usable*: are there exits, is there a
crowd, and can the crowd actually reach a way out.

The distinction matters because a sealed room is a perfectly valid string. The
API accepts it; the simulation would just watch 150 people mill about for 600
ticks. Better to say so before anyone runs it.
"""

from .grid import Grid
from .pathfinding import distance_field


def inspect(grid: Grid) -> dict:
    """A report on whether this venue can be simulated, and what is wrong."""
    problems: list[dict] = []

    # Distances measured outwards from every exit at once. A spawn cell absent
    # from this field has no route to any exit.
    reach = distance_field(grid, grid.exit_cells)

    if not grid.exits:
        problems.append(
            _problem("NO_EXIT", "This venue has no exits, so nobody can leave.")
        )
    if not grid.spawn_cells:
        problems.append(
            _problem("NO_SPAWN", "This venue has no spawn area, so there is nobody to evacuate.")
        )

    stranded = [cell for cell in grid.spawn_cells if cell not in reach]
    if grid.exits and stranded:
        problems.append(
            _problem(
                "UNREACHABLE_SPAWN",
                f"{len(stranded)} spawn cell{'s' if len(stranded) != 1 else ''} "
                "cannot reach any exit. Check for a wall closing the route off.",
                cells=[list(cell) for cell in stranded],
            )
        )

    unusable = [
        exit_.id
        for exit_ in grid.exits
        if not _reachable_from_spawn(grid, exit_, reach)
    ]
    if unusable and len(unusable) < len(grid.exits):
        listed = ", ".join(str(i) for i in unusable)
        problems.append(
            _problem(
                "UNUSABLE_EXIT",
                f"Exit {listed} cannot be reached from the spawn area, so it will carry nobody.",
            )
        )

    walks = [reach[cell] for cell in grid.spawn_cells if cell in reach]

    return {
        "ok": not problems,
        "problems": problems,
        "exits": [
            {"id": e.id, "width": e.width, "cells": [list(c) for c in e.cells]}
            for e in grid.exits
        ],
        "total_exit_width": grid.total_exit_width,
        "spawn_cells": len(grid.spawn_cells),
        # The walking half of the free-flow baseline. The throughput half needs
        # an agent count, so it is computed at run time (see docs/decisions.md).
        "longest_walk": max(walks) if walks else None,
    }


def _reachable_from_spawn(grid: Grid, exit_, reach: dict) -> bool:
    """True if at least one spawn cell has a route to this exit."""
    if not grid.spawn_cells:
        return False
    from_exit = distance_field(grid, list(exit_.cells))
    return any(cell in from_exit for cell in grid.spawn_cells)


def _problem(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}
