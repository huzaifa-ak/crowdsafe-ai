"""Day 14 acceptance: each rule fires on the venue it is meant for, stays quiet
on the venues it is not, and never claims more than it can support."""

import pytest

from app.analysis.bottlenecks import detect
from app.analysis.metrics import compute
from app.analysis.recommendations import PRIORITIES, recommend
from app.engine.grid import Grid
from app.engine.layout import inspect
from app.engine.simulation import SimulationConfig, simulate

NARROW_DOOR = """
    ######################
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    ##########E###########
"""

PINCHED = """
    ######################
    #SSSSSSSS............#
    #SSSSSSSS............#
    #SSSSSSSS............#
    #SSSSSSSS............#
    #SSSSSSSS............#
    #########..###########
    #####................#
    #####................#
    #####...............E#
    ######################
"""

LOPSIDED = """
    ######################
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    #SSSSSSSSSSSS........#
    E....................E
    ######################
"""

WITH_ENTRANCES = """
    ######################
    N.SSSSSSSSSSSS.......#
    N.SSSSSSSSSSSS.......#
    N.SSSSSSSSSSSS.......#
    #.SSSSSSSSSSSS.......#
    ##########E###########
"""

LONG_WALK = """
    ##############################
    #SSSSSS......................#
    #SSSSSS......................#
    #SSSSSS......................#
    #SSSSSS......................#
    ############################EE
    ##############################
"""

ROOMY = """
    ######################
    #....................#
    #..SSSSSS..SSSSSS....#
    #..SSSSSS..SSSSSS....#
    #....................#
    EEEEEEEEEEEEEEEEEEEEEE
    ######################
"""


@pytest.fixture
def advise(ascii_grid):
    def _advise(layout, num_agents=120, **overrides):
        venue = ascii_grid(layout)
        grid = Grid(venue["width"], venue["height"], venue["cells"])
        settings = {"num_agents": num_agents, "speed": 1.0, "cell_capacity": 3,
                    "max_ticks": 600, "seed": 42, "routing": "nearest",
                    "reroute": True, "entrances_are_exits": False}
        settings.update(overrides)
        result = simulate(grid, SimulationConfig(**settings))
        metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
        findings = detect(grid, result.density)
        return recommend(grid, metrics, findings, settings)

    return _advise


def titles(advice):
    return " | ".join(a["title"] for a in advice)


# Individual rules -----------------------------------------------------------


def test_a_narrow_door_is_told_to_widen(advise):
    advice = advise(NARROW_DOOR)
    widen = next(a for a in advice if a["title"].startswith("Widen exit"))
    assert widen["evidence"]["current_width"] == 1
    assert widen["evidence"]["proposed_width"] == 2
    assert "faster" in widen["estimate"]


def test_a_pinch_point_is_named_with_its_coordinates(advise):
    advice = advise(PINCHED, num_agents=110)
    pinch = next(a for a in advice if "gap at" in a["title"])
    assert pinch["evidence"]["at"] == [9, 6]
    assert pinch["evidence"]["passage_width"] == 2


def test_an_uneven_split_suggests_signage_rather_than_building_work(advise):
    advice = advise(LOPSIDED, reroute=False)
    uneven = next(a for a in advice if "too much of the work" in a["title"])
    assert uneven["evidence"]["overloaded_exit"] == 1
    assert uneven["evidence"]["underused_exit"] == 2
    assert "marshals" in uneven["action"] or "Signage" in uneven["action"]


def test_idle_entrances_are_pointed_out_when_doors_are_the_limit(advise):
    advice = advise(WITH_ENTRANCES)
    entrances = next(a for a in advice if "entrance" in a["title"])
    assert entrances["evidence"]["entrance_cells"] == 3
    assert entrances["priority"] == "high"


def test_a_walk_limited_venue_is_not_told_to_widen_its_doors(advise):
    """The most important negative case. Widening a door that is not the
    constraint is wasted money, and a tool that recommends it is worse than no
    tool."""
    advice = advise(LONG_WALK, num_agents=60)
    assert "Widen exit" not in titles(advice)
    assert any("long way from any exit" in a["title"] for a in advice)


def test_a_venue_that_works_gets_little_or_no_advice(advise):
    advice = advise(ROOMY, num_agents=60)
    assert not any(a["priority"] in ("critical", "high") for a in advice)


def test_stranded_people_produce_a_critical_warning(advise):
    advice = advise(
        """
        #############
        #SSS#....SSS#
        #SSS#....SSSE
        #SSS#....SSS#
        #############
        """,
        num_agents=30,
    )
    assert advice[0]["priority"] == "critical"
    assert "no route out" in advice[0]["title"]


def test_starting_density_is_reported_as_low_priority(advise):
    """It is a fact about how many people were placed where, not a fault in the
    layout, and must not crowd out the things that are."""
    advice = advise(ROOMY, num_agents=70)
    packed = [a for a in advice if "starts at high density" in a["title"]]
    if packed:
        assert packed[0]["priority"] == "low"


# Shape and honesty ----------------------------------------------------------


def test_advice_is_ordered_worst_first(advise):
    advice = advise(PINCHED, num_agents=110)
    ranks = [(PRIORITIES.index(a["priority"]), -a["weight"]) for a in advice]
    assert ranks == sorted(ranks)


def test_every_recommendation_carries_its_evidence(advise):
    """A suggestion you cannot check is a suggestion you cannot trust."""
    for layout, agents in ((NARROW_DOOR, 120), (PINCHED, 110), (LONG_WALK, 60)):
        for item in advise(layout, num_agents=agents):
            assert item["evidence"]
            assert item["title"] and item["action"]
            assert item["priority"] in PRIORITIES


def test_capacity_advice_does_not_invent_a_number(advise):
    """Crowded share does not scale with the crowd in any way worth
    extrapolating, so the rule offers a starting point to test rather than a
    calculated capacity."""
    advice = advise(NARROW_DOOR)
    capacity = next((a for a in advice if "more people than" in a["title"]), None)
    if capacity:
        assert "try" in capacity["action"]
        assert "measured, not calculated" in capacity["estimate"]


def test_recommendations_are_numbered(advise):
    advice = advise(PINCHED, num_agents=110)
    assert [a["id"] for a in advice] == list(range(1, len(advice) + 1))
