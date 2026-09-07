"""Day 6 acceptance: the crowd spawns, walks, queues at doors and gets out —
the same way every time."""

import random

import pytest

from app.engine.agents import assign_exits, exit_distance_fields, plan_routes, spawn_agents
from app.engine.grid import Grid
from app.engine.simulation import Simulation, SimulationConfig, simulate

HALL = """
    ##########
    #SSSS....#
    #SSSS....#
    #SSSS....#
    #........#
    ########E#
"""

TWO_EXITS = """
    ##########
    E...SS...E
    #...SS...#
    #...SS...#
    #........#
    ##########
"""


@pytest.fixture
def build(ascii_grid):
    def _build(text):
        venue = ascii_grid(text)
        return Grid(venue["width"], venue["height"], venue["cells"])

    return _build


def config(**overrides):
    defaults = {"num_agents": 20, "speed": 1.0, "cell_capacity": 3,
                "max_ticks": 300, "seed": 42}
    return SimulationConfig(**{**defaults, **overrides})


# Spawning -------------------------------------------------------------------


def test_agents_spawn_only_on_spawn_cells(build):
    grid = build(HALL)
    agents = spawn_agents(grid, 20, 1.0, 3, random.Random(1))
    spawn = set(grid.spawn_cells)
    assert len(agents) == 20
    assert all(agent.position in spawn for agent in agents)


def test_spawning_respects_cell_capacity(build):
    grid = build(HALL)
    agents = spawn_agents(grid, 36, 1.0, 3, random.Random(1))
    counts = {}
    for agent in agents:
        counts[agent.position] = counts.get(agent.position, 0) + 1
    assert max(counts.values()) <= 3


def test_too_many_agents_is_rejected(build):
    grid = build(HALL)
    # 12 spawn cells at capacity 3 hold 36.
    with pytest.raises(ValueError, match="will not fit"):
        spawn_agents(grid, 37, 1.0, 3, random.Random(1))


def test_the_same_seed_places_the_same_crowd(build):
    grid = build(HALL)
    first = [a.position for a in spawn_agents(grid, 20, 1.0, 3, random.Random(7))]
    second = [a.position for a in spawn_agents(grid, 20, 1.0, 3, random.Random(7))]
    assert first == second


def test_different_seeds_place_different_crowds(build):
    grid = build(HALL)
    first = [a.position for a in spawn_agents(grid, 20, 1.0, 3, random.Random(1))]
    second = [a.position for a in spawn_agents(grid, 20, 1.0, 3, random.Random(2))]
    assert first != second


# Exit assignment ------------------------------------------------------------


def test_agents_head_for_their_nearest_exit(build):
    grid = build(TWO_EXITS)
    agents = spawn_agents(grid, 12, 1.0, 3, random.Random(1))
    fields = exit_distance_fields(grid)
    assign_exits(grid, agents, fields)

    for agent in agents:
        distances = {i: f[agent.position] for i, f in fields.items()}
        assert distances[agent.exit_id] == min(distances.values())


def test_both_exits_get_used_when_the_crowd_is_central(build):
    result = simulate(build(TWO_EXITS), config(num_agents=18))
    assert all(count > 0 for count in result.exit_usage.values())


def test_agents_with_no_route_are_stranded_not_lost(build):
    grid = build(
        """
        #########
        #S.#..S.#
        #..#...E#
        #########
        """
    )
    agents = spawn_agents(grid, 3, 1.0, 3, random.Random(1))
    fields = exit_distance_fields(grid)
    assign_exits(grid, agents, fields)
    plan_routes(grid, agents)
    walled_off = [a for a in agents if a.position[0] < 3]
    assert walled_off and all(a.is_stranded for a in walled_off)


# Movement -------------------------------------------------------------------


def test_everyone_gets_out_of_an_open_hall(build):
    result = simulate(build(HALL), config(num_agents=20))
    assert result.status == "complete"
    assert result.evacuated == 20
    assert result.stranded == 0
    assert result.clearing_ticks is not None


def test_nobody_ever_shares_a_cell_beyond_capacity(build):
    """Occupancy is the constraint the whole density model rests on. Check it
    holds at every tick rather than only at the end."""
    grid = build(HALL)
    sim = Simulation(grid, config(num_agents=30, cell_capacity=3))
    for _ in range(300):
        sim.tick += 1
        sim.step()
        assert max(sim.occupancy) <= 3
        if sim.evacuated >= len(sim.agents):
            break


def test_agents_never_stand_on_a_solid_cell(build):
    grid = build(HALL)
    sim = Simulation(grid, config(num_agents=25))
    for _ in range(300):
        sim.tick += 1
        sim.step()
        for agent in sim.active_agents():
            assert grid.is_walkable(*agent.position)
        if sim.evacuated >= len(sim.agents):
            break


def test_a_slower_crowd_takes_longer(build):
    fast = simulate(build(HALL), config(num_agents=20, speed=1.0))
    slow = simulate(build(HALL), config(num_agents=20, speed=0.5))
    assert slow.clearing_ticks > fast.clearing_ticks


# Exit throughput ------------------------------------------------------------


def test_a_single_exit_admits_one_agent_per_tick(build):
    """The flow cap, checked directly: however big the queue, a 1 m door can
    never pass two people in the same tick."""
    grid = build(HALL)
    sim = Simulation(grid, config(num_agents=30))
    before = 0
    for _ in range(400):
        sim.tick += 1
        sim.step()
        assert sim.evacuated - before <= 1
        before = sim.evacuated
        if sim.evacuated >= len(sim.agents):
            break
    assert sim.evacuated == 30


def test_a_wider_door_clears_a_hall_faster(build):
    narrow = build(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ########E#
        """
    )
    wide = build(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        #####EEEE#
        """
    )
    narrow_result = simulate(narrow, config(num_agents=30))
    wide_result = simulate(wide, config(num_agents=30))
    assert wide_result.clearing_ticks < narrow_result.clearing_ticks


def test_exit_usage_adds_up_to_the_evacuated_count(build):
    result = simulate(build(TWO_EXITS), config(num_agents=18))
    assert sum(result.exit_usage.values()) == result.evacuated


# Termination ----------------------------------------------------------------


def test_a_sealed_room_does_not_run_for_the_full_budget(build):
    result = simulate(
        build(
            """
            ######
            #SSS.#
            #....#
            #....#
            ######
            """
        ),
        config(num_agents=6),
    )
    assert result.status == "stalled"
    assert result.stranded == 6
    assert result.ticks == 0


def test_a_run_that_cannot_finish_in_time_reports_timeout(build):
    result = simulate(build(HALL), config(num_agents=30, max_ticks=5))
    assert result.status == "timeout"
    assert result.evacuated < 30
    assert result.clearing_ticks is None


# Determinism ----------------------------------------------------------------


def test_the_same_seed_gives_an_identical_run(build):
    first = simulate(build(TWO_EXITS), config(num_agents=18, seed=99))
    second = simulate(build(TWO_EXITS), config(num_agents=18, seed=99))
    assert first.trace == second.trace
    assert first.exit_ticks == second.exit_ticks
    assert first.exit_usage == second.exit_usage
    assert first.clearing_ticks == second.clearing_ticks


def test_a_different_seed_gives_a_different_run(build):
    first = simulate(build(TWO_EXITS), config(num_agents=18, seed=1))
    second = simulate(build(TWO_EXITS), config(num_agents=18, seed=2))
    assert first.trace != second.trace


# Trace ----------------------------------------------------------------------


def test_the_trace_has_one_entry_per_tick_plus_the_start(build):
    result = simulate(build(HALL), config(num_agents=20))
    assert len(result.trace) == result.ticks + 1


def test_the_trace_starts_with_everyone_and_ends_with_nobody(build):
    result = simulate(build(HALL), config(num_agents=20))
    assert len(result.trace[0]) == 20 * 2
    assert result.trace[-1] == []


def test_trace_positions_are_always_inside_the_venue(build):
    grid = build(HALL)
    result = simulate(grid, config(num_agents=20))
    for tick in result.trace:
        for x, y in zip(tick[0::2], tick[1::2]):
            assert grid.is_walkable(x, y)
