"""Day 16 acceptance: two runs can be compared, and the comparison refuses to
pretend when the two are not comparable."""

import pytest

from app.analysis.comparison import compare

BODY = "\n".join(["#SSSSSSSSSSSS........#"] * 4)
NARROW = "######################\n" + BODY + "\n##########E###########"
WIDE = "######################\n" + BODY + "\n########EEEEE#########"


@pytest.fixture
def runs(client, ascii_grid):
    """Create venues and run them, returning a helper for making runs."""

    def _make(layout, name, **config):
        venue = client.post("/api/venues", json=ascii_grid(layout, name=name)).get_json()
        settings = {"num_agents": 120, "seed": 42}
        settings.update(config)
        return client.post(
            "/api/simulations",
            json={"venue_id": venue["id"], "config": settings},
        ).get_json()["id"]

    return _make


# Comparison logic -----------------------------------------------------------


def test_widening_a_door_is_reported_as_an_improvement(client, runs):
    before = runs(NARROW, "Narrow")
    after = runs(WIDE, "Widened")
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": before, "variant_simulation_id": after,
    }).get_json()["summary"]

    assert summary["comparable"] is True
    assert summary["score"]["delta"] > 0
    assert "improvement" in summary["verdict"]

    clearing = next(c for c in summary["changes"] if c["name"] == "Clearing time")
    assert clearing["delta"] < 0
    assert clearing["better"] is True


def test_the_same_queue_at_a_widened_door_is_not_reported_as_new(client, runs):
    """Widening a door moves its worst cell. Matching findings on coordinates
    reported the queue as gone and an identical one as new, which is the
    opposite of what happened."""
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow"),
        "variant_simulation_id": runs(WIDE, "Widened"),
    }).get_json()["summary"]

    findings = summary["findings"]
    assert not findings["new"]
    assert not findings["resolved"]
    queue = next(f for f in findings["remaining"] if "exit" in f["label"])
    assert queue["improved"] is True
    assert queue["severity_after"] < queue["severity_before"]


def test_runs_with_different_crowds_are_refused_as_a_comparison(client, runs):
    """The measurements still appear, but never as evidence about the layout."""
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow", num_agents=120),
        "variant_simulation_id": runs(WIDE, "Widened", num_agents=60),
    }).get_json()["summary"]

    assert summary["comparable"] is False
    assert any(w["field"] == "num_agents" for w in summary["warnings"])
    assert "not only the layout" in summary["warnings"][0]["message"]
    assert "cannot be read as the effect of the change" in summary["verdict"]


def test_a_different_seed_is_flagged_too(client, runs):
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow", seed=1),
        "variant_simulation_id": runs(NARROW, "Narrow again", seed=2),
    }).get_json()["summary"]
    assert summary["comparable"] is False
    assert any(w["field"] == "seed" for w in summary["warnings"])


def test_each_change_says_which_direction_is_better(client, runs):
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow"),
        "variant_simulation_id": runs(WIDE, "Widened"),
    }).get_json()["summary"]

    by_name = {c["name"]: c for c in summary["changes"]}
    # Less time is better, more evacuated is better, and a change in exit width
    # is neither on its own.
    assert by_name["Clearing time"]["better"] is True
    assert by_name["Total exit width"]["better"] is None


def test_an_unchanged_layout_compares_as_no_difference(client, runs):
    first = runs(NARROW, "A")
    second = runs(NARROW, "B")
    summary = client.post("/api/comparisons", json={
        "baseline_simulation_id": first, "variant_simulation_id": second,
    }).get_json()["summary"]

    assert summary["comparable"] is True
    assert summary["score"]["delta"] == 0
    assert "Little difference" in summary["verdict"]


def test_compare_handles_runs_without_metrics():
    """Defensive: a stored run from before metrics existed must not crash the
    page."""
    summary = compare({"config": {}}, {"config": {}})
    assert summary["changes"] == []
    assert summary["score"]["delta"] is None


# API ------------------------------------------------------------------------


def test_a_comparison_is_stored_and_can_be_fetched(client, runs):
    created = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow"),
        "variant_simulation_id": runs(WIDE, "Widened"),
        "name": "Widening the door",
    })
    assert created.status_code == 201
    body = created.get_json()
    assert created.headers["Location"].endswith(f"/api/comparisons/{body['id']}")

    fetched = client.get(f"/api/comparisons/{body['id']}").get_json()
    assert fetched["summary"] == body["summary"]
    assert fetched["name"] == "Widening the door"
    assert fetched["baseline_simulation_id"] == body["baseline_simulation_id"]


def test_comparisons_are_listed(client, runs):
    client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow"),
        "variant_simulation_id": runs(WIDE, "Widened"),
    })
    assert len(client.get("/api/comparisons").get_json()) == 1


def test_a_run_cannot_be_compared_with_itself(client, runs):
    only = runs(NARROW, "Narrow")
    response = client.post("/api/comparisons", json={
        "baseline_simulation_id": only, "variant_simulation_id": only,
    })
    assert response.status_code == 422


def test_comparing_a_missing_run_is_404(client, runs):
    response = client.post("/api/comparisons", json={
        "baseline_simulation_id": runs(NARROW, "Narrow"), "variant_simulation_id": 999,
    })
    assert response.status_code == 404


def test_both_ids_are_required(client):
    response = client.post("/api/comparisons", json={"baseline_simulation_id": 1})
    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["field"] == "variant_simulation_id"


def test_fetching_a_missing_comparison_is_404(client):
    assert client.get("/api/comparisons/999").status_code == 404


# Page -----------------------------------------------------------------------


def test_the_compare_page_lists_runs_to_choose_from(client, runs):
    runs(NARROW, "Narrow")
    runs(WIDE, "Widened")
    body = client.get("/compare").data.decode()
    assert 'id="baseline"' in body
    assert 'id="variant"' in body
    assert 'id="changes"' in body


def test_the_compare_page_says_so_when_there_is_nothing_to_compare(client):
    body = client.get("/compare").data.decode()
    assert "Not enough runs yet" in body


def test_the_dashboard_links_to_comparing(client):
    assert "/compare" in client.get("/").data.decode()
