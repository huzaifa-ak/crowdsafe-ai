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
