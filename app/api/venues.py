"""Venue routes.

    GET    /api/venues        list, without cell data
    POST   /api/venues        create
    GET    /api/venues/<id>   full venue including cells
    PUT    /api/venues/<id>   replace
    DELETE /api/venues/<id>   remove

`/validate` arrives on Day 5, once the engine can answer questions about
reachability rather than just shape.
"""

from flask import Blueprint, jsonify, request, url_for

from ..db import repository
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
