"""Pathfinding.

Two things live here. `distance_field` answers "how far is every cell from the
nearest exit", which is used for reachability checks and for the free-flow
baseline. `astar` finds one agent's route, and takes an optional cost function
so that Day 9 can make crowded cells expensive without changing the search.

Determinism is a hard requirement (see docs/decisions.md, D5). Two runs of the
same venue with the same seed must produce byte-identical results, so every
tie here is broken explicitly rather than left to whatever order a heap or a
set happens to produce.
"""

import heapq
from collections import deque

from .grid import NEIGHBOUR_OFFSETS, Grid, Point


def distance_field(grid: Grid, sources: list[Point]) -> dict[Point, int]:
    """Steps from the nearest source to every reachable walkable cell.

    Multi-source BFS: seeding the queue with every source at once gives the
    distance to the *nearest* one in a single pass, rather than one search per
    source and a minimum afterwards.
    """
    distances: dict[Point, int] = {}
    queue: deque[Point] = deque()

    for source in sources:
        if grid.is_walkable(*source) and source not in distances:
            distances[source] = 0
            queue.append(source)

    while queue:
        x, y = queue.popleft()
        next_distance = distances[(x, y)] + 1
        for dx, dy in NEIGHBOUR_OFFSETS:
            neighbour = (x + dx, y + dy)
            if neighbour in distances:
                continue
            if not grid.is_walkable(*neighbour):
                continue
            distances[neighbour] = next_distance
            queue.append(neighbour)

    return distances


def exit_distance_field(grid: Grid) -> dict[Point, int]:
    """Steps to the nearest exit cell, for every cell that can reach one."""
    return distance_field(grid, grid.exit_cells)


def manhattan(a: Point, b: Point) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(grid: Grid, start: Point, goals, cost=None) -> list[Point] | None:
    """Cheapest path from `start` to any cell in `goals`, or None if unreachable.

    `cost` is called as cost(x, y) and returns what it costs to *enter* that
    cell; it must never return less than 1 or the heuristic stops being
    admissible and the path stops being optimal. Left as None, every step costs
    1 and this is plain shortest-path.
    """
    goal_set = frozenset(goals)
    if not goal_set:
        return None
    if start in goal_set:
        return [start]

    def heuristic(point: Point) -> int:
        # Manhattan is admissible for four-neighbour movement with unit cost:
        # it can never overestimate, because diagonal shortcuts do not exist.
        return min(manhattan(point, goal) for goal in goal_set)

    # The counter breaks f-score ties by insertion order. Without it, heapq
    # would fall through to comparing the point tuples, which is arbitrary but
    # worse: it silently biases the search towards low coordinates, and any
    # payload that is not comparable raises instead.
    counter = 0
    open_heap: list[tuple[int, int, Point]] = [(heuristic(start), counter, start)]
    came_from: dict[Point, Point] = {}
    best_cost: dict[Point, int] = {start: 0}
    closed: set[Point] = set()

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current in goal_set:
            return _reconstruct(came_from, current)
        closed.add(current)

        x, y = current
        for dx, dy in NEIGHBOUR_OFFSETS:
            neighbour = (x + dx, y + dy)
            if neighbour in closed or not grid.is_walkable(*neighbour):
                continue
            step = cost(*neighbour) if cost else 1
            tentative = best_cost[current] + step
            if tentative >= best_cost.get(neighbour, float("inf")):
                continue
            came_from[neighbour] = current
            best_cost[neighbour] = tentative
            counter += 1
            heapq.heappush(open_heap, (tentative + heuristic(neighbour), counter, neighbour))

    return None


def _reconstruct(came_from: dict[Point, Point], end: Point) -> list[Point]:
    path = [end]
    while path[-1] in came_from:
        path.append(came_from[path[-1]])
    path.reverse()
    return path
