"""Bottlenecks.

The heatmap shows where crowding happened. This turns that into findings a
person can act on: contiguous regions, ranked by how bad they were, each with a
location and a description of what kind of place it is.

The distinction matters because "37% of your floor exceeded 2 people per m²" is
a fact, not an instruction. "The 2 m gap between the barrier and the north wall
held 2.8 people per m² for 46 ticks, 9 m from exit 1" is something you can walk
over to and change.
"""

from ..cells import WALKABLE
from ..engine.grid import NEIGHBOUR_OFFSETS, Grid
from ..engine.pathfinding import distance_field

# Regions smaller than this are noise — a single cell that briefly tipped over
# the threshold is not a bottleneck, it is one person pausing.
MIN_REGION_CELLS = 3

# A passage this wide or narrower is a pinch rather than open floor.
PINCH_WIDTH = 3

# Within this many steps of a door, congestion is the door's queue rather than
# a separate feature of the layout.
EXIT_APPROACH_STEPS = 3

MAX_FINDINGS = 5


def detect(grid: Grid, density: dict, limit: int = MAX_FINDINGS) -> list[dict]:
    """Crowded regions, worst first."""
    above = density["ticks_above_threshold"]
    peak = density["peak_density"]

    crowded = {i for i, ticks in enumerate(above) if ticks}
    if not crowded:
        return []

    to_exit = distance_field(grid, grid.exit_cells)
    regions = _components(grid, crowded)

    findings = []
    for cells in regions:
        if len(cells) < MIN_REGION_CELLS:
            continue
        findings.append(_describe(grid, cells, above, peak, to_exit, density))

    findings.sort(key=lambda f: f["severity"], reverse=True)
    for rank, finding in enumerate(findings[:limit], start=1):
        finding["id"] = rank
    return findings[:limit]


def _components(grid: Grid, crowded: set[int]) -> list[list[int]]:
    """Connected groups of crowded cells, four-connected like movement itself."""
    remaining = set(crowded)
    groups = []
    while remaining:
        start = min(remaining)
        stack = [start]
        remaining.discard(start)
        group = []
        while stack:
            index = stack.pop()
            group.append(index)
            x, y = index % grid.width, index // grid.width
            for dx, dy in NEIGHBOUR_OFFSETS:
                neighbour = (y + dy) * grid.width + (x + dx)
                if 0 <= x + dx < grid.width and 0 <= y + dy < grid.height:
                    if neighbour in remaining:
                        remaining.discard(neighbour)
                        stack.append(neighbour)
        groups.append(group)
    return groups


def _passage_width(grid: Grid, x: int, y: int) -> int:
    """How wide the free space is through this cell, at its narrowest.

    Measured as contiguous walkable cells horizontally and vertically; the
    smaller of the two is how wide the passage really is. A cell in the middle
    of a hall scores large in both directions; a cell in a doorway scores one.
    """
    def run(dx: int, dy: int) -> int:
        length = 1
        for direction in (1, -1):
            step = 1
            while True:
                nx, ny = x + dx * step * direction, y + dy * step * direction
                if not grid.is_walkable(nx, ny):
                    break
                length += 1
                step += 1
        return length

    return min(run(1, 0), run(0, 1))


def _describe(grid: Grid, cells: list[int], above: list[int], peak: list[float],
              to_exit: dict, density: dict) -> dict:
    width = grid.width
    points = [(i % width, i // width) for i in cells]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    centre = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))

    worst_index = max(cells, key=lambda i: above[i])
    worst_point = (worst_index % width, worst_index // width)

    crowded_ticks = sum(above[i] for i in cells)
    longest_spell = max(above[i] for i in cells)
    peak_density = max(peak[i] for i in cells)

    # The tightest cell, not the average one. A region usually spans the
    # constriction *and* the crowd backed up behind it, and the centroid lands
    # in the queue — which is a symptom. The narrow point is the cause, and
    # that is the coordinate worth reporting.
    widths = [(_passage_width(grid, x, y), (x, y)) for x, y in points]
    narrowest, pinch_at = min(widths)
    exit_distance = min((to_exit.get(p) for p in points if p in to_exit), default=None)
    nearest_exit = _nearest_exit(grid, points)

    if exit_distance is not None and exit_distance <= EXIT_APPROACH_STEPS:
        kind = "exit_approach"
    elif narrowest <= PINCH_WIDTH:
        kind = "pinch"
    else:
        kind = "open"

    return {
        "cells": sorted(cells),
        "size": len(cells),
        "centre": list(centre),
        "worst_cell": list(worst_point),
        "bounds": {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)},
        "peak_density": round(peak_density, 2),
        "longest_spell": longest_spell,
        "crowded_ticks": crowded_ticks,
        "passage_width": narrowest,
        "pinch_at": list(pinch_at),
        "exit_distance": exit_distance,
        "nearest_exit": nearest_exit,
        "kind": kind,
        # Cell-ticks over the threshold. A big area that was briefly tight and a
        # small one that stayed jammed can score alike, which is right — both
        # cost the same amount of human time standing still.
        "severity": crowded_ticks,
        "where": _where(grid, centre),
        "label": _label(kind, narrowest, nearest_exit, exit_distance,
                        _where(grid, pinch_at if kind == "pinch" else centre)),
        "detail": _detail(peak_density, longest_spell, len(cells), density["threshold"]),
    }


def _nearest_exit(grid: Grid, points: list[tuple[int, int]]) -> int | None:
    best_id, best = None, None
    for exit_ in grid.exits:
        field = distance_field(grid, list(exit_.cells))
        reachable = [field[p] for p in points if p in field]
        if not reachable:
            continue
        closest = min(reachable)
        if best is None or closest < best:
            best_id, best = exit_.id, closest
    return best_id


def _where(grid: Grid, centre: tuple[int, int]) -> str:
    """A rough compass position, so a finding can be found on the plan."""
    x, y = centre
    vertical = ""
    horizontal = ""
    if y < grid.height / 3:
        vertical = "north"
    elif y > grid.height * 2 / 3:
        vertical = "south"
    if x < grid.width / 3:
        horizontal = "west"
    elif x > grid.width * 2 / 3:
        horizontal = "east"

    if vertical and horizontal:
        return f"{vertical}-{horizontal}"
    return vertical or horizontal or "centre"


def _label(kind: str, narrowest: int, nearest_exit: int | None,
           exit_distance: int | None, where: str) -> str:
    if kind == "exit_approach":
        return f"Queue at exit {nearest_exit}"
    if kind == "pinch":
        gap = f"{narrowest} m gap" if narrowest > 1 else "1 m gap"
        return f"{gap} in the {where} of the plan"
    return f"Open floor in the {where} of the plan"


def _detail(peak_density: float, longest_spell: int, size: int, threshold: float) -> str:
    area = f"{size} m²"
    return (
        f"{area} reached {peak_density} people per m² and stayed above "
        f"{threshold} for up to {longest_spell} ticks."
    )
