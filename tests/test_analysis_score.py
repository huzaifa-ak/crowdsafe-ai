"""Day 12 acceptance: the numbers describe the run honestly, and the score
ranks venues the way a person would."""

import pytest

from app.analysis.metrics import compute
from app.analysis.score import score
from app.engine.grid import Grid
from app.engine.layout import inspect
from app.engine.simulation import SimulationConfig, simulate

BODY = "\n".join(["#SSSSSSSSSSSS......#"] * 8)

WIDE = "####################\n" + BODY + "\nEEEE...........EEEEE\n####################"
NARROW = "####################\n" + BODY + "\n##########E#########"
LOPSIDED = "####################\n" + BODY + "\nE..................E\n####################"


@pytest.fixture
def measure(ascii_grid):
    """Run a layout and return (metrics, assessment)."""

    def _measure(layout, **overrides):
        venue = ascii_grid(layout)
        grid = Grid(venue["width"], venue["height"], venue["cells"])
        settings = {"num_agents": 150, "speed": 1.0, "cell_capacity": 3,
                    "max_ticks": 600, "seed": 42, "routing": "nearest", "reroute": True,
                    "entrances_are_exits": False}
        settings.update(overrides)
        result = simulate(grid, SimulationConfig(**settings))
        metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
        return metrics, score(metrics)

    return _measure


# Metrics --------------------------------------------------------------------


def test_the_free_flow_floor_is_the_larger_of_walking_and_doors(measure):
    metrics, _ = measure(NARROW)
    time = metrics["time"]
    assert time["free_flow_ticks"] == max(time["walk_floor_ticks"], time["door_floor_ticks"])


def test_a_narrow_door_makes_the_doors_the_binding_constraint(measure):
    metrics, _ = measure(NARROW)
    assert metrics["time"]["binding_constraint"] == "doors"
    assert metrics["time"]["door_floor_ticks"] == 150


def test_generous_doors_make_walking_the_binding_constraint(measure):
    metrics, _ = measure(WIDE, num_agents=40)
    assert metrics["time"]["binding_constraint"] == "walking"


def test_exit_share_is_measured_against_width_not_an_even_split(ascii_grid):
    """A 3 m door beside a 1 m one should carry three quarters of the crowd.
    Penalising that would be penalising the venue for working properly."""
    venue = ascii_grid(
        "####################\n" + BODY + "\n#EEE##########E#####\n####################"
    )
    grid = Grid(venue["width"], venue["height"], venue["cells"])
    settings = {"num_agents": 150, "speed": 1.0, "cell_capacity": 3, "max_ticks": 600,
                "seed": 42, "routing": "balanced", "reroute": True,
                "entrances_are_exits": False}
    result = simulate(grid, SimulationConfig(**settings))
    metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])

    wide = next(d for d in metrics["exits"]["doors"] if d["width"] == 3)
    assert wide["capacity_share"] == 0.75
    # Carrying more than an even split is expected here, not an imbalance.
    assert wide["share"] > 0.5


def test_congestion_separates_how_much_from_how_long(measure):
    metrics, _ = measure(NARROW)
    congestion = metrics["congestion"]
    assert congestion["crowded_cells"] > 0
    assert congestion["crowded_share"] <= 1
    assert congestion["longest_crowded_spell"] > 0
    assert 0 < congestion["crowded_intensity"] < 1


def test_an_empty_quiet_room_reports_no_congestion(measure):
    metrics, _ = measure(WIDE, num_agents=20)
    assert metrics["congestion"]["peak_density"] <= 3.0


# Score ----------------------------------------------------------------------


def test_a_venue_with_generous_exits_beats_one_with_a_single_narrow_door(measure):
    _, good = measure(WIDE)
    _, bad = measure(NARROW)
    assert good["score"] > bad["score"]


def test_a_lopsided_pair_of_doors_sits_between_the_two(measure):
    _, good = measure(WIDE)
    _, middling = measure(LOPSIDED)
    _, bad = measure(NARROW)
    assert good["score"] > middling["score"] > bad["score"]


def test_a_small_crowd_scores_well_everywhere(measure):
    """Forty people leaving through one door is genuinely fine. A score that
    condemned it would be measuring the layout instead of the risk."""
    for layout in (WIDE, NARROW, LOPSIDED):
        _, assessment = measure(layout, num_agents=40)
        assert assessment["grade"] == "A"


def test_the_score_falls_as_the_crowd_grows(measure):
    """The flaw this replaced: the free-flow baseline grows with the crowd once
    the doors bind, so a ratio-driven score rated 300 people safer than 120."""
    scores = [measure(NARROW, num_agents=n)[1]["score"] for n in (40, 80, 150, 250)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] - scores[-1] > 40


def test_people_left_behind_cap_the_score(ascii_grid):
    """A venue people cannot get out of does not pass because its density
    figures happen to look calm."""
    venue = ascii_grid(
        """
        #############
        #SSS#....SSS#
        #SSS#....SSSE
        #SSS#....SSS#
        #############
        """
    )
    grid = Grid(venue["width"], venue["height"], venue["cells"])
    settings = {"num_agents": 30, "speed": 1.0, "cell_capacity": 3, "max_ticks": 600,
                "seed": 42, "routing": "nearest", "reroute": True,
                "entrances_are_exits": False}
    result = simulate(grid, SimulationConfig(**settings))
    metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
    assessment = score(metrics)

    assert metrics["crowd"]["stranded"] > 0
    assert assessment["score"] <= 35
    assert assessment["capped_by"]


def test_every_component_stays_inside_its_weight(measure):
    for layout in (WIDE, NARROW, LOPSIDED):
        _, assessment = measure(layout)
        for component in assessment["components"]:
            assert 0 <= component["penalty"] <= component["weight"]


def test_the_weights_add_to_one_hundred(measure):
    _, assessment = measure(WIDE)
    assert sum(c["weight"] for c in assessment["components"]) == 100


def test_the_score_never_leaves_its_range(measure):
    for layout in (WIDE, NARROW, LOPSIDED):
        for agents in (20, 150, 288):
            _, assessment = measure(layout, num_agents=agents)
            assert 0 <= assessment["score"] <= 100
            assert assessment["grade"] in "ABCDF"


def test_every_component_explains_itself(measure):
    """A score nobody can argue with is a score nobody can act on."""
    _, assessment = measure(NARROW)
    for component in assessment["components"]:
        assert component["detail"]
        assert component["detail"].endswith(".")
