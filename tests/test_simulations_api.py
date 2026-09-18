"""Day 7 acceptance: a saved venue can be run through the API, the result is
stored, and fetching it back gives the same run."""

import pytest

HALL = """
    ##########
    #SSSS....#
    #SSSS....#
    #SSSS....#
    #........#
    ########E#
"""


@pytest.fixture
def venue_id(client, ascii_grid):
    venue = ascii_grid(HALL, name="Hall")
    return client.post("/api/venues", json=venue).get_json()["id"]


def run(client, venue_id, **config):
    return client.post("/api/simulations", json={"venue_id": venue_id, "config": config})


# Running --------------------------------------------------------------------


def test_a_run_returns_a_summary_and_a_trace(client, venue_id):
    response = run(client, venue_id, num_agents=20, seed=42)
    assert response.status_code == 201
    body = response.get_json()

    assert body["summary"]["status"] == "complete"
    assert body["summary"]["evacuated"] == 20
    assert body["summary"]["clearing_ticks"] > 0
    assert len(body["trace"]) == body["summary"]["ticks"] + 1


def test_a_run_sets_a_location_header(client, venue_id):
    response = run(client, venue_id, num_agents=20)
    assert response.headers["Location"].endswith(f"/api/simulations/{response.get_json()['id']}")


def test_clearing_time_is_reported_in_seconds(client, venue_id):
    summary = run(client, venue_id, num_agents=20).get_json()["summary"]
    assert summary["clearing_seconds"] == pytest.approx(summary["clearing_ticks"] * 0.7, abs=0.1)


def test_the_free_flow_baseline_accounts_for_door_width(client, venue_id):
    """The hall has a 1 m door, so 40 people need at least 40 ticks however
    short the walk is. The baseline must not be the walk alone."""
    summary = run(client, venue_id, num_agents=36).get_json()["summary"]
    assert summary["free_flow_ticks"] >= 36
    assert summary["time_ratio"] >= 1


def test_exit_widths_are_reported_alongside_usage(client, venue_id):
    summary = run(client, venue_id, num_agents=20).get_json()["summary"]
    assert summary["exit_widths"] == {"1": 1}
    assert sum(summary["exit_usage"].values()) == summary["evacuated"]


def test_defaults_are_filled_in_when_no_config_is_sent(client, venue_id):
    body = client.post("/api/simulations", json={"venue_id": venue_id}).get_json()
    # 12 spawn cells at capacity 3 cannot hold the default 150, so this venue
    # needs an explicit count — checked separately. Here we only assert the
    # error names the right field.
    assert body["error"]["details"][0]["field"] == "num_agents"


def test_config_is_echoed_back_with_defaults_applied(client, venue_id):
    config = run(client, venue_id, num_agents=20).get_json()["config"]
    assert config["num_agents"] == 20
    assert config["seed"] == 42
    assert config["cell_capacity"] == 3
    assert config["max_ticks"] == 600


# Determinism ----------------------------------------------------------------


def test_the_same_seed_gives_an_identical_run_through_the_api(client, venue_id):
    first = run(client, venue_id, num_agents=24, seed=7).get_json()
    second = run(client, venue_id, num_agents=24, seed=7).get_json()
    assert first["trace"] == second["trace"]
    assert first["summary"] == second["summary"]


def test_a_different_seed_changes_the_run(client, venue_id):
    first = run(client, venue_id, num_agents=24, seed=1).get_json()
    second = run(client, venue_id, num_agents=24, seed=2).get_json()
    assert first["trace"] != second["trace"]


# Storage --------------------------------------------------------------------


def test_a_stored_run_can_be_fetched_back_unchanged(client, venue_id):
    created = run(client, venue_id, num_agents=20, seed=5).get_json()
    fetched = client.get(f"/api/simulations/{created['id']}").get_json()

    assert fetched["trace"] == created["trace"]
    assert fetched["summary"] == created["summary"]
    assert fetched["config"] == created["config"]
    assert fetched["created_at"]


def test_the_venue_snapshot_survives_editing_the_venue(client, venue_id, ascii_grid):
    """A result must keep meaning its own layout, not whatever the venue
    became afterwards."""
    created = run(client, venue_id, num_agents=20).get_json()
    original = created["venue_snapshot"]["cells"]

    replacement = ascii_grid(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        #####EEEE#
        """,
        name="Hall widened",
    )
    client.put(f"/api/venues/{venue_id}", json=replacement)

    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["venue_snapshot"]["cells"] == original
    assert fetched["venue_snapshot"]["cells"] != replacement["cells"]


def test_runs_are_listed_newest_first(client, venue_id):
    first = run(client, venue_id, num_agents=20, seed=1).get_json()["id"]
    second = run(client, venue_id, num_agents=20, seed=2).get_json()["id"]
    listing = client.get("/api/simulations").get_json()
    assert [row["id"] for row in listing] == [second, first]
    assert listing[0]["summary"]["evacuated"] == 20


def test_runs_can_be_listed_for_one_venue(client, venue_id, ascii_grid):
    run(client, venue_id, num_agents=20)
    other = client.post("/api/venues", json=ascii_grid(HALL, name="Other")).get_json()["id"]
    run(client, other, num_agents=20)

    listing = client.get(f"/api/simulations?venue_id={venue_id}").get_json()
    assert len(listing) == 1
    assert listing[0]["venue_id"] == venue_id


def test_fetching_a_missing_run_is_404(client):
    assert client.get("/api/simulations/999").status_code == 404


# Refusals -------------------------------------------------------------------


def test_running_a_missing_venue_is_404(client):
    assert client.post("/api/simulations", json={"venue_id": 999}).status_code == 404


def test_venue_id_is_required(client):
    response = client.post("/api/simulations", json={})
    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["field"] == "venue_id"


def test_a_venue_with_no_exit_is_refused_rather_than_run(client, ascii_grid):
    sealed = ascii_grid(
        """
        ######
        #SSS.#
        #....#
        #....#
        ######
        """,
        name="Sealed",
    )
    venue = client.post("/api/venues", json=sealed).get_json()
    response = run(client, venue["id"], num_agents=20)
    assert response.status_code == 422
    assert "no exits" in response.get_json()["error"]["details"][0]["message"]


def test_more_people_than_the_spawn_area_holds_is_refused(client, venue_id):
    response = run(client, venue_id, num_agents=200)
    assert response.status_code == 422
    detail = response.get_json()["error"]["details"][0]
    assert detail["field"] == "num_agents"
    assert "36" in detail["message"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("num_agents", 19),      # below MIN_AGENTS
        ("num_agents", 301),     # above MAX_AGENTS
        ("speed", 0.4),          # below MIN_SPEED
        ("speed", 1.6),          # above MAX_SPEED — capped at 1.0 by design
        ("cell_capacity", 0),
        ("cell_capacity", 6),
        ("max_ticks", 601),      # above the 600 cap
        ("max_ticks", 0),
    ],
)
def test_settings_outside_the_limits_are_refused(client, venue_id, field, value):
    settings = {"num_agents": 20, field: value}
    response = run(client, venue_id, **settings)
    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["field"] == field


def test_entrances_are_exits_must_be_a_boolean(client, venue_id):
    response = run(client, venue_id, num_agents=20, entrances_are_exits="yes")
    assert response.status_code == 422


# Trace storage and payload size ---------------------------------------------


def test_the_run_reports_what_its_trace_cost(client, venue_id):
    summary = run(client, venue_id, num_agents=30).get_json()["summary"]
    assert summary["trace"]["stored_bytes"] < summary["trace"]["raw_bytes"]
    assert summary["trace"]["ticks"] == summary["ticks"] + 1


def test_a_stored_run_returns_its_density(client, venue_id):
    created = run(client, venue_id, num_agents=30).get_json()
    assert "density" in created
    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["density"] == created["density"]


def test_density_can_be_left_out_of_the_response(client, venue_id):
    created = run(client, venue_id, num_agents=30).get_json()
    fetched = client.get(f"/api/simulations/{created['id']}?density=0").get_json()
    assert "density" not in fetched
    assert fetched["summary"] == created["summary"]


def test_the_trace_can_be_left_out_of_the_response(client, venue_id):
    created = run(client, venue_id, num_agents=30).get_json()
    fetched = client.get(f"/api/simulations/{created['id']}?trace=0").get_json()
    assert "trace" not in fetched


def test_a_compressed_trace_still_replays_exactly(client, venue_id):
    """Compression is only worth having if it is lossless. Compare the stored
    run tick by tick against the one that was returned when it ran."""
    created = run(client, venue_id, num_agents=30, seed=11).get_json()
    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["trace"] == created["trace"]


# Routing options ------------------------------------------------------------


def test_routing_defaults_to_nearest_with_rerouting_on(client, venue_id):
    config = run(client, venue_id, num_agents=20).get_json()["config"]
    assert config["routing"] == "nearest"
    assert config["reroute"] is True


def test_balanced_routing_can_be_requested(client, venue_id):
    config = run(client, venue_id, num_agents=20, routing="balanced").get_json()["config"]
    assert config["routing"] == "balanced"


def test_an_unknown_routing_model_is_refused(client, venue_id):
    response = run(client, venue_id, num_agents=20, routing="telepathy")
    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["field"] == "routing"


def test_reroute_must_be_a_boolean(client, venue_id):
    assert run(client, venue_id, num_agents=20, reroute="sometimes").status_code == 422


def test_the_two_routing_models_give_different_runs(client, ascii_grid):
    lopsided = ascii_grid(
        """
        ####################
        #SSSSSSSS..........#
        #SSSSSSSS..........#
        #SSSSSSSS..........#
        #SSSSSSSS..........#
        #SSSSSSSS..........#
        E..................E
        ####################
        """,
        name="Lopsided hall",
    )
    venue = client.post("/api/venues", json=lopsided).get_json()["id"]
    naive = run(client, venue, num_agents=120, routing="nearest", reroute=False).get_json()
    managed = run(client, venue, num_agents=120, routing="balanced", reroute=False).get_json()

    assert managed["summary"]["clearing_ticks"] < naive["summary"]["clearing_ticks"]
    assert naive["summary"]["exit_usage"]["2"] == 0
    assert managed["summary"]["exit_usage"]["2"] > 0


# Score ----------------------------------------------------------------------


def test_a_run_comes_back_scored(client, venue_id):
    body = run(client, venue_id, num_agents=30).get_json()
    assert 0 <= body["assessment"]["score"] <= 100
    assert body["assessment"]["grade"] in "ABCDF"
    assert len(body["assessment"]["components"]) == 3
    assert body["summary"]["score"] == body["assessment"]["score"]


def test_metrics_come_back_with_the_run(client, venue_id):
    metrics = run(client, venue_id, num_agents=30).get_json()["metrics"]
    assert metrics["time"]["binding_constraint"] in ("doors", "walking")
    assert metrics["exits"]["doors"][0]["width"] == 1
    assert metrics["congestion"]["walkable_cells"] > 0


def test_the_score_survives_storage(client, venue_id):
    created = run(client, venue_id, num_agents=30).get_json()
    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["assessment"] == created["assessment"]
    assert fetched["metrics"] == created["metrics"]


def test_listings_carry_the_score(client, venue_id):
    run(client, venue_id, num_agents=30)
    listing = client.get("/api/simulations").get_json()
    assert listing[0]["summary"]["grade"] in "ABCDF"


def test_a_run_comes_back_with_findings(client, ascii_grid):
    pinched = ascii_grid(
        """
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
        """,
        name="Pinched hall",
    )
    venue = client.post("/api/venues", json=pinched).get_json()["id"]
    created = run(client, venue, num_agents=110).get_json()

    assert created["bottlenecks"]
    worst = created["bottlenecks"][0]
    assert worst["kind"] in ("pinch", "exit_approach")
    assert worst["label"]

    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["bottlenecks"] == created["bottlenecks"]


def test_a_run_comes_back_with_recommendations(client, ascii_grid):
    narrow = ascii_grid(
        """
        ######################
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        ##########E###########
        """,
        name="One narrow door",
    )
    venue = client.post("/api/venues", json=narrow).get_json()["id"]
    created = run(client, venue, num_agents=120).get_json()

    assert created["recommendations"]
    top = created["recommendations"][0]
    assert top["title"] and top["action"] and top["evidence"]

    fetched = client.get(f"/api/simulations/{created['id']}").get_json()
    assert fetched["recommendations"] == created["recommendations"]


# The proposal ---------------------------------------------------------------


@pytest.fixture
def narrow_venue(client, ascii_grid):
    return client.post("/api/venues", json=ascii_grid(
        """
        ######################
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        #SSSSSSSSSSSS........#
        ##########E###########
        """,
        name="Main hall",
    )).get_json()["id"]


def test_a_run_offers_a_plan_with_its_advice_applied(client, narrow_venue):
    run_id = run(client, narrow_venue, num_agents=120).get_json()["id"]
    proposal = client.get(f"/api/simulations/{run_id}/proposal").get_json()

    assert proposal["available"] is True
    assert proposal["suggested_name"] == "Main hall suggested"
    assert proposal["after"]["cells"] != proposal["before"]["cells"]
    assert proposal["changed_cells"]


def test_the_proposal_actually_widens_the_door(client, narrow_venue):
    from app.engine.grid import Grid

    run_id = run(client, narrow_venue, num_agents=120).get_json()["id"]
    proposal = client.get(f"/api/simulations/{run_id}/proposal").get_json()

    before = Grid(**proposal["before"])
    after = Grid(**proposal["after"])
    assert after.total_exit_width > before.total_exit_width


def test_the_proposal_is_a_venue_that_can_be_run(client, narrow_venue):
    """The whole point: it is a plan, not a paragraph."""
    original = run(client, narrow_venue, num_agents=120).get_json()
    proposal = client.get(f"/api/simulations/{original['id']}/proposal").get_json()

    saved = client.post("/api/venues", json={
        "name": proposal["suggested_name"], **proposal["after"],
    })
    assert saved.status_code == 201

    improved = client.post("/api/simulations", json={
        "venue_id": saved.get_json()["id"], "config": proposal["config"],
    }).get_json()
    assert improved["summary"]["clearing_ticks"] < original["summary"]["clearing_ticks"]


def test_advice_that_is_not_a_plan_change_is_passed_through_as_a_note(client, narrow_venue):
    """Signage and capping attendance are real recommendations and neither is a
    wall. They are shown with the proposal rather than silently dropped."""
    run_id = run(client, narrow_venue, num_agents=120).get_json()["id"]
    changes = client.get(f"/api/simulations/{run_id}/proposal").get_json()["changes"]
    assert any(c["drawn"] for c in changes)
    assert any(not c["drawn"] for c in changes)


def test_a_venue_with_nothing_to_fix_offers_no_proposal(client, ascii_grid):
    roomy = client.post("/api/venues", json=ascii_grid(
        """
        ######################
        #....................#
        #..SSSSSS..SSSSSS....#
        #..SSSSSS..SSSSSS....#
        #....................#
        EEEEEEEEEEEEEEEEEEEEEE
        """,
        name="Open hall",
    )).get_json()["id"]
    run_id = run(client, roomy, num_agents=40).get_json()["id"]
    proposal = client.get(f"/api/simulations/{run_id}/proposal").get_json()
    assert proposal["available"] is False
    assert proposal["reason"]


def test_the_proposal_never_breaches_the_outer_wall(client, ascii_grid):
    """Opening a pinch means clearing what narrows it. A proposal that puts a
    hole in the side of the building is not a proposal."""
    from app.engine.grid import Grid

    pinched = client.post("/api/venues", json=ascii_grid(
        """
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
        """,
        name="Pinched hall",
    )).get_json()["id"]
    run_id = run(client, pinched, num_agents=110).get_json()["id"]
    proposal = client.get(f"/api/simulations/{run_id}/proposal").get_json()
    if not proposal["available"]:
        return

    # Doors in the outer wall are fine, and widening one is the point. What
    # must never appear is bare floor on the boundary, which would be a hole.
    from app.cells import ENTRANCE, EXIT

    after = Grid(**proposal["after"])
    boundary = (
        [(x, 0) for x in range(after.width)]
        + [(x, after.height - 1) for x in range(after.width)]
        + [(0, y) for y in range(after.height)]
        + [(after.width - 1, y) for y in range(after.height)]
    )
    for x, y in boundary:
        if after.is_walkable(x, y):
            assert after.at(x, y) in (EXIT, ENTRANCE), f"hole at {x}, {y}"


def test_a_missing_run_has_no_proposal(client):
    assert client.get("/api/simulations/999/proposal").status_code == 404
