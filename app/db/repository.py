"""Thin data-access functions. No business logic, no Flask objects in or out.

Day 2 adds create/update/delete; Day 1 needs listing so that the dashboard and
`GET /api/venues` have something real to read.
"""

from . import get_db


def list_venues() -> list[dict]:
    rows = get_db().execute(
        """
        SELECT id, name, width, height, created_at, updated_at
        FROM venues
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_venue(venue_id: int) -> dict | None:
    row = get_db().execute(
        "SELECT id, name, width, height, cells, created_at, updated_at "
        "FROM venues WHERE id = ?",
        (venue_id,),
    ).fetchone()
    return dict(row) if row else None


def count_venues() -> int:
    return get_db().execute("SELECT COUNT(*) AS n FROM venues").fetchone()["n"]
