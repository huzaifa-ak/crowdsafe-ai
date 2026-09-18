"""Day 1 acceptance: the app boots, the schema is applied, and the API answers."""

import sqlite3


def test_health_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_venue_list_is_empty_on_a_fresh_database(client):
    response = client.get("/api/venues")
    assert response.status_code == 200
    assert response.get_json() == []


def test_schema_creates_all_four_tables(app):
    connection = sqlite3.connect(app.config["DATABASE_PATH"])
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert {"venues", "simulations", "results", "comparisons"} <= names


def test_init_db_is_idempotent(app):
    from app.db import init_db

    init_db(app)  # a second boot against the same file must not raise
    init_db(app)


def test_dashboard_renders_the_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Nothing drawn yet" in response.data


def test_unknown_api_route_returns_the_error_shape(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    body = response.get_json()
    assert set(body["error"]) == {"code", "message", "details"}


def test_ascii_grid_fixture_encodes_cells(ascii_grid):
    venue = ascii_grid(
        """
        #####
        #S.E#
        #####
        """
    )
    assert venue["width"] == 5
    assert venue["height"] == 3
    assert venue["cells"] == "11111" "15041" "11111"


def test_javascript_is_served_as_a_module_script(client):
    """Windows registers .js as text/plain, and a browser will not execute a
    module script served with that type — the page loads and quietly does
    nothing. Linux gets it right, so this only breaks on one developer's
    machine and never in production."""
    response = client.get("/static/js/editor.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["Content-Type"]


def test_stylesheets_are_served_as_css(client):
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["Content-Type"]
