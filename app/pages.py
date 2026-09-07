"""Server-rendered page shells. The JavaScript modules do the work from here.

Editor, simulate, results and compare pages are added on their scheduled days.
"""

from flask import Blueprint, render_template

from .db import repository

bp = Blueprint("pages", __name__)


@bp.get("/")
def dashboard():
    return render_template("dashboard.html", venues=repository.list_venues())
