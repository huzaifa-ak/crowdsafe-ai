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


# Congestion-aware routing ---------------------------------------------------

LOPSIDED = """
    ####################
    #SSSSSSSS..........#
    #SSSSSSSS..........#
    #SSSSSSSS..........#
    #SSSSSSSS..........#
    #SSSSSSSS..........#
    E..................E
    ####################
"""

DETOUR = """
    ##################
    #SSSS#...........#
    #SSSS#...........#
    #SSSS.......######
    #SSSS#...........#
    #SSSS#...........#
    #SSSS#..........E#
    ##################
"""


def test_nearest_routing_sends_everyone_to_the_close_door(build):
    """The naive model, and the one that exposes a lopsided layout: both doors
    are the same width, but one is far closer to the crowd."""
    result = simulate(build(LOPSIDED),
                      config(num_agents=120, routing="nearest", reroute=False))
    usage = result.exit_usage
    assert usage[1] == 120
    assert usage[2] == 0


def test_balanced_routing_splits_the_crowd_between_doors(build):
    result = simulate(build(LOPSIDED),
                      config(num_agents=120, routing="balanced", reroute=False))
    near, far = result.exit_usage[1], result.exit_usage[2]
    assert far > 0
    # Neither door should carry more than about two thirds.
    assert max(near, far) / 120 < 0.7


def test_balanced_routing_clears_a_lopsided_hall_faster(build):
    naive = simulate(build(LOPSIDED), config(num_agents=120, routing="nearest", reroute=False))
    managed = simulate(build(LOPSIDED), config(num_agents=120, routing="balanced", reroute=False))
    assert managed.clearing_ticks < naive.clearing_ticks


def test_rerouting_moves_people_to_the_other_door(build):
    """With nearest routing nobody starts out heading for the far door. If any
    of them end up using it, they changed their mind mid-run."""
    result = simulate(build(LOPSIDED), config(num_agents=120, routing="nearest", reroute=True))
    assert result.exit_usage[2] > 0
    assert result.reroutes > 0


def test_rerouting_helps_when_the_crowd_picks_the_wrong_door(build):
    stubborn = simulate(build(LOPSIDED), config(num_agents=120, routing="nearest", reroute=False))
    adaptive = simulate(build(LOPSIDED), config(num_agents=120, routing="nearest", reroute=True))
    assert adaptive.clearing_ticks < stubborn.clearing_ticks


def test_rerouting_finds_the_long_way_round_a_jam(build):
    """One exit, one narrow gap, and a longer route that avoids it. Nobody
    switches doors here — the only thing rerouting can do is take the detour."""
    direct = simulate(build(DETOUR), config(num_agents=70, reroute=False))
    detoured = simulate(build(DETOUR), config(num_agents=70, reroute=True))
    assert detoured.clearing_ticks < direct.clearing_ticks
    assert detoured.reroutes > 0


def test_rerouting_can_be_turned_off(build):
    result = simulate(build(LOPSIDED), config(num_agents=120, reroute=False))
    assert result.reroutes == 0
    assert result.searches == 0


def test_the_route_cache_stops_a_jam_causing_one_search_per_agent(build):
    """Everyone stuck behind the same bottleneck is on one of a few cells, so
    they should share searches rather than each paying for their own."""
    result = simulate(build(LOPSIDED), config(num_agents=120, reroute=True))
    assert result.searches < result.reroutes


def test_rerouting_does_not_strand_anyone(build):
    """An occupancy-aware search can fail where a plain one would not, because
    the only way through may be full at that instant. Failing must mean waiting,
    never losing the route."""
    result = simulate(build(DETOUR), config(num_agents=70, reroute=True))
    assert result.status == "complete"
    assert result.evacuated == 70


def test_rerouting_stays_deterministic(build):
    first = simulate(build(LOPSIDED), config(num_agents=120, seed=3, reroute=True))
    second = simulate(build(LOPSIDED), config(num_agents=120, seed=3, reroute=True))
    assert first.trace == second.trace
    assert first.reroutes == second.reroutes


def test_exit_usage_still_adds_up_after_people_change_their_minds(build):
    result = simulate(build(LOPSIDED), config(num_agents=120, reroute=True))
    assert sum(result.exit_usage.values()) == result.evacuated
