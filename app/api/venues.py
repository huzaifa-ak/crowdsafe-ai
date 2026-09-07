"""Venue routes.

    GET    /api/venues        list, without cell data
    POST   /api/venues        create
    GET    /api/venues/<id>   full venue including cells
    PUT    /api/venues/<id>   replace
    DELETE /api/venues/<id>   remove

    POST   /api/venues/validate    layout report for an unsaved venue
    GET    /api/venues/<id>/validate layout report for a saved one
"""

from flask import Blueprint, jsonify, request, url_for

from ..db import repository
from ..engine.grid import Grid
from ..engine.layout import inspect
from .errors import NotFoundError, ValidationError
from .schemas import validate_venue

bp = Blueprint("venues", __name__, url_prefix="/api/venues")


def _json_body():
    """Parse the request body, refusing anything that is not JSON."""
    body = request.get_json(silent=True)
    if body is None:
        raise ValidationError(
            "Expected a JSON body.",
            [{"field": "body", "message": "send JSON with Content-Type: application/json"}],
        )
    return body


def _venue_or_404(venue_id: int) -> dict:
    venue = repository.get_venue(venue_id)
    if venue is None:
        raise NotFoundError(f"No venue with id {venue_id}.")
    return venue


@bp.get("")
def list_venues():
    return jsonify(repository.list_venues())


@bp.post("")
def create_venue():
    fields = validate_venue(_json_body())
    venue = repository.create_venue(**fields)
    response = jsonify(venue)
    response.status_code = 201
    response.headers["Location"] = url_for("venues.get_venue", venue_id=venue["id"])
    return response


@bp.post("/validate")
def validate_unsaved_venue():
    """Report on a venue the editor has not saved yet.

    A malformed payload is still a 422; a well-formed venue that cannot be
    evacuated is a 200 with `ok: false`, because there is nothing wrong with
    the request — only with the layout.
    """
    fields = validate_venue(_json_body())
    return jsonify(inspect(Grid(fields["width"], fields["height"], fields["cells"])))


@bp.get("/<int:venue_id>/validate")
def validate_saved_venue(venue_id: int):
    venue = _venue_or_404(venue_id)
    return jsonify(inspect(Grid.from_venue(venue)))


@bp.get("/<int:venue_id>")
def get_venue(venue_id: int):
    return jsonify(_venue_or_404(venue_id))


@bp.put("/<int:venue_id>")
def replace_venue(venue_id: int):
    fields = validate_venue(_json_body())
    venue = repository.update_venue(venue_id, **fields)
    if venue is None:
        raise NotFoundError(f"No venue with id {venue_id}.")
    return jsonify(venue)


@bp.delete("/<int:venue_id>")
def delete_venue(venue_id: int):
    if not repository.delete_venue(venue_id):
        raise NotFoundError(f"No venue with id {venue_id}.")
    return "", 204
