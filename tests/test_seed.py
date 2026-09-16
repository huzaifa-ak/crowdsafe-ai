"""Day 17 acceptance: a fresh deploy comes up with usable example venues, and
seeding never touches anyone's own work."""

import pytest

from app import create_app
from app.config import Config
from app.engine.grid import Grid
from app.engine.layout import inspect
from app.engine.simulation import SimulationConfig, simulate
from app.seed import load_examples, parse, seed_if_empty, to_ascii

DEFAULT_AGENTS = 150


@pytest.fixture(scope="module")
def examples():
    return load_examples()


@pytest.fixture
def seeded_app(tmp_path):
    return create_app(Config, DATABASE_PATH=str(tmp_path / "seeded.db"),
                      SEED_EXAMPLES=True)


# Parsing --------------------------------------------------------------------


def test_the_first_comment_line_is_the_name():
    venue = parse("# Main hall\n# some notes\n####\n#SE#\n####\n", "fallback")
    assert venue["name"] == "Main hall"
    assert venue["width"] == 4
    assert venue["height"] == 3


def test_a_wall_row_is_not_mistaken_for_a_comment():
    """Grid rows start with a hash and so do comments. The space is what
    separates them, and getting this wrong would silently eat the top wall."""
    venue = parse("# Named\n####\n#SE#\n####\n", "fallback")
    assert venue["cells"].startswith("1111")
    assert venue["height"] == 3


def test_a_file_without_a_name_falls_back_to_its_filename():
    assert parse("####\n#SE#\n####\n", "back-room")["name"] == "back-room"


def test_a_ragged_plan_is_rejected():
    with pytest.raises(ValueError, match="characters wide"):
        parse("# Bad\n####\n#SE#####\n####\n", "bad")


def test_unknown_characters_are_rejected():
    with pytest.raises(ValueError, match="unknown characters"):
        parse("# Bad\n####\n#SX#\n####\n", "bad")


def test_a_venue_survives_a_round_trip_through_ascii():
    original = parse("# Main hall\n#####\n#S.E#\n#####\n", "x")
    assert parse(to_ascii(original), "x") == original


# The examples themselves -----------------------------------------------------


def test_there_are_examples_to_load(examples):
    assert len(examples) >= 3
    assert len({v["name"] for v in examples}) == len(examples)


def test_every_example_is_a_valid_venue(examples):
    for venue in examples:
        assert len(venue["cells"]) == venue["width"] * venue["height"]
        assert Config.MIN_WIDTH <= venue["width"] <= Config.MAX_WIDTH
        assert Config.MIN_HEIGHT <= venue["height"] <= Config.MAX_HEIGHT


def test_every_example_can_actually_be_evacuated(examples):
    for venue in examples:
        report = inspect(Grid.from_venue(venue))
        assert report["ok"], f"{venue['name']}: {report['problems']}"


def test_every_example_holds_the_default_crowd(examples):
    """An example that refuses the default crowd size is a broken demo: the
    first thing anyone does is press Run."""
    for venue in examples:
        grid = Grid.from_venue(venue)
        capacity = len(grid.spawn_cells) * Config.CELL_CAPACITY
        assert capacity >= DEFAULT_AGENTS, (
            f"{venue['name']} holds {capacity}, needs {DEFAULT_AGENTS}"
        )


def test_every_example_clears_within_the_tick_budget(examples):
    for venue in examples:
        result = simulate(
            Grid.from_venue(venue),
            SimulationConfig(num_agents=DEFAULT_AGENTS, seed=42),
        )
        assert result.status == "complete", f"{venue['name']} ended {result.status}"


def test_the_examples_cover_a_range_of_outcomes(examples):
    """They exist to show what the tool finds. Four venues that all score the
    same and produce the same advice would demonstrate nothing."""
    from app.analysis.bottlenecks import detect
    from app.analysis.metrics import compute
    from app.analysis.score import score

    grades, kinds = set(), set()
    for venue in examples:
        grid = Grid.from_venue(venue)
        settings = {"num_agents": DEFAULT_AGENTS, "speed": 1.0, "cell_capacity": 3,
                    "max_ticks": 600, "seed": 42, "routing": "nearest",
                    "reroute": True, "entrances_are_exits": False}
        result = simulate(grid, SimulationConfig(**settings))
        metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
        grades.add(score(metrics)["grade"])
        kinds.update(f["kind"] for f in detect(grid, result.density))

    assert len(grades) >= 2
    assert {"pinch", "exit_approach"} <= kinds


# Seeding --------------------------------------------------------------------


def test_a_fresh_database_comes_up_with_examples(seeded_app):
    venues = seeded_app.test_client().get("/api/venues").get_json()
    assert len(venues) == len(load_examples())


def test_seeding_twice_does_not_duplicate(seeded_app):
    before = len(seeded_app.test_client().get("/api/venues").get_json())
    assert seed_if_empty(seeded_app) == 0
    after = len(seeded_app.test_client().get("/api/venues").get_json())
    assert after == before


def test_seeding_leaves_an_existing_database_alone(tmp_path, ascii_grid):
    """Someone's own venue must never be joined by four examples they did not
    ask for, or replaced by them."""
    path = str(tmp_path / "used.db")
    app = create_app(Config, DATABASE_PATH=path, SEED_EXAMPLES=False)
    client = app.test_client()
    client.post("/api/venues", json=ascii_grid(
        """
        #####
        #S..#
        #...#
        #..E#
        #####
        """,
        name="Mine",
    ))

    restarted = create_app(Config, DATABASE_PATH=path, SEED_EXAMPLES=True)
    venues = restarted.test_client().get("/api/venues").get_json()
    assert [v["name"] for v in venues] == ["Mine"]


def test_seeding_can_be_turned_off(tmp_path):
    app = create_app(Config, DATABASE_PATH=str(tmp_path / "bare.db"), SEED_EXAMPLES=False)
    assert app.test_client().get("/api/venues").get_json() == []


def test_seeded_venues_are_editable_like_any_other(seeded_app):
    client = seeded_app.test_client()
    venue = client.get("/api/venues").get_json()[0]
    full = client.get(f"/api/venues/{venue['id']}").get_json()
    updated = client.put(f"/api/venues/{venue['id']}", json={**full, "name": "Renamed"})
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Renamed"


def test_a_seeded_venue_can_be_run_straight_away(seeded_app):
    client = seeded_app.test_client()
    venue = client.get("/api/venues").get_json()[0]
    response = client.post("/api/simulations", json={"venue_id": venue["id"]})
    assert response.status_code == 201
    assert response.get_json()["summary"]["status"] == "complete"
