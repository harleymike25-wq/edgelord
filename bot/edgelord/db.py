"""SQLite system of record.

Bulk nflverse pulls live in parquet under data/cache/; this database holds only
what we generate or need to query across time: games, our own line snapshots,
the exact feature packs we sent to the model, predictions and their grades.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

# How long a writer waits for a competing write to finish before giving up.
# A model call can hold its transaction for tens of seconds, so this is
# generous rather than the sqlite default of five.
BUSY_TIMEOUT_SECONDS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    season         INTEGER NOT NULL,
    week           INTEGER NOT NULL,
    game_type      TEXT,
    gameday        TEXT NOT NULL,
    weekday        TEXT,
    gametime       TEXT,
    home_team      TEXT NOT NULL,
    away_team      TEXT NOT NULL,
    home_score     INTEGER,
    away_score     INTEGER,
    spread_line    REAL,      -- nflverse closing line, positive = home favoured
    total_line     REAL,
    home_moneyline INTEGER,
    away_moneyline INTEGER,
    roof           TEXT,
    surface        TEXT,
    temp           INTEGER,
    wind           INTEGER,
    referee        TEXT,
    home_rest      INTEGER,
    away_rest      INTEGER,
    div_game       INTEGER,
    home_coach     TEXT,
    away_coach     TEXT,
    home_qb        TEXT,
    away_qb        TEXT,
    stadium        TEXT,
    stadium_id     TEXT,
    location       TEXT,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_games_season_week ON games(season, week);
CREATE INDEX IF NOT EXISTS idx_games_gameday ON games(gameday);

-- One row per poll per book per market. The whole open-vs-close and reverse
-- line movement story is reconstructed from this table.
CREATE TABLE IF NOT EXISTS line_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id        TEXT,
    odds_event_id  TEXT NOT NULL,
    commence_time  TEXT NOT NULL,
    home_team      TEXT NOT NULL,
    away_team      TEXT NOT NULL,
    book           TEXT NOT NULL,
    captured_at    TEXT NOT NULL,
    book_update    TEXT,
    spread_home    REAL,
    spread_home_price INTEGER,
    spread_away_price INTEGER,
    total          REAL,
    over_price     INTEGER,
    under_price    INTEGER,
    ml_home        INTEGER,
    ml_away        INTEGER,
    UNIQUE(odds_event_id, book, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_snap_game ON line_snapshots(game_id, captured_at);

-- Credit accounting so the free 500/month tier is never blown through.
CREATE TABLE IF NOT EXISTS odds_api_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at     TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    credits_used    INTEGER,
    credits_remaining INTEGER,
    events_returned INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usage_time ON odds_api_usage(captured_at);

-- Model spend, one row per API call. This is what the monthly budget guard
-- reads. Without it a three-runs-a-week re-predict loop can quietly run up a
-- bill on a per-output-token model.
CREATE TABLE IF NOT EXISTS api_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    called_at       TEXT NOT NULL,
    game_id         TEXT,
    run_label       TEXT,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_usage_time ON api_usage(called_at);

-- The exact JSON pack handed to the model, kept so any prediction can be replayed.
CREATE TABLE IF NOT EXISTS features (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id    TEXT NOT NULL,
    built_at   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    data_gaps  TEXT
);
CREATE INDEX IF NOT EXISTS idx_features_game ON features(game_id, built_at);

CREATE TABLE IF NOT EXISTS predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          TEXT NOT NULL,
    features_id      INTEGER REFERENCES features(id),
    model            TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    run_label        TEXT,       -- 'sunday', 'thursday', 'monday', 'backtest'
    pick_type        TEXT,       -- 'spread' | 'total' | 'pass'
    pick_side        TEXT,       -- team abbr, or 'over'/'under'
    -- How much the pick is worth acting on. Every game gets a side; only
    -- best_bet clears the edge bar. The headline record is best bets only.
    conviction       TEXT DEFAULT 'lean',
    line_at_pick     REAL,       -- the number actually available when we picked
    price_at_pick    INTEGER,
    confidence       INTEGER,    -- 1-100 as reported by the model
    projected_margin REAL,       -- home margin, positive = home wins by
    projected_total  REAL,
    headline         TEXT,       -- one line, no statistics, for scanning a slate
    paragraph        TEXT NOT NULL,
    key_factors      TEXT,       -- JSON array
    superseded_by    INTEGER REFERENCES predictions(id)
);
CREATE INDEX IF NOT EXISTS idx_pred_game ON predictions(game_id, created_at);

CREATE TABLE IF NOT EXISTS results (
    prediction_id  INTEGER PRIMARY KEY REFERENCES predictions(id),
    game_id        TEXT NOT NULL,
    home_score     INTEGER NOT NULL,
    away_score     INTEGER NOT NULL,
    closing_line   REAL,
    closing_total  REAL,
    pick_result    TEXT,      -- 'win' | 'loss' | 'push'
    profit_units   REAL,      -- at the stored price, 1 unit risked
    clv_points     REAL,      -- line_at_pick vs close, positive = we beat the close
    graded_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_game ON results(game_id);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # WAL lets readers and a writer coexist, but two writers still collide.
    # The scheduled jobs overlap by design -- the six-hourly line poll can fire
    # while a Sunday slate is mid-run -- so wait for the lock rather than
    # failing the whole run on a few milliseconds of contention.
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_SECONDS * 1000}")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
