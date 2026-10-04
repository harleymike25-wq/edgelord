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


def passer_line(pbp: pl.DataFrame, player_id: str, season: int,
                through_week: int) -> dict | None:
    """One named passer's line, with no usage floor.

    `quarterback` reports whoever has thrown the most, which is the starter the
    team has had, not necessarily the one it will play. A backup with 34
    dropbacks still has to be described by his own numbers, so the sample size
    is reported instead of filtered on.
    """
    df = _scoped(pbp, season, through_week).filter(
        (pl.col("passer_player_id") == player_id) & (pl.col("qb_dropback") == 1)
    )
    if df.is_empty():
        return None
    return {
        "season": season,
        "games": df["game_id"].n_unique(),
        "dropbacks": df.height,
        "epa_per_dropback": round(df["epa"].mean(), 3),
        "success_rate": round(df["success"].mean(), 3),
        "sack_rate": round((df["sack"] == 1).mean(), 3),
        "interceptions": int((df["interception"] == 1).sum()),
    }


def last_game_passer(pbp: pl.DataFrame, team: str, season: int,
                     through_week: int) -> tuple[str, str] | None:
    """(player_id, name) of whoever took most dropbacks in the team's last game."""
    df = _scoped(pbp, season, through_week).filter(
        (pl.col("posteam") == team)
        & (pl.col("qb_dropback") == 1)
        & pl.col("passer_player_id").is_not_null()
    )
    if df.is_empty():
        return None
    df = df.filter(pl.col("week") == df["week"].max())
    top = (
        df.group_by("passer_player_id", "passer_player_name")
        .agg(pl.len().alias("n"))
        .sort("n", descending=True)
        .row(0)
    )
    return top[0], top[1]


# Game statuses that mean the player is not expected to play. Practice statuses
# alone ("Did Not Participate") are not a game status -- the Friday designation
# can lag in nflverse, so those leave the starter uncertain rather than out.
UNAVAILABLE = ("Out", "Doubtful")


def quarterback_situation(pbp: pl.DataFrame, injuries: pl.DataFrame,
                          depth_qbs: list[dict], team: str, season: int,
                          week: int) -> dict | None:
    """Who is expected to play quarterback, and how sure that is.

    The depth chart's QB1 stays listed while injured, and `player_form` only
    knows who has thrown the most. Together they described an injured starter as
    the quarterback and gave no numbers for the one actually playing. This names
    the expected starter -- the first quarterback on the depth chart not ruled
    out -- and, whenever there is any doubt, gives each candidate's own line.

    Returns None when the listed starter has no designation and also started
    the last game, which is the ordinary week and needs no extra block.
    """
    if not depth_qbs:
        return None

    status: dict[str, dict] = {}
    if not injuries.is_empty():
        rows = injuries.filter(
            (pl.col("season") == season) & (pl.col("week") == week)
            & (pl.col("team") == team) & (pl.col("position") == "QB")
        )
        for r in rows.to_dicts():
            status[r["gsis_id"]] = {
                "game_status": r.get("report_status"),
                "practice": r.get("practice_status"),
            }

    listed = depth_qbs[0]
    listed_status = status.get(listed["gsis_id"], {})
    expected = next(
        (q for q in depth_qbs
         if status.get(q["gsis_id"], {}).get("game_status") not in UNAVAILABLE),
        listed,
    )
    last = last_game_passer(pbp, team, season, week)

    # A full practice with no game status is a maintenance listing, not doubt.
    listed_clean = not listed_status.get("game_status") and (
        (listed_status.get("practice") or "").startswith("Full") or not listed_status
    )
    if listed_clean and (last is None or last[0] == listed["gsis_id"]):
        return None

    if expected is not listed:
        basis = (
            f"{listed['name']} is {listed_status.get('game_status')}; "
            f"{expected['name']} is next on the depth chart"
        )
    elif listed_status.get("game_status"):
        basis = (
            f"{listed['name']} is {listed_status['game_status']} -- "
            "treat the start as uncertain"
        )
    elif not listed_clean:
        basis = (
            f"{listed['name']} has no game status yet but practice reads "
            f"'{listed_status.get('practice')}' -- treat the start as uncertain"
        )
    else:
        basis = f"{listed['name']} is listed QB1 but did not start the last game"
    last_out = bool(last) and status.get(last[0], {}).get("game_status") in UNAVAILABLE
    if last and last[0] != expected["gsis_id"] and not last_out:
        basis +=f"; {last[1]} started the last game, so the depth chart may be stale"

    seen: set[str] = set()
    candidates = []
    for q in [listed, expected, *depth_qbs[1:]]:
        if q["gsis_id"] in seen:
            continue
        seen.add(q["gsis_id"])
        st = status.get(q["gsis_id"], {})
        candidates.append({
            "player": q["name"],
            "depth_rank": q["rank"],
            "game_status": st.get("game_status"),
            "practice": st.get("practice"),
            "started_last_game": bool(last and last[0] == q["gsis_id"]),
            "form_this_season": passer_line(pbp, q["gsis_id"], season, week),
            "form_last_season": passer_line(pbp, q["gsis_id"], season - 1, 99),
        })

    return {
        "listed_starter": listed["name"],
        "expected_starter": expected["name"],
        "basis": basis,
        "candidates": candidates,
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
