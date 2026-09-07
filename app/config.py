"""Application configuration.

Every tunable number in CrowdSafe AI lives here so that the engine, the API
validators and the docs all read from one place. Values are documented in
docs/algorithms.md; the analysis thresholds are added in Week 3.
"""

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-in-production")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "crowdsafe.db")

    # Content limits (D8). Enforced server-side on every request.
    MAX_WIDTH = _env_int("MAX_WIDTH", 80)
    MAX_HEIGHT = _env_int("MAX_HEIGHT", 60)
    MIN_WIDTH = 5
    MIN_HEIGHT = 5
    MAX_AGENTS = _env_int("MAX_AGENTS", 300)
    MIN_AGENTS = 20
    # Capped at 600 rather than 1200: a 600-tick run is 7 minutes of simulated
    # evacuation and keeps the worst-case trace inside the 2 MB budget.
    MAX_TICKS = _env_int("MAX_TICKS", 600)

    # Grid semantics (D2, D3, D6).
    SECONDS_PER_TICK = 0.7
    CELL_CAPACITY = 3
    MIN_CELL_CAPACITY = 1
    MAX_CELL_CAPACITY = 5
    EXIT_THROUGHPUT_PER_CELL = 1  # agents admitted per exit cell per tick

    # Simulation defaults offered by the config panel.
    DEFAULT_AGENTS = 150
    DEFAULT_SPEED = 1.0
    MIN_SPEED = 0.5
    MAX_SPEED = 1.0  # credit is capped at 1 cell/tick, so >1.0 has no effect
    DEFAULT_SEED = 42

    MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB request body cap


class TestConfig(Config):
    """Tests supply DATABASE_PATH as a temp file (see tests/conftest.py).

    An in-memory SQLite database is not usable here: each request opens its own
    connection, and ':memory:' would give every one of them an empty database.
    """

    TESTING = True
