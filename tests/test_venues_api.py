"""Day 2 acceptance: venues can be created, read, replaced and deleted, and
every way of getting it wrong produces a useful error."""

import pytest


@pytest.fixture
def room(ascii_grid):
    """A minimal valid venue: walls around the edge, a spawn, an exit."""
    return ascii_grid(
        """
        ######
        #S..E#
        #....#
        #....#
        ######
        """,
        name="Small hall",
    )


def _create(client, venue):
    return client.post("/api/venues", json=venue)


# Create ---------------------------------------------------------------------


def test_create_returns_the_stored_venue(client, room):
    response = _create(client, room)
    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "Small hall"
    assert body["width"] == 6
    assert body["height"] == 5
    assert body["cells"] == room["cells"]
    assert isinstance(body["id"], int)
    assert body["created_at"] and body["updated_at"]


def test_create_sets_a_location_header(client, room):
    response = _create(client, room)
    venue_id = response.get_json()["id"]
    assert response.headers["Location"].endswith(f"/api/venues/{venue_id}")


def test_created_venue_appears_in_the_listing_without_cells(client, room):
    _create(client, room)
    listing = client.get("/api/venues").get_json()
    assert len(listing) == 1
    assert listing[0]["name"] == "Small hall"
    assert "cells" not in listing[0]


def test_name_is_trimmed(client, room):
    room["name"] = "  Padded name  "
    assert _create(client, room).get_json()["name"] == "Padded name"


# Read -----------------------------------------------------------------------


def test_get_returns_the_full_venue(client, room):
    venue_id = _create(client, room).get_json()["id"]
    body = client.get(f"/api/venues/{venue_id}").get_json()
    assert body["cells"] == room["cells"]


def test_get_missing_venue_is_404(client):
    response = client.get("/api/venues/999")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


# Replace --------------------------------------------------------------------


def test_put_replaces_every_field(client, room, ascii_grid):
    venue_id = _create(client, room).get_json()["id"]
    bigger = ascii_grid(
        """
        #######
        #S...E#
        #.....#
        #.....#
        #######
        """,
        name="Bigger hall",
    )
    response = client.put(f"/api/venues/{venue_id}", json=bigger)
    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == venue_id
    assert body["name"] == "Bigger hall"
    assert body["width"] == 7
    assert body["height"] == 5
    assert body["cells"] == bigger["cells"]


def test_put_missing_venue_is_404(client, room):
    response = client.put("/api/venues/999", json=room)
    assert response.status_code == 404


def test_put_validates_before_it_writes(client, room):
    venue_id = _create(client, room).get_json()["id"]
    client.put(f"/api/venues/{venue_id}", json={**room, "cells": "000"})
    unchanged = client.get(f"/api/venues/{venue_id}").get_json()
    assert unchanged["cells"] == room["cells"]


# Delete ---------------------------------------------------------------------


def test_delete_removes_the_venue(client, room):
    venue_id = _create(client, room).get_json()["id"]
    assert client.delete(f"/api/venues/{venue_id}").status_code == 204
    assert client.get(f"/api/venues/{venue_id}").status_code == 404
    assert client.get("/api/venues").get_json() == []


def test_delete_missing_venue_is_404(client):
    assert client.delete("/api/venues/999").status_code == 404


# Validation -----------------------------------------------------------------


def _problem_fields(response):
    return {problem["field"] for problem in response.get_json()["error"]["details"]}


def test_missing_everything_reports_every_field_at_once(client):
    response = client.post("/api/venues", json={})
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "VALIDATION"
    assert _problem_fields(response) == {"name", "width", "height", "cells"}


def test_cell_string_length_must_match_the_dimensions(client, room):
    response = client.post("/api/venues", json={**room, "cells": room["cells"][:-1]})
    assert response.status_code == 422
    assert "cells" in _problem_fields(response)
    assert "30" in response.get_json()["error"]["details"][0]["message"]


def test_unknown_cell_codes_are_rejected(client, room):
    broken = "9" + room["cells"][1:]
    response = client.post("/api/venues", json={**room, "cells": broken})
    assert response.status_code == 422
    assert "cells" in _problem_fields(response)


@pytest.mark.parametrize(
    "field,value",
    [
        ("width", 4),      # below MIN_WIDTH
        ("width", 81),     # above MAX_WIDTH
        ("height", 4),     # below MIN_HEIGHT
        ("height", 61),    # above MAX_HEIGHT
    ],
)
def test_dimensions_outside_the_limits_are_rejected(client, room, field, value):
    response = client.post("/api/venues", json={**room, field: value})
    assert response.status_code == 422
    assert field in _problem_fields(response)


def test_dimensions_must_be_whole_numbers(client, room):
    response = client.post("/api/venues", json={**room, "width": "six"})
    assert response.status_code == 422
    assert "width" in _problem_fields(response)


def test_blank_name_is_rejected(client, room):
    response = client.post("/api/venues", json={**room, "name": "   "})
    assert response.status_code == 422
    assert "name" in _problem_fields(response)


def test_overlong_name_is_rejected(client, room):
    response = client.post("/api/venues", json={**room, "name": "x" * 101})
    assert response.status_code == 422
    assert "name" in _problem_fields(response)


def test_non_json_body_is_rejected(client):
    response = client.post("/api/venues", data="not json", content_type="text/plain")
    assert response.status_code == 422
    assert "body" in _problem_fields(response)


def test_json_array_body_is_rejected(client):
    response = client.post("/api/venues", json=["not", "a", "venue"])
    assert response.status_code == 422
    assert "body" in _problem_fields(response)


def test_nothing_is_stored_when_validation_fails(client):
    client.post("/api/venues", json={"name": "Bad"})
    assert client.get("/api/venues").get_json() == []
