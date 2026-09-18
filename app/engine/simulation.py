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

from .agents import (
    Agent, RoutePlanner, arrival_targets, assign_entrances, assign_exits,
    exit_distance_fields, places_in, plan_routes, spawn_agents,
)
from .pathfinding import astar, distance_field
from ..cells import SPAWN
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

# Rerouting. An agent that has been unable to move for this many consecutive
# ticks is standing behind something that is not clearing, and is worth
# replanning. Low enough to react within a few seconds of simulated time, high
# enough that ordinary shuffling at a doorway does not trigger it.
REROUTE_AFTER_BLOCKED_TICKS = 8

# Minimum gap between one agent's reroutes. Without it a persistent jam makes
# every agent in it replan every tick, and the search cost swamps the run.
REROUTE_COOLDOWN_TICKS = 20

# What a crowded cell costs to walk into, relative to an empty one. At 4, a
# full cell costs five steps, so an agent will accept a detour of up to four
# cells to get round a queue — but not an arbitrarily long one.
OCCUPANCY_COST_WEIGHT = 4.0

# How much better another door must look before an agent switches to it.
# Without a margin, two similar doors make people oscillate.
EXIT_SWITCH_MARGIN_TICKS = 10

# Arrival only. Ticks of being unable to move before someone stops trying to
# reach a place and simply stands where they are. People do this in a full
# venue, and it is worth reporting rather than hiding: standing in a
# circulation route is a finding.
GIVE_UP_TICKS = 30

# One person per checkpoint cell per tick, the same rate as a doorway. A real
# ticket scan is quicker than that and a bag search much slower; one per cell
# keeps a checkpoint comparable with the doors either side of it, which is the
# comparison that matters when deciding how many lanes to open.
CHECKPOINT_THROUGHPUT_PER_CELL = 1

# What a checkpoint cell costs to walk through for somebody who does not need
# checking. Checkpoint cells are walkable — a lane has to be enterable — but
# nobody without a ticket to show has any business in one, and a route straight
# through the security line both looks wrong and inflates the congestion
# measured there. High rather than infinite: if the only way to a place runs
# through the lane, walking through it beats standing still forever.
CHECKPOINT_DETOUR_COST = 40.0

# How much of a checkpoint queue is allowed inside the building, expressed as
# the number of ticks' worth of processing it represents. Past this, arrivals
# are held outside.
#
# Without it a wide entrance feeding a narrow checkpoint gridlocks: people are
# admitted several times faster than they can be processed, the foyer packs
# solid at capacity, and nobody can move at all — not even the person at the
# front of the queue. That is a real failure mode and real venues avoid it the
# same way, by holding the crowd outside rather than letting the concourse
# fill. Modelling the holding is more useful than modelling the gridlock,
# because a stalled run reports nothing.
# Twenty was chosen by sweeping it against a foyer with one, two, four and
# eight lanes at every ticket share. Above about twenty-five the concourse
# packs solid and two lanes gridlock where one lane does not, which is the
# clearest sign the number is too generous: more capacity should never produce
# a worse outcome.
QUEUE_HOLD_TICKS = 20

# Ticks with nobody moving and nobody leaving before the run is called stuck.
# Long enough that a brief jam at a door does not trip it, short enough that a
# genuine deadlock does not burn the whole tick budget.
STALL_TICKS = 25


@dataclass
class SimulationConfig:
    # "evacuation" empties a full venue through its exits. "arrival" fills an
    # empty one through its entrances. They are different questions and are
    # measured differently; see app/analysis/metrics.py.
    mode: str = "evacuation"
    num_agents: int = 150
    speed: float = 1.0
    cell_capacity: int = 3
    max_ticks: int = 600
    seed: int = 42
    entrances_are_exits: bool = False

    # How many of the crowd are VIPs, with places in the restricted area
    # behind a checkpoint. Arrival only: on the way out everybody is the same
    # and the checkpoints are just floor.
    vip_count: int = 0

    # "nearest" or "balanced" — see assign_exits.
    routing: str = "nearest"
    # Whether people go round a jam once they realise they are stuck in one.
    reroute: bool = True

    def as_dict(self) -> dict:
        return {
            "num_agents": self.num_agents,
            "speed": self.speed,
            "cell_capacity": self.cell_capacity,
            "max_ticks": self.max_ticks,
            "seed": self.seed,
            "entrances_are_exits": self.entrances_are_exits,
            "routing": self.routing,
            "reroute": self.reroute,
            "mode": self.mode,
            "vip_count": self.vip_count,
        }


@dataclass
class SimulationResult:
    mode: str                        # evacuation | arrival
    status: str                      # complete | timeout | stalled
    ticks: int
    agent_count: int
    evacuated: int
    stranded: int
    exit_usage: dict[int, int]
    exit_ticks: list[int | None]     # per agent, in id order
    entrance_usage: dict[int, int] = field(default_factory=dict)
    checkpoint_usage: dict[int, int] = field(default_factory=dict)
    vip_count: int = 0
    vip_clearing_ticks: int | None = None
    # Arrival only: people who never reached a place and stopped in a
    # circulation route instead.
    stopped_short: int = 0
    reroutes: int = 0
    searches: int = 0
    trace: list[list[int]] = field(default_factory=list)
    density: dict = field(default_factory=dict)

    @property
    def clearing_ticks(self) -> int | None:
        """Tick on which the last person finished their journey.

        Leaving, in an evacuation. Reaching their place, in an arrival. None if
        some never did.
        """
        if self.evacuated < self.agent_count - self.stranded:
            return None
        done = [t for t in self.exit_ticks if t is not None]
        return max(done) if done else None


class Simulation:
    def __init__(self, grid: Grid, config: SimulationConfig):
        self.grid = grid
        self.config = config
        self.rng = random.Random(config.seed)

        self.agents = spawn_agents(
            grid, config.num_agents, config.speed, config.cell_capacity, self.rng
        )
        self.fields = exit_distance_fields(grid)
        assign_exits(grid, self.agents, self.fields, speed=config.speed,
                     balanced=config.routing == "balanced")
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

        # How many people are still heading for each door. This is the queue
        # that matters: the cells immediately inside a doorway hold at most a
        # handful of people, so measuring congestion there makes a queue of a
        # hundred look no worse than a queue of three.
        self.heading_for = {exit_.id: 0 for exit_ in grid.exits}
        for agent in self.agents:
            if agent.exit_id is not None and not agent.is_stranded:
                self.heading_for[agent.exit_id] += 1
        self.exit_usage = {exit_.id: 0 for exit_ in grid.exits}
        self.trace: list[list[int]] = []

        self.planner = RoutePlanner(grid, self._cell_cost)
        self.reroutes = 0

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

    def _cell_cost(self, x: int, y: int) -> float:
        """What it costs to walk into this cell, in step-equivalents.

        Never below 1: A*'s heuristic is only admissible while every step costs
        at least one, and an underpriced step would make the path it returns
        no longer the cheapest one.
        """
        occupied = self.occupancy[self._index(x, y)]
        return 1.0 + OCCUPANCY_COST_WEIGHT * occupied / self.config.cell_capacity

    def _should_reroute(self, agent: Agent) -> bool:
        if not self.config.reroute:
            return False
        if agent.blocked_ticks < REROUTE_AFTER_BLOCKED_TICKS:
            return False
        return self.tick - agent.last_reroute_tick >= REROUTE_COOLDOWN_TICKS

    def _reroute(self, agent: Agent) -> None:
        """Replan around the congestion, and reconsider which door to head for.

        The exit choice is re-made with a margin: a door has to be clearly
        better, not marginally better, or agents flip between two doors every
        cooldown and nobody gets anywhere. The margin is what stops that.
        """
        agent.last_reroute_tick = self.tick
        agent.blocked_ticks = 0

        target = self._best_exit_now(agent)
        path = self.planner.route(agent.position, target, self.tick)

        # An occupancy-aware search can fail where a plain one would not: the
        # only way through may be full at this instant. Keeping the old path
        # means the agent waits rather than giving up.
        if not path or len(path) < 2:
            return

        if target != agent.exit_id:
            self.heading_for[agent.exit_id] -= 1
            self.heading_for[target] += 1
        agent.exit_id = target
        agent.path = path
        agent.path_index = 0
        self.reroutes += 1

    def _best_exit_now(self, agent: Agent) -> int:
        """Estimated ticks to get out by each door: the walk, plus the wait.

        The wait is the number of people still heading for that door divided by
        its width — how long until the last of them is through. It combines
        with the walk as a maximum, not a sum: you leave once you have both
        arrived and outlasted the queue. Adding them would treat a queue that
        drains before you arrive as though you had to stand in it.

        Because the count updates the moment an agent switches, this
        self-limits: the first people to abandon a jammed door make the
        alternative less attractive for those behind them, and the crowd
        settles into a split rather than stampeding across en masse.
        """
        current = agent.exit_id
        if len(self.grid.exits) < 2:
            return current

        best_id, best_cost = current, None
        for exit_ in self.grid.exits:
            distance = self.fields[exit_.id].get(agent.position)
            if distance is None:
                continue
            cost = max(distance / self.config.speed,
                       self.heading_for[exit_.id] / exit_.width)
            if exit_.id == current:
                # Switching has to be clearly better, not marginally better.
                # Without hysteresis two similar doors make people oscillate.
                cost -= EXIT_SWITCH_MARGIN_TICKS
            if best_cost is None or cost < best_cost:
                best_id, best_cost = exit_.id, cost
        return best_id

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

    def _vip_clearing_ticks(self) -> int | None:
        """Tick by which every ticketed arrival had been through a checkpoint."""
        ticks = [a.tick_cleared for a in self.agents if a.is_vip and a.tick_cleared]
        return max(ticks) if ticks else None

    def _result(self, status: str, stranded: int) -> SimulationResult:
        return SimulationResult(
            mode=self.config.mode,
            status=status,
            ticks=self.tick,
            agent_count=len(self.agents),
            evacuated=self.evacuated,
            stranded=stranded,
            exit_usage=dict(self.exit_usage),
            exit_ticks=[a.tick_exited for a in self.agents],
            entrance_usage=dict(getattr(self, "entrance_usage", {})),
            checkpoint_usage=dict(getattr(self, "checkpoint_usage", {})),
            vip_count=sum(1 for a in self.agents if a.is_vip),
            vip_clearing_ticks=self._vip_clearing_ticks(),
            stopped_short=getattr(self, "stopped_short", 0),
            reroutes=self.reroutes,
            searches=self.planner.searches,
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
        occupants = self._occupants_of(order)
        moved: set = set()

        something_happened = False

        for agent in order:
            if id(agent) in moved:
                continue
            target = agent.next_cell()
            if target is None:
                continue

            agent.credit = min(1.0, agent.credit + agent.speed * self._slow_factor(target))
            if agent.credit < 1.0:
                continue

            if target in self.exit_cells:
                if admissions[target] <= 0:
                    agent.blocked_ticks += 1
                    continue
                admissions[target] -= 1
                self._leave(agent, target)
                something_happened = True
                continue

            if self.occupancy[self._index(*target)] >= self.config.cell_capacity:
                if self._try_swap(agent, target, occupants, moved):
                    something_happened = True
                    continue
                agent.blocked_ticks += 1
                if self._should_reroute(agent):
                    self._reroute(agent)
                continue

            agent.blocked_ticks = 0
            self._move(agent, target)
            something_happened = True

        return something_happened

    def _occupants_of(self, agents: list[Agent]) -> dict:
        """Where everyone still moving is standing, for swap detection."""
        by_cell: dict = {}
        for agent in agents:
            by_cell.setdefault(agent.position, []).append(agent)
        return by_cell

    def _try_swap(self, agent: Agent, target, occupants: dict, moved: set) -> bool:
        """Two people stepping past each other in one move.

        Without this, a corridor at capacity one deadlocks permanently the
        moment two people meet head on: each is standing in the only cell the
        other can move into, and neither can step aside because there is
        nowhere to step. Rerouting cannot solve it either, since no route
        avoids a cell somebody is standing in.

        Real people turn sideways and pass. Allowing the exchange costs nothing
        in occupancy — each cell loses one person and gains one — and it is the
        difference between a density cap of one being usable and being a
        guaranteed gridlock.
        """
        for other in occupants.get(target, ()):
            if other is agent or id(other) in moved:
                continue
            if other.next_cell() != agent.position:
                continue

            here = agent.position
            agent.x, agent.y = target
            other.x, other.y = here
            agent.path_index += 1
            other.path_index += 1
            agent.credit = max(0.0, agent.credit - 1.0)
            other.credit = max(0.0, other.credit - 1.0)
            agent.blocked_ticks = 0
            other.blocked_ticks = 0
            moved.add(id(agent))
            moved.add(id(other))

            occupants.setdefault(here, []).append(other)
            occupants[target] = [a for a in occupants.get(target, []) if a is not other]
            occupants[here] = [a for a in occupants.get(here, []) if a is not agent]
            occupants.setdefault(target, []).append(agent)
            return True
        return False

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
        if agent.exit_id is not None:
            self.heading_for[agent.exit_id] -= 1

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
        self.density.record(self.occupancy, list(self.occupied), self.tick)

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


class ArrivalSimulation(Simulation):
    """Filling a venue rather than emptying one.

    The mechanics of movement are identical — same capacity, same slowdown,
    same rerouting — so this inherits all of it. Three things differ, and they
    are the whole feature:

    People start outside. They queue at an entrance and are admitted one per
    entrance cell per tick, the same flow cap that makes exits bottleneck. What
    happens outside the building is not modelled; the queue is simply a list of
    people not yet in the room.

    They have somewhere to go, and once there they stop for good. Each is
    assigned a place in the spawn area before the run starts, allocated exactly
    as `spawn_agents` places an evacuation crowd, so an arrival finishes in the
    state an evacuation starts in. Nobody who has settled ever moves again.

    The queue is ordered farthest place first, so the room fills from the back
    and nobody walks past somebody already settled. Two alternatives were
    tried and are worse. Stopping at the first free square anyone walks over
    fills the room from the doors inwards and walls off the space behind: on a
    test foyer it left a third of the crowd standing in the doorway. Sending
    everyone to the farthest free square, recalculated as they go, completes
    but strands several times as many people in gangways, because the route to
    the back keeps closing behind them. Allocating up front and filling from
    the back is what stewards do with block numbers, and it is the only one of
    the three that finishes with nobody stranded.

    They stay. An evacuation drains and the room empties; an arrival
    accumulates, so the floor gets progressively fuller and later arrivals have
    to pick their way past people already seated. That is why an arrival can
    jam when an evacuation of the same venue does not.
    """

    def __init__(self, grid: Grid, config: SimulationConfig):
        super().__init__(grid, config)

        self.entrance_cells = {cell for door in grid.entrances for cell in door.cells}
        self.entrance_usage = {door.id: 0 for door in grid.entrances}
        self.checkpoint_cells = {c for s_ in grid.checkpoints for c in s_.cells}
        self.checkpoint_usage = {station.id: 0 for station in grid.checkpoints}
        self.arrived = 0
        self._path_cache: dict[tuple, list] = {}

        # Rewind the generator. The inherited constructor has already placed an
        # evacuation crowd and consumed randomness doing it, so drawing targets
        # from where it left off would give a different allocation than the
        # evacuation of the same venue and seed. Restarting it makes the two
        # match, which is what lets an arrival finish in the state an
        # evacuation starts in.
        self.rng = random.Random(config.seed)

        # Two crowds, two parts of the building. VIPs are given places in the
        # restricted area and everybody else in the general one, so who goes
        # through the checkpoint is decided by where they are going rather than
        # by a flag on the person. The geometry does the rest: the restricted
        # area is by definition only reachable through a checkpoint, so a VIP's
        # route passes one whether the model says so or not.
        vips = min(config.vip_count, config.num_agents)
        general = config.num_agents - vips

        vip_places = places_in(grid.restricted_spawn_cells, vips,
                               config.cell_capacity, self.rng, "VIP area")
        general_places = places_in(grid.general_spawn_cells, general,
                                   config.cell_capacity, self.rng, "general area")

        self.agents = []
        for index, place in enumerate(vip_places):
            self.agents.append(Agent(id=index, x=-1, y=-1, speed=config.speed,
                                     exit_id=None, target=place, waiting=True,
                                     is_vip=True, cleared=False))
        for offset, place in enumerate(general_places):
            self.agents.append(Agent(id=len(vip_places) + offset, x=-1, y=-1,
                                     speed=config.speed, exit_id=None,
                                     target=place, waiting=True))

        fields = {d.id: distance_field(grid, list(d.cells)) for d in grid.entrances}
        assign_entrances(grid, self.agents, fields)

        # Nobody is in the building yet.
        self.occupancy = [0] * (grid.width * grid.height)
        self.occupied = set()

        # Queue order is farthest seat first.
        #
        # People stay where they land, so a room fills up behind them. Admitting
        # in arbitrary order strands whoever is left: their seat is past a row
        # that is already full, and there is no way through. Letting the far
        # seats go first means nobody ever has to walk past someone already
        # seated, which is exactly why ushers and row numbers work that way.
        # How many people are committed to each spawn cell, seated or on their
        # way. Needed to find someone an alternative that is not already full.
        self.stopped_short = 0
        self.claimed: dict = {}
        for agent in self.agents:
            self.claimed[agent.target] = self.claimed.get(agent.target, 0) + 1

        self.queues = {door.id: [] for door in grid.entrances}
        for agent in self.agents:
            if agent.exit_id is not None:
                self.queues[agent.exit_id].append(agent)
        for door_id, queue in self.queues.items():
            reach = fields[door_id]
            queue.sort(key=lambda a: (-reach.get(a.target, 0), a.target[1], a.target[0]))

    # ------------------------------------------------------------------ #

    def active_agents(self) -> list[Agent]:
        """Inside the building and still walking."""
        return [a for a in self.agents if a.is_inside and not a.seated]

    def run(self) -> SimulationResult:
        if not self.grid.entrances:
            return self._result("stalled", len(self.agents))

        unreachable = sum(1 for a in self.agents if a.exit_id is None)
        expected = len(self.agents) - unreachable
        self._record_tick()

        if expected == 0:
            return self._result("stalled", unreachable)

        status = "timeout"
        while self.tick < self.config.max_ticks:
            if self.arrived >= expected:
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
            if self.arrived >= expected:
                status = "complete"

        self.evacuated = self.arrived
        return self._result(status, unreachable)

    def step(self) -> bool:
        something_happened = self._admit()

        # One person per checkpoint cell per tick, refilled here. This is the
        # whole reason a checkpoint is a bottleneck rather than a floor tile.
        clearances = {cell: CHECKPOINT_THROUGHPUT_PER_CELL
                      for cell in self.checkpoint_cells}

        order = self.active_agents()
        self.rng.shuffle(order)
        occupants = self._occupants_of(order)
        moved: set = set()

        for agent in order:
            if id(agent) in moved:
                continue
            target = agent.next_cell()
            if target is None:
                # At the end of a path that no longer goes anywhere. Somebody
                # already checked can simply stop here. Somebody who has not
                # been checked must not: seating them would put an unchecked
                # person in their seat, which is the one outcome a checkpoint
                # exists to prevent. Send them to a checkpoint instead.
                if agent.cleared:
                    self._seat(agent)
                    something_happened = True
                    continue

                station = self._nearest_checkpoint(agent)
                path = astar(self.grid, agent.position, [station]) if station else None
                self.planner.searches += 1
                if path and len(path) > 1:
                    agent.path = path
                    agent.path_index = 0
                    something_happened = True
                continue

            agent.credit = min(1.0, agent.credit + agent.speed * self._slow_factor(target))
            if agent.credit < 1.0:
                continue

            # Waiting to be served, rather than waiting for space.
            if target in self.checkpoint_cells:
                if clearances.get(target, 0) <= 0:
                    agent.blocked_ticks += 1
                    continue
                if self.occupancy[self._index(*target)] >= self.config.cell_capacity:
                    agent.blocked_ticks += 1
                    continue
                clearances[target] -= 1
                agent.blocked_ticks = 0
                self._move(agent, target)
                self._clear(agent)
                something_happened = True
                if agent.position == agent.target:
                    self._seat(agent)
                continue

            if self.occupancy[self._index(*target)] >= self.config.cell_capacity:
                if self._try_swap(agent, target, occupants, moved):
                    if agent.cleared and agent.position == agent.target:
                        self._seat(agent)
                    something_happened = True
                    continue

                agent.blocked_ticks += 1
                agent.total_blocked += 1

                # The give-up fallbacks below end with somebody standing still
                # for good, and that must never happen to a person who has not
                # been through a checkpoint yet: they would end up in their
                # seat unchecked, which is exactly what the checkpoint exists
                # to prevent. Someone queueing waits instead, however long it
                # takes.
                if not agent.cleared:
                    if self._should_reroute(agent):
                        self._reroute_to_target(agent)
                    continue

                if agent.total_blocked >= GIVE_UP_TICKS:
                    self._stand_here(agent)
                    something_happened = True
                    continue

                # Blocked on the destination itself, not on the way to it. No
                # route exists that avoids a cell you are trying to stand in,
                # so rerouting is pointless — and it does not fail, because A*
                # will happily path through a full cell at a higher cost. Left
                # to itself this deadlocks: two people in each other's places,
                # both cells at capacity, each waiting for the other.
                if (agent.cleared and target == agent.target
                        and agent.blocked_ticks >= REROUTE_AFTER_BLOCKED_TICKS):
                    self._take_another_place(agent)
                    continue

                if self._should_reroute(agent):
                    if not self._reroute_to_target(agent):
                        # The room filled in behind the route to their place.
                        # People do not stand in a doorway waiting for a seat
                        # they cannot reach; they take a different one.
                        self._take_another_place(agent)
                continue

            agent.blocked_ticks = 0
            self._move(agent, target)
            something_happened = True

            if (agent.x, agent.y) == agent.target:
                self._seat(agent)

        return something_happened

    def _admit(self) -> bool:
        """Let people in, one per entrance cell per tick.

        Unless the checkpoint queue inside is already as long as it should get,
        in which case they wait outside — which is what a queue manager is for.
        """
        if self._queue_inside_is_full():
            return False

        admitted = False
        for door in self.grid.entrances:
            queue = self.queues[door.id]
            for cell in door.cells:
                if not queue:
                    break
                if self.occupancy[self._index(*cell)] >= self.config.cell_capacity:
                    continue

                agent = queue[0]
                path = self._route(cell, agent.target, vip=agent.is_vip)
                if path is None:
                    # No way from this door to where they are going. Drop them
                    # from the queue rather than blocking everyone behind.
                    queue.pop(0)
                    agent.path = []
                    agent.waiting = False
                    continue

                queue.pop(0)
                agent.waiting = False
                agent.x, agent.y = cell
                agent.path = path
                agent.path_index = 0
                self._set_occupancy(self._index(*cell), 1)
                self.entrance_usage[door.id] += 1
                admitted = True

                if (agent.x, agent.y) in self.checkpoint_cells:
                    self._clear(agent)
                if (agent.x, agent.y) == agent.target:
                    self._seat(agent)
        return admitted

    def _queue_inside_is_full(self) -> bool:
        """Whether to stop letting people in for now.

        Counts everyone inside who is still moving, not only those waiting to
        be checked. The jam that matters is caused by people who have *already*
        been through: they end up standing on the checkpoint itself with
        nowhere onward to step, and once that happens the checkpoint is blocked
        for good. Holding on the total keeps enough slack in the concourse for
        the line to keep moving.
        """
        if not self.grid.checkpoints:
            return False
        inside = sum(1 for a in self.agents if a.is_inside and not a.seated)
        return inside >= self.grid.total_checkpoint_width * QUEUE_HOLD_TICKS

    def _off_limits(self, x: int, y: int) -> bool:
        """Somewhere a general-admission ticket does not go."""
        return (x, y) in self.checkpoint_cells or (x, y) in self.grid.restricted_cells

    def _route_cost_for(self, agent: Agent):
        """Walking cost as this person sees it.

        A VIP is only slowed by crowds. Everybody else treats the security lane
        and everything behind it as somewhere they cannot go, which is the
        whole point of a restricted area — and also stops the lane being used
        as a shortcut, which it otherwise is, because a checkpoint cell is
        walkable and often on the most direct route.
        """
        if agent.is_vip:
            return self._cell_cost

        def cost(x: int, y: int) -> float:
            if self._off_limits(x, y):
                return CHECKPOINT_DETOUR_COST
            return self._cell_cost(x, y)

        return cost

    def _route(self, start, target, vip: bool = False):
        key = (start, target, vip)
        if key not in self._path_cache:
            cost = None if vip else self._keep_out
            self._path_cache[key] = astar(self.grid, start, [target], cost=cost)
        return self._path_cache[key]

    def _keep_out(self, x: int, y: int) -> float:
        return CHECKPOINT_DETOUR_COST if self._off_limits(x, y) else 1.0

    def _reroute_to_target(self, agent: Agent) -> bool:
        agent.last_reroute_tick = self.tick
        agent.blocked_ticks = 0
        # Whichever leg they are on: a ticket holder reroutes towards the
        # checkpoint, not past it.
        # Congestion, and for general admission the restricted area too:
        # rerouting was the remaining way to end up walking through the
        # security lane, because the occupancy cost has no opinion about it.
        path = astar(self.grid, agent.position, [agent.target],
                     cost=self._route_cost_for(agent))
        self.planner.searches += 1
        if not path or len(path) < 2:
            return False
        agent.path = path
        agent.path_index = 0
        self.reroutes += 1
        return True

    def _take_another_place(self, agent: Agent) -> bool:
        """Retarget to the nearest place with room that can actually be reached."""
        here = agent.position

        # Already standing somewhere people are meant to stand. This is the
        # common case once a room is nearly full: two people end up in each
        # other's places, both cells are at capacity, and neither can move
        # because the swap needs a free cell that does not exist. Sitting down
        # where you are is what a person does, and it is the only thing that
        # resolves it.
        if self.grid.at(*here) == SPAWN:
            self.claimed[agent.target] = max(0, self.claimed.get(agent.target, 1) - 1)
            agent.target = here
            self._seat(agent)
            return True

        reach = distance_field(self.grid, [agent.position])
        candidates = [
            cell for cell in self.grid.spawn_cells
            if cell in reach
            and self.claimed.get(cell, 0) < self.config.cell_capacity
            and self.occupancy[self._index(*cell)] < self.config.cell_capacity
        ]
        if not candidates:
            return False

        candidates.sort(key=lambda c: (reach[c], c[1], c[0]))
        for cell in candidates[:5]:
            path = astar(self.grid, agent.position, [cell],
                         cost=self._route_cost_for(agent))
            self.planner.searches += 1
            if not path:
                continue
            self.claimed[agent.target] = max(0, self.claimed.get(agent.target, 1) - 1)
            self.claimed[cell] = self.claimed.get(cell, 0) + 1
            agent.target = cell
            agent.path = path
            agent.path_index = 0
            self.reroutes += 1
            if agent.position == cell:
                self._seat(agent)
            return True
        return False

    def _clear(self, agent: Agent) -> None:
        """Passed the checkpoint. Recorded, and the walk continues."""
        if agent.cleared:
            return
        agent.cleared = True
        agent.tick_cleared = self.tick
        station = self.grid.checkpoint_for_cell(agent.position)
        if station is not None:
            self.checkpoint_usage[station.id] += 1
        agent.total_blocked = 0

    def _stand_here(self, agent: Agent) -> None:
        """Give up on reaching a place and stop where standing.

        Counted separately. Somebody who ends up standing in a gangway because
        the room filled before they got to their spot is not the same as
        somebody seated, and a venue where it happens has told you something
        about its capacity.
        """
        if self.grid.at(*agent.position) != SPAWN:
            self.stopped_short += 1
        self.claimed[agent.target] = max(0, self.claimed.get(agent.target, 1) - 1)
        agent.target = agent.position
        self._seat(agent)

    def _seat(self, agent: Agent) -> None:
        if agent.seated:
            return
        agent.seated = True
        agent.tick_arrived = self.tick
        agent.tick_exited = self.tick   # journey complete, for shared reporting
        self.arrived += 1

    def _record_trace(self) -> None:
        """Everyone in the building, seated or not.

        People still outside are not drawn, because they are not in the venue
        yet. People who have reached their place are, because they are — an
        arrival ends with a full room, not an empty one. `tick_exited` is set
        when a journey completes so that clearing time means the same thing in
        both modes, which is why this cannot simply ask whether they have left.
        """
        positions: list[int] = []
        for agent in self.agents:
            if agent.waiting:
                continue
            if agent.has_left and not agent.seated:
                continue
            positions.append(agent.x)
            positions.append(agent.y)
        self.trace.append(positions)


def simulate(grid: Grid, config: SimulationConfig) -> SimulationResult:
    engine = ArrivalSimulation if config.mode == "arrival" else Simulation
    return engine(grid, config).run()
