"""SQLite connection handling.

One connection per request, stored on `g` and closed by the teardown hook.
`init_db` is idempotent (the schema uses IF NOT EXISTS) so it can run on every
boot, which is what keeps a fresh Render deploy working without a migration step.
"""

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exception=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app) -> None:
    """Apply the schema. Safe to call on every start."""
    path = Path(app.config["DATABASE_PATH"])
    if path.parent != Path("") and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(app.config["DATABASE_PATH"])
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def register(app) -> None:
    app.teardown_appcontext(close_db)
