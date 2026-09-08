"""Page routes render. The editor's behaviour lives in JavaScript; these tests
only check that the shell it needs is present and correctly parameterised."""


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
