"""Page routes render. The editor's behaviour lives in JavaScript; these tests
only check that the shell it needs is present and correctly parameterised."""

import re


def test_editor_page_renders_a_blank_plan(client):
    response = client.get("/editor")
    assert response.status_code == 200
    body = response.data.decode()
    assert 'id="grid-canvas"' in body
    assert 'data-width="30"' in body
    assert 'data-height="20"' in body
    # A blank plan carries no cells; the browser builds the empty room.
    assert "data-cells" not in body


def test_editor_offers_every_cell_type(client):
    body = client.get("/editor").data.decode()
    for code in "012345":
        assert f'data-cell="{code}"' in body


def test_editor_loads_its_module(client):
    assert 'type="module"' in client.get("/editor").data.decode()


def test_dashboard_links_to_the_editor(client):
    assert '/editor' in client.get("/").data.decode()


def _create_venue(client, name="Main hall"):
    return client.post(
        "/api/venues",
        json={"name": name, "width": 6, "height": 5,
              "cells": "111111" "150041" "100001" "100001" "111111"},
    ).get_json()


def test_editor_for_an_existing_venue_embeds_its_grid(client):
    venue = _create_venue(client)
    body = client.get(f"/editor/{venue['id']}").data.decode()
    assert f'data-venue-id="{venue["id"]}"' in body
    assert f'data-cells="{venue["cells"]}"' in body
    assert 'value="Main hall"' in body


def test_editor_for_a_missing_venue_is_404(client):
    assert client.get("/editor/999").status_code == 404


def test_blank_editor_has_no_venue_id(client):
    body = client.get("/editor").data.decode()
    assert "data-venue-id" not in body


def test_dashboard_open_link_points_at_the_venue(client):
    venue = _create_venue(client)
    assert f'/editor/{venue["id"]}' in client.get("/").data.decode()


def test_editor_has_save_controls(client):
    body = client.get("/editor").data.decode()
    assert 'id="venue-name"' in body
    assert 'id="save"' in body
    assert 'id="save-errors"' in body


def test_simulate_page_embeds_the_venue(client):
    venue = _create_venue(client, name="Hall")
    body = client.get(f"/simulate/{venue['id']}").data.decode()
    assert f'data-venue-id="{venue["id"]}"' in body
    assert f'data-cells="{venue["cells"]}"' in body
    assert 'id="grid-canvas"' in body


def test_simulate_page_has_playback_controls(client):
    venue = _create_venue(client)
    body = client.get(f"/simulate/{venue['id']}").data.decode()
    for control in ('id="play"', 'id="scrubber"', 'id="rate"', 'id="run"'):
        assert control in body


def test_simulate_page_offers_both_routing_models(client):
    venue = _create_venue(client)
    body = client.get(f"/simulate/{venue['id']}").data.decode()
    assert 'value="nearest"' in body
    assert 'value="balanced"' in body


def test_simulate_page_for_a_missing_venue_is_404(client):
    assert client.get("/simulate/999").status_code == 404


def test_dashboard_links_to_running_a_venue(client):
    venue = _create_venue(client)
    assert f'/simulate/{venue["id"]}' in client.get("/").data.decode()


def test_simulate_page_offers_every_heatmap_mode(client):
    venue = _create_venue(client)
    body = client.get(f"/simulate/{venue['id']}").data.decode()
    for mode in ("none", "peak", "duration", "traffic"):
        assert f'value="{mode}"' in body
    assert 'id="legend"' in body
    assert 'id="cell-readout"' in body


def test_editor_links_to_running_a_saved_venue(client):
    venue = _create_venue(client)
    body = client.get(f"/editor/{venue['id']}").data.decode()
    assert f'/simulate/{venue["id"]}' in body
    assert 'id="run-link"' in body


def test_a_blank_editor_hides_the_run_link(client):
    """Nothing to run until it has been saved, so the link starts hidden."""
    body = client.get("/editor").data.decode()
    tag = re.search(r'<a[^>]*id="run-link".*?>', body, re.S).group(0)
    assert "hidden" in tag
    assert "/simulate/" not in tag


def test_the_dashboard_offers_a_delete_control(client):
    venue = _create_venue(client, name="Main hall")
    body = client.get("/").data.decode()
    assert f'data-delete="{venue["id"]}"' in body
    assert 'data-name="Main hall"' in body
    assert "js/dashboard.js" in body


def test_deleting_a_venue_leaves_its_runs_readable(client, ascii_grid):
    """Each run stored the plan as it was at the time, so a result outlives the
    venue it came from."""
    venue = client.post("/api/venues", json=ascii_grid(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ######EE##
        """,
        name="Hall",
    )).get_json()
    run = client.post("/api/simulations", json={
        "venue_id": venue["id"], "config": {"num_agents": 20, "seed": 42},
    }).get_json()

    assert client.delete(f"/api/venues/{venue['id']}").status_code == 204

    fetched = client.get(f"/api/simulations/{run['id']}").get_json()
    assert fetched["venue_snapshot"]["cells"] == venue["cells"]
    assert fetched["summary"]["clearing_ticks"] == run["summary"]["clearing_ticks"]


def test_the_venue_list_summarises_each_plan(client, ascii_grid):
    """Enough to tell two venues apart without opening either."""
    client.post("/api/venues", json=ascii_grid(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ###EEEE###
        """,
        name="Main hall",
    ))
    body = client.get("/").data.decode()
    assert "10 × 6 m" in body
    assert "4 m" in body          # exit width
    assert ">36<" in body         # capacity: 12 spawn cells at 3 per m²


def test_a_venue_with_no_exit_is_flagged_in_the_list(client, ascii_grid):
    """The list is where somebody notices a plan they cannot run, rather than
    finding out when the simulation refuses it."""
    client.post("/api/venues", json=ascii_grid(
        """
        ##########
        #SSSS....#
        #SSSS....#
        #SSSS....#
        #........#
        ##########
        """,
        name="Sealed room",
    ))
    assert "needs an exit" in client.get("/").data.decode()


def test_each_row_offers_run_edit_and_delete(client):
    venue = _create_venue(client)
    body = client.get("/").data.decode()
    assert f'/simulate/{venue["id"]}' in body
    assert f'/editor/{venue["id"]}' in body
    assert f'data-delete="{venue["id"]}"' in body


def test_the_proposal_dialog_shows_both_plans(client):
    venue = _create_venue(client)
    body = client.get(f"/simulate/{venue['id']}").data.decode()
    assert 'id="proposal-before"' in body
    assert 'id="proposal-after"' in body
