"""The simulation.

One tick is 0.7 seconds and one cell is one metre, so an unobstructed agent
walks at about 1.4 m/s. Everything else — capacity, slowdown, exit throughput —
is expressed in those units, which is why the output can be read as people per
square metre and compared against real crowd-safety figures.

The loop is deliberately simple and sequential. Agents are processed in a
shuffled order each tick so that no one has a permanent advantage at a
doorway, and the shuffle comes from the run's seed so the order is the same
every time.
"""

import random
from dataclasses import dataclass, field

from .agents import Agent, assign_exits, exit_distance_fields, plan_routes, spawn_agents
from .density import DensityAccumulator
from .grid import Grid

# How much a crowded destination slows an approach. An empty cell costs nothing;
# a nearly full one takes several ticks to enter. Never zero, or an agent facing
# a busy cell would wait forever instead of eventually squeezing in.
MIN_SLOW_FACTOR = 0.2

# One agent per exit cell per tick, so a 3 m door passes three people per 0.7 s
# — about 1.4 people per metre per second, which is roughly what a real doorway
# manages (D6).
EXIT_THROUGHPUT_PER_CELL = 1

# Ticks with nobody moving and nobody leaving before the run is called stuck.
# Long enough that a brief jam at a door does not trip it, short enough that a
# genuine deadlock does not burn the whole tick budget.
STALL_TICKS = 25


@dataclass
class SimulationConfig:
    num_agents: int = 150
    speed: float = 1.0
    cell_capacity: int = 3
    max_ticks: int = 600
    seed: int = 42
    entrances_are_exits: bool = False

    def as_dict(self) -> dict:
        return {
            "num_agents": self.num_agents,
            "speed": self.speed,
            "cell_capacity": self.cell_capacity,
            "max_ticks": self.max_ticks,
            "seed": self.seed,
            "entrances_are_exits": self.entrances_are_exits,
        }


@dataclass
class SimulationResult:
    status: str                      # complete | timeout | stalled
    ticks: int
    agent_count: int
    evacuated: int
    stranded: int
    exit_usage: dict[int, int]
    exit_ticks: list[int | None]     # per agent, in id order
    trace: list[list[int]] = field(default_factory=list)
    density: dict = field(default_factory=dict)

    @property
    def clearing_ticks(self) -> int | None:
        """Tick on which the last person left, or None if some never did."""
        if self.evacuated < self.agent_count - self.stranded:
            return None
        left = [t for t in self.exit_ticks if t is not None]
        return max(left) if left else None


class Simulation:
    def __init__(self, grid: Grid, config: SimulationConfig):
        self.grid = grid
        self.config = config
        self.rng = random.Random(config.seed)

        self.agents = spawn_agents(
            grid, config.num_agents, config.speed, config.cell_capacity, self.rng
        )
        fields = exit_distance_fields(grid)
        assign_exits(grid, self.agents, fields)
        plan_routes(grid, self.agents)

        # Occupancy as a flat array indexed the same way as the cell string.
        # A dict would be tidier; this is read and written several thousand
        # times a tick and the indexing arithmetic is cheaper.
        self.occupancy = [0] * (grid.width * grid.height)
        for agent in self.agents:
            self.occupancy[self._index(agent.x, agent.y)] += 1

        self.density = DensityAccumulator(grid)
        # Indices of cells holding somebody. Maintained as agents move rather
        # than rebuilt each tick, so the density accumulator never has to scan
        # the grid to find out where people are.
        self.occupied: set[int] = {
            self._index(a.x, a.y) for a in self.agents
        }

        self.exit_cells = {cell for exit_ in grid.exits for cell in exit_.cells}
        self.exit_usage = {exit_.id: 0 for exit_ in grid.exits}
        self.trace: list[list[int]] = []

        self.tick = 0
        self.evacuated = 0
        self._quiet_ticks = 0

    # ------------------------------------------------------------------ #

    def _index(self, x: int, y: int) -> int:
        return y * self.grid.width + x

    def _slow_factor(self, cell) -> float:
        """How much the crowd already in `cell` slows an agent entering it."""
        occupied = self.occupancy[self._index(*cell)]
        return max(MIN_SLOW_FACTOR, 1.0 - occupied / self.config.cell_capacity)

    def active_agents(self) -> list[Agent]:
        return [a for a in self.agents if not a.has_left and not a.is_stranded]

    # ------------------------------------------------------------------ #

    def run(self) -> SimulationResult:
        stranded = sum(1 for a in self.agents if a.is_stranded)
        evacuable = len(self.agents) - stranded

        self._record_trace()

        # Nobody can get out: finish immediately rather than idling for 600 ticks.
        if evacuable == 0:
            return self._result("stalled" if stranded else "complete", stranded)

        status = "timeout"
        while self.tick < self.config.max_ticks:
            if self.evacuated >= evacuable:
                status = "complete"
                break

            self.tick += 1
            moved = self.step()
            self._record_tick()

            if moved:
                self._quiet_ticks = 0
            else:
                self._quiet_ticks += 1
                if self._quiet_ticks >= STALL_TICKS:
                    status = "stalled"
                    break
        else:
            if self.evacuated >= evacuable:
                status = "complete"

        return self._result(status, stranded)

    def _result(self, status: str, stranded: int) -> SimulationResult:
        return SimulationResult(
            status=status,
            ticks=self.tick,
            agent_count=len(self.agents),
            evacuated=self.evacuated,
            stranded=stranded,
            exit_usage=dict(self.exit_usage),
            exit_ticks=[a.tick_exited for a in self.agents],
            trace=self.trace,
            density=self.density.as_dict(),
        )

    def step(self) -> bool:
        """Advance one tick. Returns True if anything happened.

        Each exit cell admits one agent per tick — the flow cap that makes
        doorways bottleneck (D6). The budget is refilled here, at the start of
        every tick.
        """
        admissions = {cell: EXIT_THROUGHPUT_PER_CELL for cell in self.exit_cells}

        order = self.active_agents()
        self.rng.shuffle(order)

        something_happened = False

        for agent in order:
            target = agent.next_cell()
            if target is None:
                continue

            agent.credit = min(1.0, agent.credit + agent.speed * self._slow_factor(target))
            if agent.credit < 1.0:
                continue

            if target in self.exit_cells:
                if admissions[target] <= 0:
                    continue
                admissions[target] -= 1
                self._leave(agent, target)
                something_happened = True
                continue

            if self.occupancy[self._index(*target)] >= self.config.cell_capacity:
                continue

            self._move(agent, target)
            something_happened = True

        return something_happened

    def _move(self, agent: Agent, target) -> None:
        self._set_occupancy(self._index(agent.x, agent.y), -1)
        self._set_occupancy(self._index(*target), 1)
        agent.x, agent.y = target
        agent.path_index += 1
        agent.credit -= 1.0

    def _leave(self, agent: Agent, target) -> None:
        self._set_occupancy(self._index(agent.x, agent.y), -1)
        agent.x, agent.y = target
        agent.credit -= 1.0
        agent.tick_exited = self.tick
        self.evacuated += 1

        exit_ = self.grid.exit_for_cell(target)
        if exit_ is not None:
            self.exit_usage[exit_.id] += 1

    def _set_occupancy(self, index: int, delta: int) -> None:
        value = self.occupancy[index] + delta
        self.occupancy[index] = value
        if value:
            self.occupied.add(index)
        else:
            self.occupied.discard(index)

    def _record_tick(self) -> None:
        self._record_trace()
        self.density.record(self.occupancy, list(self.occupied))

    def _record_trace(self) -> None:
        """One flat list of coordinates per tick.

        No identities: playback draws dots, and metrics are computed here rather
        than in the browser, so carrying agent ids would double the size of the
        trace for nothing.
        """
        positions: list[int] = []
        for agent in self.agents:
            if agent.has_left:
                continue
            positions.append(agent.x)
            positions.append(agent.y)
        self.trace.append(positions)


def simulate(grid: Grid, config: SimulationConfig) -> SimulationResult:
    return Simulation(grid, config).run()
