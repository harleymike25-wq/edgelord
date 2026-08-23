"""nflverse pulls, cached to parquet.

Completed seasons never change, so they are cached indefinitely. The in-progress
season is refetched once it goes stale, which keeps the Sunday job from pulling
tens of megabytes of play-by-play it already has.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Iterable

import nflreadpy as nfl
import polars as pl

from .. import config

# How long an in-progress season's cache stays fresh.
LIVE_TTL_SECONDS = 6 * 3600

# dataset -> seasons nflverse does not publish yet. Populated as pulls are
# attempted so callers can report what was skipped rather than guess.
UNAVAILABLE: dict[str, set[int]] = {}


def _cache_path(dataset: str, season: int):
    return config.CACHE_DIR / f"{dataset}_{season}.parquet"


def _is_stale(dataset: str, season: int) -> bool:
    path = _cache_path(dataset, season)
    if not path.exists():
        return True
    if season < config.current_season():
        return False
    return (time.time() - path.stat().st_mtime) > LIVE_TTL_SECONDS


def _load(
    dataset: str,
    loader: Callable[[list[int]], pl.DataFrame],
    seasons: Iterable[int],
    *,
    refresh: bool = False,
) -> pl.DataFrame:
    seasons = list(seasons)
    config.ensure_dirs()
    frames = []
    missing = [s for s in seasons if refresh or _is_stale(dataset, s)]

    if missing:
        # A future season has a published schedule long before it has any
        # play-by-play, injuries or officials, and nflreadpy raises rather than
        # returning empty for those. One unavailable season must not take down
        # the whole pull, so fall back to fetching season by season and skip
        # the ones that are not out yet.
        try:
            fetched = loader(missing)
            for season in missing:
                fetched.filter(pl.col("season") == season).write_parquet(
                    _cache_path(dataset, season)
                )
        except Exception:
            for season in missing:
                try:
                    part = loader([season])
                except Exception:
                    UNAVAILABLE.setdefault(dataset, set()).add(season)
                    continue
                part.filter(pl.col("season") == season).write_parquet(
                    _cache_path(dataset, season)
                )

    for season in seasons:
        path = _cache_path(dataset, season)
        if path.exists():
            frames.append(pl.read_parquet(path))

    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal_relaxed")


def schedules(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("schedules", lambda s: nfl.load_schedules(s), seasons, refresh=refresh)


def pbp(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("pbp", lambda s: nfl.load_pbp(s), seasons, refresh=refresh)


def injuries(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("injuries", lambda s: nfl.load_injuries(s), seasons, refresh=refresh)


def officials(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("officials", lambda s: nfl.load_officials(s), seasons, refresh=refresh)


def ftn_charting(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("ftn", lambda s: nfl.load_ftn_charting(s), seasons, refresh=refresh)


def snap_counts(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("snap_counts", lambda s: nfl.load_snap_counts(s), seasons, refresh=refresh)


def rosters(seasons: Iterable[int], *, refresh: bool = False) -> pl.DataFrame:
    return _load("rosters", lambda s: nfl.load_rosters(s), seasons, refresh=refresh)


def depth_charts(season: int, *, refresh: bool = False) -> pl.DataFrame:
    """Depth charts for one season.

    Not routed through `_load`: the frame has no `season` column to filter on,
    and it is refreshed on the live TTL because charts move through the week.
    """
    path = config.CACHE_DIR / f"depth_charts_{season}.parquet"
    config.ensure_dirs()
    stale = (
        refresh
        or not path.exists()
        or (time.time() - path.stat().st_mtime) > LIVE_TTL_SECONDS
    )
    if stale:
        nfl.load_depth_charts([season]).write_parquet(path)
    return pl.read_parquet(path)


def players(*, refresh: bool = False) -> pl.DataFrame:
    """Player id crosswalk. Not season-scoped, so cached under a fixed key."""
    path = config.CACHE_DIR / "players.parquet"
    config.ensure_dirs()
    if refresh or not path.exists() or (
        time.time() - path.stat().st_mtime > 30 * 24 * 3600
    ):
        nfl.load_players().write_parquet(path)
    return pl.read_parquet(path)


# Columns we lift from the nflverse schedule into the games table.
_GAME_COLUMNS = {
    "game_id": "game_id",
    "season": "season",
    "week": "week",
    "game_type": "game_type",
    "gameday": "gameday",
    "weekday": "weekday",
    "gametime": "gametime",
    "home_team": "home_team",
    "away_team": "away_team",
    "home_score": "home_score",
    "away_score": "away_score",
    "spread_line": "spread_line",
    "total_line": "total_line",
    "home_moneyline": "home_moneyline",
    "away_moneyline": "away_moneyline",
    "roof": "roof",
    "surface": "surface",
    "temp": "temp",
    "wind": "wind",
    "referee": "referee",
    "home_rest": "home_rest",
    "away_rest": "away_rest",
    "div_game": "div_game",
    "home_coach": "home_coach",
    "away_coach": "away_coach",
    "home_qb_name": "home_qb",
    "away_qb_name": "away_qb",
    "stadium": "stadium",
    "stadium_id": "stadium_id",
    "location": "location",
}


def snapshot_lines(conn, seasons: Iterable[int], *, refresh: bool = True) -> dict:
    """Record the current nflverse line for every unplayed game.

    nflverse carries a live spread/total/moneyline on upcoming games and
    updates it through the week, so snapshotting it on each run reconstructs
    the same open-to-close path the paid odds feeds give -- opening number,
    movement, key-number crossings and closing line value -- without a key.

    The trade-off versus The Odds API is breadth, not existence: one consensus
    number instead of thirty books, so there is no best-available shopping and
    no cross-book divergence signal. Rows are written with `book = 'nflverse'`
    so they can be told apart if a real odds feed is added later.
    """
    df = schedules(seasons, refresh=refresh)
    if df.is_empty():
        return {"snapshots": 0, "games": 0}

    upcoming = df.filter(
        pl.col("home_score").is_null() & pl.col("spread_line").is_not_null()
    )
    if upcoming.is_empty():
        return {"snapshots": 0, "games": 0}

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (
            r["game_id"], r["game_id"], f"{r['gameday']}T{r['gametime'] or '00:00'}",
            r["home_team"], r["away_team"], "nflverse", captured_at,
            r["spread_line"], r["total_line"], r["home_moneyline"], r["away_moneyline"],
        )
        for r in upcoming.select(
            "game_id", "gameday", "gametime", "home_team", "away_team",
            "spread_line", "total_line", "home_moneyline", "away_moneyline",
        ).to_dicts()
    ]

    # A snapshot is only interesting if the number actually moved, so skip
    # writing when this game's latest stored nflverse line already matches.
    written = 0
    for row in rows:
        prev = conn.execute(
            "SELECT spread_home, total FROM line_snapshots "
            "WHERE game_id = ? AND book = 'nflverse' "
            "ORDER BY captured_at DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        if prev and prev["spread_home"] == row[7] and prev["total"] == row[8]:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO line_snapshots (game_id, odds_event_id, "
            "commence_time, home_team, away_team, book, captured_at, spread_home, "
            "total, ml_home, ml_away) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        written += 1

    return {"snapshots": written, "games": len(rows), "captured_at": captured_at}


def sync_games(conn, seasons: Iterable[int], *, refresh: bool = False) -> int:
    """Upsert nflverse schedule rows into the games table."""
    df = schedules(seasons, refresh=refresh)
    if df.is_empty():
        return 0

    df = df.select([pl.col(src).alias(dst) for src, dst in _GAME_COLUMNS.items()])
    cols = list(_GAME_COLUMNS.values())
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "game_id")

    sql = (
        f"INSERT INTO games ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(game_id) DO UPDATE SET {updates}, updated_at=datetime('now')"
    )
    rows = [tuple(r[c] for c in cols) for r in df.to_dicts()]
    conn.executemany(sql, rows)
    return len(rows)
