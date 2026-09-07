"""Day 5 acceptance: the engine can read a venue, find its exits, and route
through it — reproducibly."""

import pytest

from app.engine.grid import Grid
from app.engine.layout import inspect
from app.engine.pathfinding import astar, distance_field, exit_distance_field


@pytest.fixture
def build(ascii_grid):
    """ASCII layout to engine Grid."""

    def _build(text: str) -> Grid:
        venue = ascii_grid(text)
        return Grid(venue["width"], venue["height"], venue["cells"])

    return _build


# Grid model -----------------------------------------------------------------


def test_walls_and_barriers_are_not_walkable(build):
    grid = build(
        """
        #####
        #S.E#
        #.B.#
        #...#
        #####
        """
    )
    assert grid.is_walkable(1, 1)          # spawn
    assert grid.is_walkable(3, 1)          # exit
    assert not grid.is_walkable(0, 0)      # wall
    assert not grid.is_walkable(2, 2)      # barrier
    assert not grid.is_walkable(-1, 0)     # off grid


def test_neighbours_skip_solid_cells(build):
    grid = build(
        """
        #####
        #...#
        #.#.#
        #...#
        #####
        """
    )
    assert set(grid.neighbours(2, 1)) == {(1, 1), (3, 1)}


def test_cells_are_found_in_row_major_order(build):
    grid = build(
        """
        #####
        #S.S#
        #...#
        #S..#
        #####
        """
    )
    assert grid.spawn_cells == [(1, 1), (3, 1), (1, 3)]


# Exit detection -------------------------------------------------------------


def test_adjacent_exit_cells_are_one_doorway(build):
    grid = build(
        """
        #EEE#
        #...#
        #.S.#
        #...#
        #####
        """
    )
    assert len(grid.exits) == 1
    assert grid.exits[0].width == 3
    assert grid.total_exit_width == 3


def test_separated_exit_cells_are_separate_doorways(build):
    grid = build(
        """
        #E#E#
        #...#
        #.S.#
        #...#
        #####
        """
    )
    assert [e.width for e in grid.exits] == [1, 1]
    assert grid.total_exit_width == 2


def test_exit_ids_follow_reading_order(build):
    grid = build(
        """
        ##E##
        #...#
        E.S.#
        #...#
        ##E##
        """
    )
    firsts = [exit_.cells[0] for exit_ in grid.exits]
    assert firsts == [(2, 0), (0, 2), (2, 4)]
    assert [e.id for e in grid.exits] == [1, 2, 3]


def test_exit_ids_are_stable_across_rebuilds(build):
    layout = """
        ##E##
        #...#
        E.S.#
        #...#
        ##E##
        """
    first = [(e.id, e.cells) for e in build(layout).exits]
    second = [(e.id, e.cells) for e in build(layout).exits]
    assert first == second


# Distance fields ------------------------------------------------------------


def test_distance_field_counts_steps_around_obstacles(build):
    grid = build(
        """
        #######
        #S....#
        #####.#
        #E....#
        #######
        """
    )
    field = exit_distance_field(grid)
    # Two rows apart, but the wall forces a detour out to x=5 and back.
    assert field[(1, 1)] == 10


def test_unreachable_cells_are_absent_from_the_field(build):
    grid = build(
        """
        #######
        #S.#.E#
        #..#..#
        #######
        """
    )
    field = exit_distance_field(grid)
    assert (1, 1) not in field
    assert (5, 1) in field


def test_distance_field_takes_the_nearest_source(build):
    grid = build(
        """
        #######
        E..S..E
        #######
        """
    )
    field = distance_field(grid, grid.exit_cells)
    assert field[(3, 1)] == 3


# A* -------------------------------------------------------------------------


def test_astar_finds_the_shortest_route(build):
    grid = build(
        """
        #######
        #S...E#
        #######
        """
    )
    path = astar(grid, (1, 1), grid.exit_cells)
    assert path[0] == (1, 1)
    assert path[-1] == (5, 1)
    assert len(path) == 5


def test_astar_routes_around_a_barrier(build):
    grid = build(
        """
        #######
        #S..#.#
        #...#.#
        #.....#
        #E#####
        """
    )
    path = astar(grid, (1, 1), grid.exit_cells)
    assert path is not None
    assert path[-1] == (1, 4)
    # Path length equals BFS distance, so it really is shortest.
    assert len(path) - 1 == exit_distance_field(grid)[(1, 1)]


def test_astar_returns_none_when_walled_off(build):
    grid = build(
        """
        #######
        #S.#.E#
        #..#..#
        #######
        """
    )
    assert astar(grid, (1, 1), grid.exit_cells) is None


def test_astar_returns_none_without_goals(build):
    grid = build(
        """
        #####
        #S..#
        #...#
        #####
        """
    )
    assert astar(grid, (1, 1), []) is None


def test_astar_is_deterministic_when_routes_tie(build):
    """A square room gives many equally short routes. The same call must always
    return the same one, or two runs of a simulation would diverge."""
    grid = build(
        """
        #########
        #S......#
        #.......#
        #.......#
        #.......#
        #.......#
        #.......E
        #########
        """
    )
    runs = {tuple(astar(grid, (1, 1), grid.exit_cells)) for _ in range(20)}
    assert len(runs) == 1


def test_astar_respects_a_cost_function(build):
    """Making the direct corridor expensive should push the route round."""
    grid = build(
        """
        #######
        #S...E#
        #.....#
        #.....#
        #######
        """
    )
    def cost(x, y):
        return 50 if y == 1 and x not in (1, 5) else 1

    cheap = astar(grid, (1, 1), grid.exit_cells)
    expensive = astar(grid, (1, 1), grid.exit_cells, cost=cost)
    assert len(expensive) > len(cheap)
    assert (2, 1) not in expensive


# Layout inspection ----------------------------------------------------------


def test_a_usable_venue_reports_ok(build):
    report = inspect(
        build(
            """
            #######
            #S...E#
            #.....#
            #.....#
            #######
            """
        )
    )
    assert report["ok"] is True
    assert report["problems"] == []
    assert report["total_exit_width"] == 1
    assert report["longest_walk"] == 4


def test_a_venue_with_no_exit_is_flagged(build):
    report = inspect(
        build(
            """
            #####
            #S..#
            #...#
            #####
            """
        )
    )
    assert report["ok"] is False
    assert [p["code"] for p in report["problems"]] == ["NO_EXIT"]


def test_a_venue_with_no_spawn_is_flagged(build):
    report = inspect(
        build(
            """
            #####
            #..E#
            #...#
            #####
            """
        )
    )
    assert [p["code"] for p in report["problems"]] == ["NO_SPAWN"]


def test_spawn_cells_walled_off_from_every_exit_are_flagged(build):
    report = inspect(
        build(
            """
            #######
            #S.#.E#
            #..#..#
            #######
            """
        )
    )
    problem = next(p for p in report["problems"] if p["code"] == "UNREACHABLE_SPAWN")
    assert problem["cells"] == [[1, 1]]


def test_an_exit_nobody_can_reach_is_flagged(build):
    report = inspect(
        build(
            """
            #######
            #S...E#
            #.....#
            ###.###
            #####E#
            """
        )
    )
    codes = [p["code"] for p in report["problems"]]
    assert "UNUSABLE_EXIT" in codes


def test_report_lists_every_exit_with_its_width(build):
    report = inspect(
        build(
            """
            #EE#E#
            #....#
            #.S..#
            #....#
            ######
            """
        )
    )
    assert [(e["id"], e["width"]) for e in report["exits"]] == [(1, 2), (2, 1)]
    assert report["total_exit_width"] == 3
