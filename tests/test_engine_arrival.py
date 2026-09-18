"""Arrival runs: filling a venue rather than emptying one.

The mechanics are shared with evacuation, so these tests concentrate on what is
genuinely different — people entering over time, staying where they land, and
the room filling up behind them.
"""

import pytest

from app.engine.grid import Grid
from app.engine.simulation import SimulationConfig, simulate

HALL = """
    ######################
    #....................#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #....................#
    #####NN######EEEE#####
"""

ONE_TURNSTILE = """
    ######################
    #....................#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #....................#
    #####N#######EEEE#####
"""

TWO_DOORS = """
    ######################
    #....................#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #..SSSSSSSSSSSSSSSS..#
    #....................#
    #NN########EEEE####NN#
"""

NO_ENTRANCE = """
    ##########
    #SSSS....#
    #SSSS....#
    #SSSS....#
    #........#
    ######EE##
"""


@pytest.fixture
def build(ascii_grid):
    def _build(layout):
        venue = ascii_grid(layout)
        return Grid(venue["width"], venue["height"], venue["cells"])

    return _build


def arrival(grid, **overrides):
    settings = {"mode": "arrival", "num_agents": 120, "seed": 42}
    settings.update(overrides)
    return simulate(grid, SimulationConfig(**settings))


# Filling --------------------------------------------------------------------


def test_a_venue_fills_from_empty(build):
    result = arrival(build(HALL))
    assert result.status == "complete"
    assert result.evacuated == 120
    assert len(result.trace[0]) == 0          # nobody inside at the start
    assert len(result.trace[-1]) == 120 * 2   # everyone inside at the end


def test_people_accumulate_rather_than_drain(build):
    """The defining difference from an evacuation. The number inside only ever
    goes up."""
    result = arrival(build(HALL))
    inside = [len(frame) // 2 for frame in result.trace]
    assert inside == sorted(inside)
    assert inside[0] == 0
    assert inside[-1] == 120


def test_entrances_admit_one_person_per_cell_per_tick(build):
    """The same flow cap that makes exits bottleneck, pointed the other way."""
    result = arrival(build(ONE_TURNSTILE))
    inside = [len(frame) // 2 for frame in result.trace]
    arrivals_per_tick = [b - a for a, b in zip(inside, inside[1:])]
    assert max(arrivals_per_tick) <= 1


def test_a_wider_entrance_fills_faster(build):
    narrow = arrival(build(ONE_TURNSTILE))
    wide = arrival(build(HALL))
    assert wide.clearing_ticks < narrow.clearing_ticks


def test_two_entrances_share_the_crowd(build):
    result = arrival(build(TWO_DOORS))
    assert len(result.entrance_usage) == 2
    assert all(count > 0 for count in result.entrance_usage.values())
    assert sum(result.entrance_usage.values()) == 120


def test_everyone_ends_up_somewhere_they_can_stand(build):
    """Almost everyone reaches the place allocated to them. A handful in a
    packed room will not, and those are counted rather than lost — see
    `stopped_short`."""
    grid = build(HALL)
    result = arrival(grid)
    last = result.trace[-1]
    for x, y in zip(last[0::2], last[1::2]):
        assert grid.is_walkable(x, y)
    assert result.stopped_short <= 2


def test_nobody_exceeds_capacity_while_filling(build):
    grid = build(HALL)
    result = arrival(grid, cell_capacity=3)
    for frame in result.trace:
        counts = {}
        for x, y in zip(frame[0::2], frame[1::2]):
            counts[(x, y)] = counts.get((x, y), 0) + 1
        assert max(counts.values(), default=0) <= 3


# The awkward cases ----------------------------------------------------------


def test_filling_a_room_to_the_brim_still_finishes(build):
    """A room fills up behind the people already in it. Without care the last
    few arrivals deadlock: their place is past a row that is now full, and two
    people end up standing in each other's spots with nowhere to step."""
    grid = build(
        """
        ################
        #..............#
        #..SSSSSSSSSS..#
        #..SSSSSSSSSS..#
        #..............#
        ####NN####EE####
        """
    )
    for count in (50, 55, 59, 60):
        result = arrival(grid, num_agents=count)
        assert result.status == "complete", f"{count} people: {result.status}"
        assert result.evacuated == count


def test_someone_who_cannot_reach_a_place_is_counted_not_lost(build):
    """Standing in a gangway because the room filled first is a finding, not an
    error. It has to be reported rather than quietly fixed."""
    grid = build(
        """
        ################
        #..............#
        #..SSSSSSSSSS..#
        #..SSSSSSSSSS..#
        #..............#
        ####NN####EE####
        """
    )
    result = arrival(grid, num_agents=55)
    assert result.status == "complete"
    assert result.evacuated == 55


def test_a_venue_with_no_entrance_cannot_be_filled(build):
    result = arrival(build(NO_ENTRANCE), num_agents=30)
    assert result.status == "stalled"
    assert result.evacuated == 0


def test_more_people_than_the_room_holds_is_refused(build):
    with pytest.raises(ValueError, match="will not fit"):
        arrival(build(HALL), num_agents=200)


# Determinism ----------------------------------------------------------------


def test_the_same_seed_fills_a_venue_identically(build):
    first = arrival(build(TWO_DOORS), seed=7)
    second = arrival(build(TWO_DOORS), seed=7)
    assert first.trace == second.trace
    assert first.entrance_usage == second.entrance_usage


def test_a_different_seed_fills_it_differently(build):
    assert arrival(build(TWO_DOORS), seed=1).trace != arrival(build(TWO_DOORS), seed=2).trace


def test_evacuation_is_unaffected_by_the_arrival_code(build):
    """The two share an engine. A change to one must not move the other."""
    result = simulate(build(HALL), SimulationConfig(num_agents=120, seed=42))
    assert result.mode == "evacuation"
    assert result.status == "complete"
    assert result.entrance_usage == {}


# An arrival leaves the room where an evacuation starts ----------------------


def test_filling_then_emptying_uses_the_same_crowd(build):
    """Targets are allocated exactly as an evacuation places its crowd, so the
    two runs of one venue and seed join up: the room an arrival leaves behind
    is the room an evacuation begins with.

    Only exactly, though, when everyone reached the place allocated to them. In
    a room filled to the brim a few people stop short, and then the arrival
    ends somewhere the evacuation would never have started — which is itself
    worth knowing, and is why `stopped_short` exists.
    """
    grid = build(HALL)
    filled = arrival(grid, num_agents=90, seed=42)
    evacuating = simulate(grid, SimulationConfig(num_agents=90, seed=42))
    assert filled.stopped_short == 0

    def occupancy(frame):
        counts = {}
        for x, y in zip(frame[0::2], frame[1::2]):
            counts[(x, y)] = counts.get((x, y), 0) + 1
        return counts

    assert occupancy(filled.trace[-1]) == occupancy(evacuating.trace[0])
