"""Individual player form, from play-by-play.

Team efficiency answers "how good is this offence"; it does not answer "who is
producing it, and are they still doing it". A team can carry a good season-long
EPA while its quarterback has thrown six interceptions in three weeks, and the
pack should say so.

Scope is deliberately tight. Quarterback plus the two or three skill players
carrying real usage is what moves a number; a full depth chart of statistics
would triple the pack for players who touch the ball twice a game.
"""

from __future__ import annotations

import polars as pl

# Usage floors, so a backup's three efficient carries do not outrank a starter.
MIN_DROPBACKS = 30
MIN_CARRIES = 20
MIN_TARGETS = 15
TOP_SKILL_PLAYERS = 3


def _scoped(pbp: pl.DataFrame, season: int, through_week: int,
            last_n_weeks: int | None = None) -> pl.DataFrame:
    df = pbp.filter(
        (pl.col("season") == season)
        & (pl.col("week") < through_week)
        & (pl.col("season_type") == "REG")
    )
    if last_n_weeks:
        df = df.filter(pl.col("week") >= through_week - last_n_weeks)
    return df


def quarterback(pbp: pl.DataFrame, team: str, season: int, through_week: int,
                *, last_n_weeks: int | None = None) -> dict | None:
    """The primary passer's form: efficiency, accuracy and ball security."""
    df = _scoped(pbp, season, through_week, last_n_weeks).filter(
        (pl.col("posteam") == team) & (pl.col("qb_dropback") == 1)
    )
    if df.is_empty():
        return None

    rows = (
        df.filter(pl.col("passer_player_id").is_not_null())
        .group_by("passer_player_id", "passer_player_name")
        .agg(
            pl.len().alias("dropbacks"),
            pl.col("epa").mean().alias("epa_per_dropback"),
            pl.col("cpoe").mean().alias("cpoe"),
            pl.col("success").mean().alias("success_rate"),
            (pl.col("sack") == 1).mean().alias("sack_rate"),
            (pl.col("interception") == 1).sum().alias("interceptions"),
            (pl.col("pass_touchdown") == 1).sum().alias("pass_tds"),
            pl.col("air_yards").mean().alias("avg_air_yards"),
            pl.col("game_id").n_unique().alias("games"),
        )
        .filter(pl.col("dropbacks") >= MIN_DROPBACKS)
        .sort("dropbacks", descending=True)
    )
    if rows.is_empty():
        return None

    r = rows.to_dicts()[0]
    return {
        "player": r["passer_player_name"],
        "games": r["games"],
        "dropbacks": r["dropbacks"],
        "epa_per_dropback": round(r["epa_per_dropback"], 3),
        "cpoe": round(r["cpoe"], 2) if r["cpoe"] is not None else None,
        "success_rate": round(r["success_rate"], 3),
        "sack_rate": round(r["sack_rate"], 3),
        "pass_tds": r["pass_tds"],
        "interceptions": r["interceptions"],
        "avg_air_yards": round(r["avg_air_yards"], 1) if r["avg_air_yards"] else None,
    }


def _skill(df: pl.DataFrame, id_col: str, name_col: str, min_uses: int,
           use_label: str) -> list[dict]:
    rows = (
        df.filter(pl.col(id_col).is_not_null())
        .group_by(id_col, name_col)
        .agg(
            pl.len().alias("uses"),
            pl.col("epa").mean().alias("epa_per_use"),
            pl.col("success").mean().alias("success_rate"),
            pl.col("yards_gained").sum().alias("yards"),
            pl.col("game_id").n_unique().alias("games"),
        )
        .filter(pl.col("uses") >= min_uses)
        .sort("uses", descending=True)
        .head(TOP_SKILL_PLAYERS)
    )
    return [
        {
            "player": r[name_col],
            "games": r["games"],
            use_label: r["uses"],
            "yards": int(r["yards"]) if r["yards"] is not None else None,
            "epa_per_use": round(r["epa_per_use"], 3),
            "success_rate": round(r["success_rate"], 3),
        }
        for r in rows.to_dicts()
    ]


def skill_players(pbp: pl.DataFrame, team: str, season: int, through_week: int,
                  *, last_n_weeks: int | None = None) -> dict:
    """Leading rushers and receivers by usage, with their efficiency."""
    df = _scoped(pbp, season, through_week, last_n_weeks).filter(
        pl.col("posteam") == team
    )
    if df.is_empty():
        return {}
    return {
        "rushers": _skill(
            df.filter(pl.col("rush") == 1), "rusher_player_id",
            "rusher_player_name", MIN_CARRIES, "carries",
        ),
        "receivers": _skill(
            df.filter(pl.col("pass") == 1), "receiver_player_id",
            "receiver_player_name", MIN_TARGETS, "targets",
        ),
    }


def profile(pbp: pl.DataFrame, team: str, season: int, through_week: int,
            *, recent_weeks: int = 5) -> dict:
    """Season-to-date and recent form for the players who carry the offence.

    Both windows are given because the interesting case is when they disagree:
    a quarterback whose season line looks fine while the last month does not.
    """
    season_qb = quarterback(pbp, team, season, through_week)
    recent_qb = quarterback(pbp, team, season, through_week, last_n_weeks=recent_weeks)

    out: dict = {}
    if season_qb:
        out["quarterback_season"] = season_qb
    if recent_qb and recent_qb.get("dropbacks", 0) >= MIN_DROPBACKS:
        out[f"quarterback_last_{recent_weeks}"] = recent_qb

    skills = skill_players(pbp, team, season, through_week)
    if skills.get("rushers") or skills.get("receivers"):
        out["skill_players_season"] = skills
    return out
