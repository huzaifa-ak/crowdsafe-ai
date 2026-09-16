"""Day 8 acceptance: traces survive storage, density is measured correctly, and
the worst case the API will accept stays inside its budgets."""

import random
import time

import pytest

from app.engine import trace as trace_store
from app.engine.density import DENSITY_THRESHOLD, DensityAccumulator
from app.engine.grid import Grid
from app.engine.simulation import SimulationConfig, simulate

# The largest venue the API accepts, laid out to be genuinely hard: scattered
# obstacles, a big spawn area, and one narrow door everybody must queue for.
WORST_CASE = {"width": 80, "height": 60, "agents": 300, "ticks": 600}

# Budgets. These exist to catch a regression that makes something an order of
# magnitude slower, not to police drift across machines. The worst case runs in
# well under a second on a fast machine and a few seconds on a slow laptop —
# roughly a fourfold spread — so the budget has to clear the slow end by enough
# that hardware never fails the suite, while still catching a tenfold slowdown
# anywhere. An earlier 3 s budget failed on an ordinary laptop, which made it a
# measure of the machine rather than of the code.
RUN_SECONDS_BUDGET = 10.0
RAW_TRACE_BYTES_BUDGET = 2 * 1024 * 1024
STORED_TRACE_BYTES_BUDGET = 256 * 1024


@pytest.fixture
def build(ascii_grid):
    def _build(text):
        venue = ascii_grid(text)
        return Grid(venue["width"], venue["height"], venue["cells"])

    return _build


@pytest.fixture(scope="module")
def worst_case_grid():
    width, height = WORST_CASE["width"], WORST_CASE["height"]
    rng = random.Random(3)
    cells = []
    for y in range(height):
        for x in range(width):
            if y == height - 1 and 39 <= x <= 41:
                cells.append("4")
            elif x in (0, width - 1) or y in (0, height - 1):
                cells.append("1")
            elif rng.random() < 0.05:
                cells.append("2")
            elif y < 20 and 2 < x < 60:
                cells.append("5")
            else:
                cells.append("0")
    return Grid(width, height, "".join(cells))


@pytest.fixture(scope="module")
def worst_case_run(worst_case_grid):
    started = time.perf_counter()
    result = simulate(
        worst_case_grid,
        SimulationConfig(num_agents=WORST_CASE["agents"], max_ticks=WORST_CASE["ticks"], seed=42),
    )
    return result, time.perf_counter() - started


# Trace storage --------------------------------------------------------------


def test_a_trace_survives_a_round_trip(build):
    result = simulate(
        build(
            """
            ##########
            #SSSS....#
            #SSSS....#
            #SSSS....#
            #........#
            ########E#
            """
        ),
        SimulationConfig(num_agents=20, seed=42),
    )
    blob = trace_store.encode(result.trace)
    assert trace_store.decode(blob) == result.trace


def test_uncompressed_traces_still_load():
    """Runs stored before compression was added must not become unreadable."""
    import json

    trace = [[1, 2, 3, 4], [1, 3, 3, 5], []]
    assert trace_store.decode(json.dumps(trace).encode("utf-8")) == trace


def test_an_empty_trace_decodes_to_nothing():
    assert trace_store.decode(None) == []
    assert trace_store.decode(b"") == []


def test_compression_earns_its_place(worst_case_run):
    result, _ = worst_case_run
    blob = trace_store.encode(result.trace)
    stats = trace_store.summarise(result.trace, blob)
    # Coordinates repeat heavily between ticks, so anything under 3x would mean
    # something has gone wrong with the format.
    assert stats["compression_ratio"] > 3
    assert stats["stored_bytes"] < stats["raw_bytes"]


# Density --------------------------------------------------------------------


def test_visits_count_agent_ticks(build):
    grid = build(
        """
        #####
        #S..#
        #...#
        #####
        """
    )
    accumulator = DensityAccumulator(grid)
    occupancy = [0] * (grid.width * grid.height)
    index = 1 * grid.width + 1
    occupancy[index] = 2

    for _ in range(5):
        accumulator.record(occupancy, [index])

    assert accumulator.visits[index] == 10  # two people, five ticks


def test_window_density_divides_by_walkable_cells_only(build):
    """A cell in a corner has fewer neighbours. Dividing by nine there would
    understate the crowding in exactly the places crowding is worst."""
    grid = build(
        """
        #####
        #S..#
        #...#
        #####
        """
    )
    accumulator = DensityAccumulator(grid)
    corner = 1 * grid.width + 1
    occupancy = [0] * (grid.width * grid.height)
    occupancy[corner] = 3

    accumulator.record(occupancy, [corner])

    # The corner's window covers four walkable cells, so three people there
    # read as 0.75 per square metre, not 3/9.
    assert accumulator.peak_density[corner] == pytest.approx(0.75)


def test_peak_density_keeps_the_worst_moment(build):
    grid = build(
        """
        #######
        #S....#
        #.....#
        #.....#
        #######
        """
    )
    accumulator = DensityAccumulator(grid)
    middle = 2 * grid.width + 3
    occupancy = [0] * (grid.width * grid.height)

    occupancy[middle] = 3
    accumulator.record(occupancy, [middle])
    busy = accumulator.peak_density[middle]

    occupancy[middle] = 1
    accumulator.record(occupancy, [middle])

    assert accumulator.peak_density[middle] == busy


def test_time_above_the_threshold_is_counted_separately(build):
    """Peak finds the worst instant; duration separates a brief surge from a
    sustained crush. They are different findings and need different numbers."""
    grid = build(
        """
        #####
        #S..#
        #...#
        #####
        """
    )
    accumulator = DensityAccumulator(grid)
    size = grid.width * grid.height
    cells = [1 * grid.width + 1, 1 * grid.width + 2,
             2 * grid.width + 1, 2 * grid.width + 2]

    occupancy = [0] * size
    for cell in cells:
        occupancy[cell] = 3

    for _ in range(4):
        accumulator.record(occupancy, cells)

    packed = accumulator.peak_density[cells[0]]
    assert packed >= DENSITY_THRESHOLD
    assert accumulator.ticks_above[cells[0]] == 4


def test_an_empty_room_records_no_density(build):
    grid = build(
        """
        #####
        #S..#
        #..E#
        #####
        """
    )
    accumulator = DensityAccumulator(grid)
    accumulator.record([0] * (grid.width * grid.height), [])
    assert max(accumulator.peak_density) == 0
    assert sum(accumulator.visits) == 0


def test_density_arrays_line_up_with_the_cell_string(build):
    grid = build(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ########E#
        """
    )
    result = simulate(grid, SimulationConfig(num_agents=20, seed=42))
    density = result.density
    assert len(density["visits"]) == grid.width * grid.height
    assert len(density["peak_density"]) == grid.width * grid.height
    assert density["width"] == grid.width

    # Nobody can ever have stood on a wall, so its visit count must be zero.
    for y in range(grid.height):
        for x in range(grid.width):
            if not grid.is_walkable(x, y):
                assert density["visits"][y * grid.width + x] == 0


def test_density_never_exceeds_the_cell_capacity(build):
    grid = build(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ########E#
        """
    )
    result = simulate(grid, SimulationConfig(num_agents=30, cell_capacity=3, seed=1))
    assert max(result.density["peak_density"]) <= 3.0


def test_the_busiest_cells_are_near_the_door(build):
    """A sanity check on the whole accumulator: in a hall with one exit, the
    heaviest traffic must be the approach to it."""
    grid = build(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ########E#
        """
    )
    result = simulate(grid, SimulationConfig(num_agents=30, seed=1))
    visits = result.density["visits"]
    busiest = max(range(len(visits)), key=lambda i: visits[i])
    x, y = busiest % grid.width, busiest // grid.width
    exit_x, exit_y = grid.exit_cells[0]
    assert abs(x - exit_x) + abs(y - exit_y) <= 3


# Budgets --------------------------------------------------------------------


def test_the_worst_case_run_stays_inside_its_time_budget(worst_case_run):
    result, elapsed = worst_case_run
    assert result.status == "complete"
    assert elapsed < RUN_SECONDS_BUDGET, (
        f"A worst-case run took {elapsed:.2f}s against a {RUN_SECONDS_BUDGET}s budget. "
        "That is far beyond hardware variation — something has become much slower."
    )


def test_the_worst_case_trace_stays_inside_its_size_budget(worst_case_run):
    result, _ = worst_case_run
    raw = trace_store.raw_size(result.trace)
    stored = len(trace_store.encode(result.trace))
    assert raw < RAW_TRACE_BYTES_BUDGET
    assert stored < STORED_TRACE_BYTES_BUDGET


def test_capping_max_ticks_keeps_the_trace_bounded(worst_case_grid):
    """max_ticks is what makes the trace budget hold. At 600 the worst case
    fits comfortably; the cap is the reason it cannot grow without limit."""
    result = simulate(worst_case_grid, SimulationConfig(num_agents=300, max_ticks=600, seed=42))
    assert len(result.trace) <= 601
