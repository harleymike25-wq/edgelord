"""Matchup context: head-to-head, splits, referee crews, coaching, injuries.

nflverse's `spread_line` is the number of points the home team is favoured by,
and `result` is home_score - away_score, so the home side covers when
`result > spread_line`. That convention is used throughout this module.
"""

from __future__ import annotations

import polars as pl

from ..sources import stadiums

# 4th down "go zone": short yardage in the part of the field where the decision
# is genuinely optional, before garbage time.
GO_ZONE_MAX_YDSTOGO = 4


def _finished(games: pl.DataFrame) -> pl.DataFrame:
    return games.filter(pl.col("home_score").is_not_null())


def _with_ats(games: pl.DataFrame) -> pl.DataFrame:
    return _finished(games).with_columns(
        (pl.col("result") - pl.col("spread_line")).alias("ats_margin"),
        (pl.col("home_score") + pl.col("away_score")).alias("actual_total"),
    )


def _before(games: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """Everything already played, in this season up to `week` or any earlier season."""
    return games.filter(
        (pl.col("season") < season) | ((pl.col("season") == season) & (pl.col("week") < week))
    )


def head_to_head(
    games: pl.DataFrame, home: str, away: str, season: int, week: int, *, limit: int = 10
) -> dict:
    """Recent meetings between these two, straight up and against the spread."""
    hist = _with_ats(_before(games, season, week)).filter(
        ((pl.col("home_team") == home) & (pl.col("away_team") == away))
        | ((pl.col("home_team") == away) & (pl.col("away_team") == home))
    ).sort(["season", "week"], descending=True).head(limit)

    if hist.is_empty():
        return {"meetings": 0, "recent": []}

    recent = []
    home_wins = home_covers = 0
    for r in hist.to_dicts():
        winner = r["home_team"] if r["result"] > 0 else r["away_team"] if r["result"] < 0 else "tie"
        covered = r["home_team"] if r["ats_margin"] > 0 else r["away_team"] if r["ats_margin"] < 0 else "push"
        if winner == home:
            home_wins += 1
        if covered == home:
            home_covers += 1
        recent.append(
            {
                "season": r["season"],
                "week": r["week"],
                "at": r["home_team"],
                "score": f"{r['away_team']} {r['away_score']} @ {r['home_team']} {r['home_score']}",
                "spread_line": r["spread_line"],
                "winner": winner,
                "covered": covered,
                "total": r["actual_total"],
                "total_line": r["total_line"],
            }
        )

    return {
        "meetings": len(recent),
        f"{home}_su_wins": home_wins,
        f"{home}_ats_covers": home_covers,
        "recent": recent,
    }


def team_splits(games: pl.DataFrame, team: str, season: int, week: int) -> dict:
    """Home/road/divisional record, straight up and against the spread, this season."""
    season_games = _with_ats(
        games.filter((pl.col("season") == season) & (pl.col("week") < week))
    ).filter((pl.col("home_team") == team) | (pl.col("away_team") == team))

    if season_games.is_empty():
        return {"games": 0}

    def tally(rows: list[dict]) -> dict:
        w = l = t = cov = notcov = push = 0
        for r in rows:
            at_home = r["home_team"] == team
            margin = r["result"] if at_home else -r["result"]
            ats = r["ats_margin"] if at_home else -r["ats_margin"]
            w, l, t = w + (margin > 0), l + (margin < 0), t + (margin == 0)
            cov, notcov, push = cov + (ats > 0), notcov + (ats < 0), push + (ats == 0)
        return {
            "record": f"{w}-{l}" + (f"-{t}" if t else ""),
            "ats": f"{cov}-{notcov}" + (f"-{push}" if push else ""),
            "ats_pct": round(cov / (cov + notcov), 3) if (cov + notcov) else None,
        }

    rows = season_games.to_dicts()
    return {
        "games": len(rows),
        "overall": tally(rows),
        "home": tally([r for r in rows if r["home_team"] == team]),
        "away": tally([r for r in rows if r["away_team"] == team]),
        "divisional": tally([r for r in rows if r["div_game"] == 1]),
        "as_favorite": tally(
            [
                r
                for r in rows
                if (r["spread_line"] > 0) == (r["home_team"] == team) and r["spread_line"] != 0
            ]
        ),
    }


def referee_profile(
    games: pl.DataFrame, pbp: pl.DataFrame, referee: str | None, *, exclude_season: int | None = None
) -> dict | None:
    """How this referee's games have historically run.

    Referee effects are small and noisy; this is included so the model can note
    a genuinely extreme crew, not so it can lean on it.
    """
    if not referee:
        return None

    hist = _with_ats(games).filter(pl.col("referee") == referee)
    if exclude_season is not None:
        hist = hist.filter(pl.col("season") <= exclude_season)
    if hist.height < 5:
        return {"referee": referee, "games": hist.height, "note": "too few games to profile"}

    ids = set(hist["game_id"].to_list())
    pen = pbp.filter(pl.col("game_id").is_in(ids) & (pl.col("penalty") == 1))
    n_games = hist.height

    league_total = _with_ats(games)["actual_total"].mean()

    return {
        "referee": referee,
        "games": n_games,
        "penalties_per_game": round(pen.height / n_games, 2) if n_games else None,
        "penalty_yards_per_game": round((pen["penalty_yards"].sum() or 0) / n_games, 1),
        "avg_total_points": round(float(hist["actual_total"].mean()), 1),
        "league_avg_total_points": round(float(league_total), 1),
        "over_rate": round(float((hist["actual_total"] > hist["total_line"]).mean()), 3),
        "home_cover_rate": round(float((hist["ats_margin"] > 0).mean()), 3),
    }


def coaching_profile(
    pbp: pl.DataFrame, team: str, season: int, week: int, *, lookback_seasons: int = 2
) -> dict:
    """Fourth down aggression and situational tendencies, from play calls."""
    scoped = pbp.filter(
        pl.col("season").is_between(season - lookback_seasons + 1, season)
        & ~((pl.col("season") == season) & (pl.col("week") >= week))
        & (pl.col("posteam") == team)
    )
    if scoped.is_empty():
        return {"games": 0}

    go_zone = scoped.filter(
        (pl.col("down") == 4)
        & (pl.col("ydstogo") <= GO_ZONE_MAX_YDSTOGO)
        & pl.col("yardline_100").is_between(20, 70)
        & (pl.col("qtr") <= 3)
        & (pl.col("play_type").is_not_null())
    )
    went = go_zone.filter(pl.col("play_type").is_in(["pass", "run"])).height
    total = go_zone.filter(
        pl.col("play_type").is_in(["pass", "run", "punt", "field_goal"])
    ).height

    two_min = scoped.filter(
        (pl.col("qtr") == 2) & (pl.col("half_seconds_remaining") <= 120)
    )

    return {
        "games": scoped["game_id"].n_unique(),
        "fourth_down_go_rate": round(went / total, 3) if total else None,
        "fourth_down_go_zone_attempts": total,
        "no_huddle_rate": round(float(scoped["no_huddle"].mean() or 0), 3),
        "shotgun_rate": round(float(scoped["shotgun"].mean() or 0), 3),
        "two_minute_drill_epa": (
            round(float(two_min["epa"].mean()), 3) if two_min.height else None
        ),
    }


def injury_report(
    injuries: pl.DataFrame,
    team: str,
    season: int,
    week: int,
    *,
    positions: tuple[str, ...] = (),
    usage: dict[str, dict] | None = None,
) -> list[dict]:
    """Practice-report statuses for the week, weighted by how much each plays.

    This is the Wednesday-to-Friday report, not the inactives list, which is
    only published 90 minutes before kickoff and is not in nflverse at all.

    `usage` maps gsis_id to snap share. Without it a report is a list of names
    and the model cannot tell a shutdown corner from a special-teamer; with it,
    entries rank by status *and* playing time, so the ones that actually move a
    number sort to the top.
    """
    if injuries.is_empty():
        return []
    rows = injuries.filter(
        (pl.col("season") == season) & (pl.col("week") == week) & (pl.col("team") == team)
    )
    if positions:
        rows = rows.filter(pl.col("position").is_in(list(positions)))
    rows = rows.filter(
        pl.col("report_status").is_not_null() | pl.col("practice_status").is_not_null()
    )
    out = []
    for r in rows.to_dicts():
        played = (usage or {}).get(r.get("gsis_id") or "", {})
        out.append(
            {
                "player": r.get("full_name"),
                "position": r.get("position"),
                "status": r.get("report_status") or r.get("practice_status"),
                "injury": r.get("report_primary_injury") or r.get("practice_primary_injury"),
                "practice": r.get("practice_status"),
                # Share of snaps in the reference season. None means no track
                # record -- a rookie or fringe player, not necessarily minor.
                "snap_pct_prior": played.get("snap_pct"),
                "starter": (played.get("snap_pct") or 0) >= 0.55,
            }
        )
    # Out and doubtful first, and within a status the heaviest usage first.
    rank = {"Out": 0, "Doubtful": 1, "Questionable": 2}
    out.sort(key=lambda x: (rank.get(x["status"], 9), -(x["snap_pct_prior"] or 0)))
    return out


def divisional_context(home: str, away: str) -> dict:
    return {
        "home_division": stadiums.DIVISIONS.get(home),
        "away_division": stadiums.DIVISIONS.get(away),
        "same_division": stadiums.same_division(home, away),
    }
