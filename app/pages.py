"""Server-rendered page shells. The JavaScript modules do the work from here.

Editor, simulate, results and compare pages are added on their scheduled days.
"""

from flask import Blueprint, abort, render_template

from .cells import CELL_NAMES, PALETTE_ORDER
from .db import repository

bp = Blueprint("pages", __name__)

DEFAULT_WIDTH = 30
DEFAULT_HEIGHT = 20


def _palette():
    """(code, label) pairs in the order the editor shows them."""
    return [(code, CELL_NAMES[code].capitalize()) for code in PALETTE_ORDER]


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", venues=repository.list_venues())


@bp.get("/editor")
def new_editor():
    """A blank plan. It has no id until the first save."""
    venue = {"id": None, "name": "", "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT,
             "cells": None}
    return render_template("editor.html", venue=venue, palette=_palette())


@bp.get("/simulate/<int:venue_id>")
def simulate_venue(venue_id: int):
    venue = repository.get_venue(venue_id)
    if venue is None:
        abort(404)
    return render_template("simulate.html", venue=venue)


@bp.get("/compare")
def compare():
    """Two runs side by side. The runs are listed server-side so the page has
    something to choose from before any JavaScript runs."""
    return render_template("compare.html", runs=repository.list_simulations())


@bp.get("/editor/<int:venue_id>")
def edit_venue(venue_id: int):
    """An existing venue. The grid is rendered into the page rather than fetched,
    so the plan is on screen in one round trip instead of two."""
    venue = repository.get_venue(venue_id)
    if venue is None:
        abort(404)
    return render_template("editor.html", venue=venue, palette=_palette())
