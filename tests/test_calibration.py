"""Day 15 acceptance: the score agrees with judgement across a fixed set of
venues, and keeps agreeing after future changes.

The individual score tests check that thresholds behave arithmetically. This
checks something different and harder: that the whole assembly — engine,
metrics, thresholds — ranks real layouts the way a person would. It is the test
most likely to catch a change that is locally reasonable and globally wrong.

Run `python calibrate.py` to see the table these assertions are made against.
"""

import pytest

from app.analysis.bottlenecks import detect
from app.analysis.metrics import compute
from app.analysis.recommendations import recommend
from app.analysis.score import score
from app.engine.layout import inspect
from app.engine.simulation import SimulationConfig, simulate

from .reference_venues import GRADE_ORDER, SCENARIOS, build, in_band


def assess(scenario: dict) -> dict:
    grid = build(scenario)
    settings = {"num_agents": scenario["agents"], "speed": 1.0, "cell_capacity": 3,
                "max_ticks": 600, "seed": 42, "routing": "nearest", "reroute": True,
                "entrances_are_exits": False}
    result = simulate(grid, SimulationConfig(**settings))
    metrics = compute(grid, result, settings, inspect(grid)["longest_walk"])
    findings = detect(grid, result.density)
    return {
        "grid": grid,
        "metrics": metrics,
        "assessment": score(metrics),
        "advice": recommend(grid, metrics, findings, settings),
    }


@pytest.fixture(scope="module")
def graded():
    return {s["name"]: assess(s) for s in SCENARIOS}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
def test_each_reference_venue_lands_in_its_band(scenario, graded):
    assessment = graded[scenario["name"]]["assessment"]
    assert in_band(assessment["grade"], scenario["expect"]), (
        f"{scenario['name']} scored {assessment['score']} ({assessment['grade']}), "
        f"expected {scenario['expect'][0]}–{scenario['expect'][1]}. {scenario['why']}"
    )


def test_the_scale_is_actually_used(graded):
    """A score that puts every venue between 60 and 75 is not measuring
    anything, however defensible each individual number looks."""
    scores = [g["assessment"]["score"] for g in graded.values()]
    assert max(scores) - min(scores) > 45
    assert len({g["assessment"]["grade"] for g in graded.values()}) >= 4


def test_the_worst_venues_rank_below_the_best(graded):
    best = graded["Small room, small crowd"]["assessment"]["score"]
    good = graded["Hall with generous exits"]["assessment"]["score"]
    bad = graded["One narrow door"]["assessment"]["score"]
    worst = graded["Part of the floor is sealed off"]["assessment"]["score"]
    assert best > good > bad > worst


def test_no_component_saturates_across_the_whole_set(graded):
    """A penalty pinned at full for several venues cannot distinguish bad from
    catastrophic. Congestion did exactly that before this set existed."""
    for name in ("Hall with generous exits", "Lopsided doors", "Pinched corridor"):
        for component in graded[name]["assessment"]["components"]:
            assert component["penalty"] < component["weight"], (
                f"{component['name']} is at full penalty on {name}"
            )


def test_placement_density_is_excluded_from_congestion(graded):
    """A well laid out hall must not be marked down for having a crowd in it."""
    congestion = graded["Hall with generous exits"]["metrics"]["congestion"]
    assert congestion["placed_dense_cells"] > 0
    assert congestion["crowded_share"] < 0.15


def test_a_queue_that_starts_in_the_spawn_area_still_counts(graded):
    """The other half of that exclusion. Where the crowd never disperses, the
    spawn area *is* the queue, and excluding it rated this venue a B."""
    congestion = graded["One narrow door"]["metrics"]["congestion"]
    assert congestion["crowded_share"] > 0.2


def test_the_good_venues_are_not_told_to_do_building_work(graded):
    for name in ("Small room, small crowd", "Hall with generous exits"):
        advice = graded[name]["advice"]
        assert not any(a["priority"] in ("critical", "high") for a in advice), (
            f"{name} was given urgent advice it does not need"
        )


def test_the_bad_venues_are_told_something_useful(graded):
    for name in ("One narrow door", "Pinched corridor", "Part of the floor is sealed off"):
        advice = graded[name]["advice"]
        assert advice, f"{name} produced no advice at all"
        assert advice[0]["priority"] in ("critical", "high")


def test_walk_limited_venues_are_never_told_to_widen_a_door(graded):
    titles = [a["title"] for a in graded["Long thin venue"]["advice"]]
    assert not any(t.startswith("Widen exit") for t in titles)


def test_grades_follow_scores(graded):
    """Sanity on the mapping itself: a higher score can never grade worse."""
    pairs = sorted(
        (g["assessment"]["score"], g["assessment"]["grade"]) for g in graded.values()
    )
    ranks = [GRADE_ORDER.index(grade) for _, grade in pairs]
    assert ranks == sorted(ranks, reverse=True)
