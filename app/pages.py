"""Server-rendered page shells. The JavaScript modules do the work from here.

Editor, simulate, results and compare pages are added on their scheduled days.
"""

from flask import Blueprint, render_template

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
    """A blank plan. Saving is wired up on Day 4."""
    venue = {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT, "cells": None}
    return render_template("editor.html", venue=venue, palette=_palette())
