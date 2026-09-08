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

    # Consecutive ticks this agent wanted to move and could not. Drives
    # rerouting: someone standing still behind a jam is the signal that the
    # route they were given is no longer the best one available.
    blocked_ticks: int = 0
    last_reroute_tick: int = -10_000

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


def assign_exits(grid: Grid, agents: list[Agent], fields: dict[int, dict[Point, int]],
                 speed: float = 1.0, balanced: bool = False) -> None:
    """Choose a doorway for each agent.

    Two models, both defensible, and which one to use is a question about the
    venue rather than about the code:

    `nearest` — everyone walks to the closest door and takes no account of how
    busy it is. This is what an unsignposted crowd actually does, and it is the
    behaviour that produces the bottlenecks the tool exists to find. Default.

    `balanced` — people weigh the queue as well as the walk. Both terms are in
    ticks, so they are directly comparable, and they combine as a maximum
    rather than a sum: you leave when you have both arrived and cleared the
    queue, whichever happens later. Adding them would treat everyone assigned
    to a door as already standing at it, which panics about queues that drain
    long before most of the crowd gets there. This is the same reasoning as the
    free-flow baseline in docs/decisions.md, correction 1.

    It models a venue with marshals or clear signage, and running one layout
    both ways shows what better crowd management alone would be worth.

    Assignment is greedy in agent-id order. That order is fixed and so the
    result is reproducible — which matters here, because under the balanced
    model each choice changes the cost of the next one.
    """
    widths = {exit_.id: exit_.width for exit_ in grid.exits}
    planned = {exit_.id: 0 for exit_ in grid.exits}

    for agent in agents:
        best_id = None
        best_cost = None
        for exit_id, field_ in fields.items():
            distance = field_.get(agent.position)
            if distance is None:
                continue
            cost = distance / speed
            if balanced:
                # Ticks until everyone already heading here has been admitted,
                # at one per exit cell per tick. You leave at whichever comes
                # later: your arrival, or the queue draining.
                cost = max(cost, planned[exit_id] / widths[exit_id])
            if best_cost is None or cost < best_cost:
                best_id, best_cost = exit_id, cost
        agent.exit_id = best_id
        if best_id is not None:
            planned[best_id] += 1


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


class RoutePlanner:
    """Rebuilds routes mid-run for agents who have stopped making progress.

    Two things keep this affordable. A cooldown stops an agent replanning every
    tick it is stuck — without it, a jam of eighty people would trigger eighty
    A* searches a tick and the run would crawl. And a cache shared across a
    short window of ticks means the dozens of agents piled on the same few
    cells behind a bottleneck share one search rather than repeating it.

    The cache is keyed by epoch as well as position, so it expires on its own:
    a route computed while a corridor was full must not be handed out once the
    corridor has drained.
    """

    def __init__(self, grid: Grid, cost, epoch_length: int = 10):
        self.grid = grid
        self.cost = cost
        self.epoch_length = epoch_length
        self._cache: dict[tuple[Point, int, int], list[Point] | None] = {}
        self.searches = 0

    def route(self, position: Point, exit_id: int, tick: int) -> list[Point] | None:
        epoch = tick // self.epoch_length
        key = (position, exit_id, epoch)
        if key not in self._cache:
            goal = next(e for e in self.grid.exits if e.id == exit_id)
            self._cache[key] = astar(self.grid, position, goal.cells, cost=self.cost)
            self.searches += 1
            # An epoch's worth of entries is all that is ever read; dropping
            # the rest keeps this from growing across a 600-tick run.
            if len(self._cache) > 4000:
                self._cache = {k: v for k, v in self._cache.items() if k[2] == epoch}
        return self._cache[key]
