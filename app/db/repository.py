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


# Simulations ----------------------------------------------------------------


def create_simulation(venue_id: int | None, venue_snapshot: str, config_json: str,
                      seed: int, status: str) -> int:
    """Record a run. `venue_snapshot` is the cell string as it was at run time,
    so a saved result stays meaningful after the venue is edited."""
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO simulations (venue_id, venue_snapshot, config_json, seed, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (venue_id, venue_snapshot, config_json, seed, status),
    )
    db.commit()
    return cursor.lastrowid


def create_result(simulation_id: int, metrics_json: str, trace_blob: bytes,
                  heatmap_json: str | None = None, bottlenecks_json: str | None = None,
                  recommendations_json: str | None = None) -> int:
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO results (simulation_id, metrics_json, heatmap_json,
                             bottlenecks_json, recommendations_json, trace_blob)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (simulation_id, metrics_json, heatmap_json, bottlenecks_json,
         recommendations_json, trace_blob),
    )
    db.commit()
    return cursor.lastrowid


def get_simulation(simulation_id: int) -> dict | None:
    row = get_db().execute(
        """
        SELECT s.id, s.venue_id, s.venue_snapshot, s.config_json, s.seed, s.status,
               s.created_at,
               r.id AS result_id, r.metrics_json, r.heatmap_json, r.bottlenecks_json,
               r.recommendations_json, r.trace_blob
          FROM simulations s
          LEFT JOIN results r ON r.simulation_id = s.id
         WHERE s.id = ?
        """,
        (simulation_id,),
    ).fetchone()
    return dict(row) if row else None


def list_simulations(venue_id: int | None = None) -> list[dict]:
    sql = """
        SELECT s.id, s.venue_id, s.status, s.seed, s.created_at, r.metrics_json
          FROM simulations s
          LEFT JOIN results r ON r.simulation_id = s.id
    """
    params: tuple = ()
    if venue_id is not None:
        sql += " WHERE s.venue_id = ?"
        params = (venue_id,)
    sql += " ORDER BY s.id DESC"
    return [dict(row) for row in get_db().execute(sql, params).fetchall()]
