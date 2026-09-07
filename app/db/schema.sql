PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS venues (
  id         INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  width      INTEGER NOT NULL,
  height     INTEGER NOT NULL,
  cells      TEXT    NOT NULL,
  created_at TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS simulations (
  id             INTEGER PRIMARY KEY,
  venue_id       INTEGER REFERENCES venues(id) ON DELETE SET NULL,
  -- Cells as they were at run time, so a result survives later edits to the venue.
  venue_snapshot TEXT    NOT NULL,
  config_json    TEXT    NOT NULL,
  seed           INTEGER,
  status         TEXT,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS results (
  id                   INTEGER PRIMARY KEY,
  simulation_id        INTEGER REFERENCES simulations(id) ON DELETE CASCADE,
  metrics_json         TEXT,
  heatmap_json         TEXT,
  bottlenecks_json     TEXT,
  recommendations_json TEXT,
  trace_blob           BLOB,
  created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comparisons (
  id                 INTEGER PRIMARY KEY,
  name               TEXT,
  baseline_result_id INTEGER REFERENCES results(id) ON DELETE CASCADE,
  variant_result_id  INTEGER REFERENCES results(id) ON DELETE CASCADE,
  summary_json       TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_simulations_venue ON simulations(venue_id);
CREATE INDEX IF NOT EXISTS idx_results_simulation ON results(simulation_id);
