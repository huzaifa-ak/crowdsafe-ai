"""Thin data-access functions. No business logic, no Flask objects in or out.

List responses deliberately omit `cells`: a dashboard listing twenty venues
should not carry twenty grids it will never draw.
"""

from . import get_db

SUMMARY_COLUMNS = "id, name, width, height, created_at, updated_at"
FULL_COLUMNS = "id, name, width, height, cells, created_at, updated_at"


def list_venues() -> list[dict]:
    rows = get_db().execute(
        f"SELECT {SUMMARY_COLUMNS} FROM venues ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def get_venue(venue_id: int) -> dict | None:
    row = get_db().execute(
        f"SELECT {FULL_COLUMNS} FROM venues WHERE id = ?", (venue_id,)
    ).fetchone()
    return dict(row) if row else None


def create_venue(name: str, width: int, height: int, cells: str) -> dict:
    db = get_db()
    cursor = db.execute(
        "INSERT INTO venues (name, width, height, cells) VALUES (?, ?, ?, ?)",
        (name, width, height, cells),
    )
    db.commit()
    return get_venue(cursor.lastrowid)


def update_venue(venue_id: int, name: str, width: int, height: int, cells: str) -> dict | None:
    db = get_db()
    cursor = db.execute(
        """
        UPDATE venues
           SET name = ?, width = ?, height = ?, cells = ?, updated_at = datetime('now')
         WHERE id = ?
        """,
        (name, width, height, cells, venue_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        return None
    return get_venue(venue_id)


def delete_venue(venue_id: int) -> bool:
    db = get_db()
    cursor = db.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
    db.commit()
    return cursor.rowcount > 0


def count_venues() -> int:
    return get_db().execute("SELECT COUNT(*) AS n FROM venues").fetchone()["n"]
