"""Agents: who is in the room, where they start, and which way out they take.

Everything random here comes from one seeded generator, drawn in a fixed order.
Same venue, same config, same seed means the same crowd — which is what makes
two simulation results comparable at all (docs/decisions.md, D5).
"""

import random
from dataclasses import dataclass, field

from .grid import Grid, Point
from .pathfinding import astar, distance_field


@dataclass
class Agent:
    id: int
    x: int
    y: int
    speed: float
    exit_id: int | None
    path: list[Point] = field(default_factory=list)
    path_index: int = 0

    # Movement credit. Accrues each tick and is spent one cell at a time, so a
    # slowed agent takes several ticks to make a step it would otherwise make
    # in one. Capped at 1.0: nobody crosses more than one metre per tick.
    credit: float = 0.0

    tick_exited: int | None = None

    @property
    def position(self) -> Point:
        return (self.x, self.y)

    @property
    def has_left(self) -> bool:
        return self.tick_exited is not None

    @property
    def is_stranded(self) -> bool:
        """No route out. Counted separately from people who simply ran out of time."""
        return not self.path and not self.has_left

    def next_cell(self) -> Point | None:
        if self.path_index + 1 >= len(self.path):
            return None
        return self.path[self.path_index + 1]


def spawn_agents(grid: Grid, count: int, speed: float, cell_capacity: int,
                 rng: random.Random) -> list[Agent]:
    """Place `count` agents across the spawn cells, at most `cell_capacity` each.

    Every spawn cell contributes that many slots; the slots are shuffled once
    and the first `count` are taken. This spreads the crowd without clustering
    it at the top-left, and without needing a rejection loop that could run
    forever on a tight venue.
    """
    slots = [cell for cell in grid.spawn_cells for _ in range(cell_capacity)]
    if count > len(slots):
        raise ValueError(
            f"{count} agents will not fit: {len(grid.spawn_cells)} spawn cells "
            f"hold at most {len(slots)} at capacity {cell_capacity}"
        )

    rng.shuffle(slots)
    chosen = slots[:count]
    # Back to reading order so agent ids follow the layout rather than the
    # shuffle. Makes traces far easier to read when something looks wrong.
    chosen.sort(key=lambda cell: (cell[1], cell[0]))

    return [
        Agent(id=index, x=cell[0], y=cell[1], speed=speed, exit_id=None)
        for index, cell in enumerate(chosen)
    ]


def exit_distance_fields(grid: Grid) -> dict[int, dict[Point, int]]:
    """One distance field per doorway, keyed by exit id."""
    return {exit_.id: distance_field(grid, list(exit_.cells)) for exit_ in grid.exits}


def assign_exits(grid: Grid, agents: list[Agent], fields: dict[int, dict[Point, int]]) -> None:
    """Send everyone to their nearest exit, ties going to the lower exit id.

    This is the naive assignment: people head for the closest door and take no
    account of how busy it is. Making it congestion-aware is Day 9's job, and
    keeping the naive version around matters — it is the behaviour that
    produces the bottlenecks the tool is meant to find.
    """
    for agent in agents:
        best_id = None
        best_distance = None
        for exit_id, field_ in fields.items():
            distance = field_.get(agent.position)
            if distance is None:
                continue
            if best_distance is None or distance < best_distance:
                best_id, best_distance = exit_id, distance
        agent.exit_id = best_id


def plan_routes(grid: Grid, agents: list[Agent]) -> None:
    """Give every agent a path to its assigned exit.

    Agents are planned in id order, which is deterministic, and identical
    (start, exit) pairs share a cached path — in a dense spawn area most agents
    start on one of a few dozen cells, so this avoids repeating the same search
    hundreds of times.
    """
    by_exit = {exit_.id: exit_ for exit_ in grid.exits}
    cache: dict[tuple[Point, int], list[Point] | None] = {}

    for agent in agents:
        if agent.exit_id is None:
            agent.path = []
            continue
        key = (agent.position, agent.exit_id)
        if key not in cache:
            cache[key] = astar(grid, agent.position, by_exit[agent.exit_id].cells)
        path = cache[key]
        agent.path = list(path) if path else []
        agent.path_index = 0
