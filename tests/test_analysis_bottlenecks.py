"""Day 13 acceptance: crowded cells become located, described findings."""

import pytest

from app.analysis.bottlenecks import detect
from app.engine.grid import Grid
from app.engine.simulation import SimulationConfig, simulate

# A hall whose crowd must squeeze through a 2 m gap to reach a 1 m door, so
# there are two distinct problems and one is clearly worse than the other.
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

OPEN_HALL = """
    ######################
    #SSSSSSSS............#
    #SSSSSSSS............#
    #SSSSSSSS............#
    EEEEEEEEEEEEEEEEEEEEEE
    ######################
"""


@pytest.fixture
def findings(ascii_grid):
    def _findings(layout, **overrides):
        venue = ascii_grid(layout)
        grid = Grid(venue["width"], venue["height"], venue["cells"])
        settings = {"num_agents": 110, "speed": 1.0, "cell_capacity": 3,
                    "max_ticks": 600, "seed": 42}
        settings.update(overrides)
        result = simulate(grid, SimulationConfig(**settings))
        return grid, detect(grid, result.density)

    return _findings


def test_a_pinch_point_is_found_and_located(findings):
    grid, found = findings(PINCHED)
    pinch = next(f for f in found if f["kind"] == "pinch")
    assert pinch["passage_width"] == 2
    # The gap in that layout is at x=9-10, y=6.
    assert pinch["pinch_at"][1] == 6
    assert pinch["pinch_at"][0] in (9, 10)


def test_the_queue_at_a_door_is_recognised_as_such(findings):
    _, found = findings(PINCHED)
    queue = next(f for f in found if f["kind"] == "exit_approach")
    assert queue["nearest_exit"] == 1
    assert queue["exit_distance"] <= 3
    assert "exit 1" in queue["label"]


def test_findings_are_ranked_by_how_much_time_they_cost(findings):
    """The pinch holds the whole crowd; the door queue holds whoever got
    through. Ranking has to put the cause above the symptom."""
    _, found = findings(PINCHED)
    assert [f["severity"] for f in found] == sorted(
        (f["severity"] for f in found), reverse=True
    )
    assert found[0]["kind"] == "pinch"
    assert found[0]["severity"] > found[1]["severity"] * 2


def test_a_pinch_is_located_at_the_gap_not_the_queue_behind_it(findings):
    """A region spans the constriction and the crowd backed up behind it. The
    centroid lands in the queue, which is the symptom; the reported point has
    to be the cause."""
    grid, found = findings(PINCHED)
    pinch = found[0]
    assert pinch["pinch_at"] != pinch["centre"]
    x, y = pinch["pinch_at"]
    assert grid.is_walkable(x, y)
    assert not grid.is_walkable(x - 1, y) or not grid.is_walkable(x + 1, y)


def test_every_finding_carries_a_readable_description(findings):
    _, found = findings(PINCHED)
    for finding in found:
        assert finding["label"]
        assert finding["detail"].endswith(".")
        assert "people per m²" in finding["detail"]
        assert len(finding["centre"]) == 2


def test_findings_are_numbered_worst_first(findings):
    _, found = findings(PINCHED)
    assert [f["id"] for f in found] == list(range(1, len(found) + 1))


def test_single_cells_are_not_reported_as_bottlenecks(findings):
    """One cell briefly over the line is a person pausing, not a finding."""
    _, found = findings(PINCHED)
    assert all(f["size"] >= 3 for f in found)


def test_a_hall_that_never_gets_crowded_reports_nothing(findings):
    _, found = findings(OPEN_HALL, num_agents=20)
    assert found == []


def test_a_wide_open_exit_wall_produces_few_findings(findings):
    """Twenty-two metres of door for a full room should not read as a venue
    riddled with bottlenecks."""
    _, found = findings(OPEN_HALL, num_agents=70)
    assert len(found) <= 2


def test_findings_cover_real_cells_inside_the_venue(findings):
    grid, found = findings(PINCHED)
    for finding in found:
        assert finding["cells"]
        for index in finding["cells"]:
            x, y = index % grid.width, index // grid.width
            assert grid.is_walkable(x, y)


def test_at_most_five_findings_are_returned(findings):
    _, found = findings(PINCHED)
    assert len(found) <= 5
