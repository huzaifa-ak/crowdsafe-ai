"""Venue routes.

Day 1: listing only. Create/update/delete plus cell-string validation land on
Day 2, and `/validate` on Day 5 once grid.py exists.
"""

from flask import Blueprint, jsonify

from ..db import repository

bp = Blueprint("venues", __name__, url_prefix="/api/venues")


@bp.get("")
def list_venues():
    return jsonify(repository.list_venues())
