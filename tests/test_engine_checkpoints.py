"""Checkpoints and the VIP area.

A checkpoint is a run of cells that passes one person per cell per tick, like a
doorway. What makes it more than a slow doorway is what sits behind it: any
part of the floor that can only be reached by passing a checkpoint is a
restricted area, worked out from the plan rather than painted separately.

VIPs have their places in that area and everybody else does not, so who goes
through security is decided by where they are going rather than by a flag on
the person. Nobody checks anything on the way out, so an evacuation walks
straight over a checkpoint and ignores the restriction.
"""

import pytest

from app.engine.grid import Grid
from app.engine.simulation import ArrivalSimulation, SimulationConfig, simulate

CHARS = {".": "0", "#": "1", "B": "2", "N": "3", "E": "4", "S": "5", "C": "6"}


def grid_from(rows: list[str]) -> Grid:
    assert len({len(row) for row in rows}) == 1, "ragged layout"
    return Grid(len(rows[0]), len(rows),
                "".join(CHARS[c] for row in rows for c in row))


def venue(lanes: int = 2) -> Grid:
    """A general floor, and a VIP box reachable only through a checkpoint."""
    # The gate sits under the box interior (x=18 onward), not under its wall.
    gate = "#" + "C" * lanes + "#" * (5 - lanes)
    return grid_from([
        "##########################",
        "#........................#",
        "#..SSSSSSSSSSSS..######..#",
        "#..SSSSSSSSSSSS..#SSSS#..#",
        "#..SSSSSSSSSSSS..#SSSS#..#",
        "#................#SSSS#..#",
        "#................" + gate + "..#",
        "#........................#",
        "###NNNN#############EEEE##",
    ])


OPEN_HALL = [
    "##########################",
    "#........................#",
    "#..SSSSSSSSSSSSSSSSSSSS..#",
    "#..SSSSSSSSSSSSSSSSSSSS..#",
    "#........................#",
    "###NNNN#############EEEE##",
]


def arrival(grid, **overrides):
    settings = {"mode": "arrival", "num_agents": 80, "seed": 42, "vip_count": 12}
    settings.update(overrides)
    return ArrivalSimulation(grid, SimulationConfig(**settings))


# The restricted area ---------------------------------------------------------


def test_a_checkpoint_creates_a_restricted_area_behind_it():
    grid = venue()
    assert grid.restricted_spawn_cells
    assert grid.general_spawn_cells
    assert not set(grid.restricted_spawn_cells) & set(grid.general_spawn_cells)


def test_the_restricted_area_is_worked_out_from_the_plan():
    """Nobody paints it. It is whatever you cannot reach without passing a
    checkpoint, which is what a restricted area means."""
    grid = venue()
    for cell in grid.restricted_spawn_cells:
        assert cell not in grid.general_spawn_cells
    assert len(grid.restricted_spawn_cells) == 12


def test_a_plan_with_no_checkpoints_has_no_restricted_area():
    grid = grid_from(OPEN_HALL)
    assert grid.restricted_cells == set()
    assert grid.general_spawn_cells == grid.spawn_cells


def test_a_checkpoint_that_gates_nothing_restricts_nothing():
    """Painted in the open, with a way round it, it is just a slow patch of
    floor."""
    rows = list(OPEN_HALL)
    rows[4] = "#......CC................#"
    grid = grid_from(rows)
    assert grid.checkpoints
    assert not grid.restricted_spawn_cells


def test_adjacent_checkpoint_cells_are_one_station():
    grid = venue(lanes=2)
    assert len(grid.checkpoints) == 1
    assert grid.checkpoints[0].width == 2
    assert grid.total_checkpoint_width == 2


# Who goes where --------------------------------------------------------------


def test_vips_are_given_places_in_the_restricted_area():
    sim = arrival(venue(), vip_count=12)
    sim.run()
    restricted = set(sim.grid.restricted_spawn_cells)
    for agent in sim.agents:
        if agent.is_vip:
            assert agent.target in restricted


def test_everybody_else_is_given_places_outside_it():
    sim = arrival(venue(), vip_count=12)
    sim.run()
    general = set(sim.grid.general_spawn_cells)
    for agent in sim.agents:
        if not agent.is_vip:
            assert agent.target in general


def test_general_admission_never_enters_the_restricted_area():
    """The point of the feature. A checkpoint cell is walkable, so without care
    the security lane becomes a shortcut and the area behind it a through
    route."""
    sim = arrival(venue(), vip_count=12)
    sim.run()
    off_limits = set(sim.grid.restricted_cells) | set(sim.grid.checkpoint_cells)
    for agent in sim.agents:
        if agent.is_vip:
            continue
        assert not (set(agent.path) & off_limits)


def test_every_vip_passes_a_checkpoint():
    sim = arrival(venue(), vip_count=12)
    result = sim.run()
    assert result.status == "complete"
    assert sum(result.checkpoint_usage.values()) == result.vip_count == 12


def test_no_vips_means_no_checkpoint_use():
    result = arrival(venue(), vip_count=0).run()
    assert result.vip_count == 0
    assert sum(result.checkpoint_usage.values()) == 0


def test_a_narrower_gate_takes_longer_to_admit_the_vips():
    one = arrival(venue(lanes=1), vip_count=24).run()
    two = arrival(venue(lanes=2), vip_count=24).run()
    assert one.vip_clearing_ticks > two.vip_clearing_ticks


def test_checkpoints_pass_one_person_per_cell_per_tick():
    result = arrival(venue(lanes=1), vip_count=24).run()
    assert result.vip_clearing_ticks >= 24


def test_a_ticketed_arrival_is_deterministic():
    first = arrival(venue(), vip_count=12, seed=9).run()
    second = arrival(venue(), vip_count=12, seed=9).run()
    assert first.trace == second.trace
    assert first.checkpoint_usage == second.checkpoint_usage


# Evacuation ------------------------------------------------------------------


def test_nobody_is_checked_on_the_way_out():
    result = simulate(venue(), SimulationConfig(num_agents=80, seed=42, vip_count=12))
    assert result.vip_count == 0
    assert result.checkpoint_usage == {}


def test_the_restricted_area_still_empties():
    """People are in it when the alarm goes, and a checkpoint is not a wall."""
    result = simulate(venue(), SimulationConfig(num_agents=80, seed=42))
    assert result.status == "complete"
    assert result.evacuated == 80


# Through the API -------------------------------------------------------------


@pytest.fixture
def restricted_venue(client):
    grid = venue()
    return client.post("/api/venues", json={
        "name": "Arena with a box", "width": grid.width, "height": grid.height,
        "cells": grid.cells,
    }).get_json()["id"]


@pytest.fixture
def open_venue(client):
    grid = grid_from(OPEN_HALL)
    return client.post("/api/venues", json={
        "name": "Open hall", "width": grid.width, "height": grid.height,
        "cells": grid.cells,
    }).get_json()["id"]


def run(client, venue_id, **config):
    settings = {"mode": "arrival", "num_agents": 80, "seed": 42}
    settings.update(config)
    return client.post("/api/simulations",
                       json={"venue_id": venue_id, "config": settings})


def test_the_api_reports_the_vip_split(client, restricted_venue):
    summary = run(client, restricted_venue, vip_count=12).get_json()["summary"]
    assert summary["vip_count"] == 12
    assert summary["vip_places"] == 36
    assert summary["general_places"] == 108
    assert sum(summary["checkpoint_usage"].values()) == 12


def test_vips_without_a_checkpoint_are_refused(client, open_venue):
    response = run(client, open_venue, vip_count=5)
    assert response.status_code == 422
    assert "checkpoint" in response.get_json()["error"]["details"][0]["message"]


def test_more_vips_than_the_area_holds_is_refused(client, restricted_venue):
    response = run(client, restricted_venue, vip_count=40)
    assert response.status_code == 422
    detail = response.get_json()["error"]["details"][0]
    assert detail["field"] == "vip_count"
    assert "36" in detail["message"]


def test_the_vip_count_is_ignored_on_the_way_out(client, restricted_venue):
    """Rather than refused: the setting belongs to the venue, and switching
    mode to compare should not need it cleared first."""
    body = run(client, restricted_venue, mode="evacuation", vip_count=12).get_json()
    assert body["config"]["vip_count"] == 0
    assert body["summary"]["vip_count"] == 0


def test_a_negative_vip_count_is_refused(client, restricted_venue):
    response = run(client, restricted_venue, vip_count=-1)
    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["field"] == "vip_count"


def test_the_editor_offers_the_checkpoint_tool(client):
    body = client.get("/editor").data.decode()
    assert 'data-cell="6"' in body
    assert "Checkpoint" in body


def test_the_simulate_page_offers_a_vip_count(client, restricted_venue):
    body = client.get(f"/simulate/{restricted_venue}").data.decode()
    assert 'id="vip-count"' in body
