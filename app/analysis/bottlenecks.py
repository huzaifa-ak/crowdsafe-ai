"""Bottlenecks.

The heatmap shows where crowding happened. This turns that into findings a
person can act on: contiguous regions, ranked by how bad they were, each with a
location and a description of what kind of place it is.

The distinction matters because "37% of your floor exceeded 2 people per m²" is
a fact, not an instruction. "The 2 m gap between the barrier and the north wall
held 2.8 people per m² for 46 ticks, 9 m from exit 1" is something you can walk
over to and change.
"""

from ..cells import SPAWN
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

# Most of a region's cells being spawn cells, with crowding present from the
# first tick, means the crowd was placed that densely rather than arriving that
# densely.
SPAWN_MAJORITY = 0.5


def detect(grid: Grid, density: dict, limit: int = MAX_FINDINGS,
           mode: str = "evacuation") -> list[dict]:
    """Crowded regions, worst first.

    An arrival is measured against the entrances: a queue builds on the way in
    rather than on the way out, and calling it a queue at an exit would point
    at the wrong door.
    """
    above = density["ticks_above_threshold"]
    peak = density["peak_density"]

    crowded = {i for i, ticks in enumerate(above) if ticks}
    if not crowded:
        return []

    arriving = mode == "arrival"
    doorways = grid.entrances if arriving else grid.exits
    door_cells = grid.entrance_cells if arriving else grid.exit_cells
    door_word = "entrance" if arriving else "exit"
    to_exit = distance_field(grid, door_cells)
    regions = _components(grid, crowded)

    total_ticks = max(1, max(density.get("last_crowded_tick") or [1]))

    findings = []
    for cells in regions:
        if len(cells) < MIN_REGION_CELLS:
            continue
        findings.append(_describe(grid, cells, above, peak, to_exit, density,
                                  total_ticks, doorways, door_word))

    # Starting density is reported but never outranks a real bottleneck. It is
    # a fact about how many people were placed where, not about the layout, and
    # letting it top the list buries the findings that can be acted on.
    findings.sort(key=lambda f: (f["kind"] != "spawn_density", f["severity"]), reverse=True)
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
              to_exit: dict, density: dict, total_ticks: int,
              doorways, door_word: str) -> dict:
    width = grid.width
    points = [(i % width, i // width) for i in cells]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    centre = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))

    worst_index = max(cells, key=lambda i: above[i])
    worst_point = (worst_index % width, worst_index // width)

    crowded_ticks = sum(above[i] for i in cells)
    # Person-ticks spent in the region. Unlike severity this counts everyone
    # who passed through, not just time over the threshold, which is what makes
    # it usable as "how much human time this area consumed".
    person_ticks = sum(density["visits"][i] for i in cells)
    longest_spell = max(above[i] for i in cells)
    peak_density = max(peak[i] for i in cells)

    # The tightest cell, not the average one. A region usually spans the
    # constriction *and* the crowd backed up behind it, and the centroid lands
    # in the queue — which is a symptom. The narrow point is the cause, and
    # that is the coordinate worth reporting.
    widths = [(_passage_width(grid, x, y), (x, y)) for x, y in points]
    narrowest, pinch_at = min(widths)
    exit_distance = min((to_exit.get(p) for p in points if p in to_exit), default=None)
    nearest_exit = _nearest_exit(doorways, grid, points)

    first = [density["first_crowded_tick"][i] for i in cells if above[i]]
    last = [density["last_crowded_tick"][i] for i in cells if above[i]]
    started = min(first) if first else 0
    ended = max(last) if last else 0
    on_spawn = sum(1 for x, y in points if grid.at(x, y) == SPAWN) / len(points)

    # Crowding that is there from the first tick, sits on the spawn area, and
    # clears as people disperse is the crowd's starting density. It is worth
    # saying, but it is not a bottleneck: it describes how many people were put
    # in the room, not how the room behaves.
    starts_packed = started <= 1 and on_spawn > SPAWN_MAJORITY

    # Ordered by how specific the explanation is, not by how the region looks.
    # A queue at a door and a constriction are both explanations of *why* the
    # crowding happened; starting density is only an explanation when neither
    # of those applies. Testing it first would swallow a genuine pinch that
    # happens to sit across the spawn area — which is common, because that is
    # where the crowd is.
    if exit_distance is not None and exit_distance <= EXIT_APPROACH_STEPS:
        kind = "exit_approach"
    elif narrowest <= PINCH_WIDTH:
        kind = "pinch"
    elif starts_packed:
        kind = "spawn_density"
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
        "person_ticks": person_ticks,
        "passage_width": narrowest,
        "pinch_at": list(pinch_at),
        "exit_distance": exit_distance,
        "nearest_exit": nearest_exit,
        "kind": kind,
        "first_tick": started,
        "last_tick": ended,
        "on_spawn": round(on_spawn, 2),
        # Cell-ticks over the threshold. A big area that was briefly tight and a
        # small one that stayed jammed can score alike, which is right — both
        # cost the same amount of human time standing still.
        "severity": crowded_ticks,
        "where": _where(grid, centre),
        "label": _label(kind, narrowest, nearest_exit, exit_distance,
                        _where(grid, pinch_at if kind == "pinch" else centre),
                        door_word),
        "detail": _detail(peak_density, longest_spell, len(cells),
                          density["threshold"], kind),
    }


def _nearest_exit(doorways, grid: Grid, points: list[tuple[int, int]]) -> int | None:
    best_id, best = None, None
    for exit_ in doorways:
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
           exit_distance: int | None, where: str, door_word: str = "exit") -> str:
    if kind == "spawn_density":
        return f"Crowd starts packed in the {where}"
    
    if kind == "exit_approach":
        return f"Queue at {door_word} {nearest_exit}"
    if kind == "pinch":
        return f"{narrowest} m gap in the {where} of the plan"
    # "Open floor" said where but not what. Naming the nearest door gives the
    # finding something to be next to.
    if nearest_exit is not None and exit_distance is not None:
        return f"Crush in the {where}, {exit_distance} m from {door_word} {nearest_exit}"
    return f"Crush in the {where} of the plan"


def _detail(peak_density: float, longest_spell: int, size: int, threshold: float,
            kind: str) -> str:
    measured = (
        f"{size} m² reached {peak_density} people per m² and stayed above "
        f"{threshold} for up to {longest_spell} ticks"
    )
    if kind == "spawn_density":
        return measured + ". This is the density people were placed at, not congestion."
    return measured + "."
