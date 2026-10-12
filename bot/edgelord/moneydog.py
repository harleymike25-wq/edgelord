"""The Moneydog: one moneyline underdog a week, chosen by arithmetic.

No model call. Each live pick already carries a projected home margin; a margin
becomes a win probability through the spread of NFL results around a
projection (about 13.5 points), and the moneyline gives the market's price for
the same thing. Among underdogs priced +120 to +300 -- real dogs that still win
25-45% of the time -- the Moneydog is the one with the best expected return per
unit at the price the pick was made against.

Like every other pick it is one a week whether or not any dog shows value; the
expected value is stored beside it so a week with no real value reads as one.
It may change until its game kicks off, then it is locked. The record starts at
2026 Week 6, when it was introduced; earlier weeks are deliberately not rebuilt.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from .recheck import kicked_off

# Standard deviation of NFL results around a projected margin. The prediction
# prompt uses ~13; 13.5 is the long-run figure for final margins vs the spread.
MARGIN_SD = 13.5
MIN_ODDS, MAX_ODDS = 120, 300


def win_prob(margin: float) -> float:
    """Chance a team projected to win by `margin` wins outright."""
    return 0.5 * (1 + math.erf(margin / (MARGIN_SD * math.sqrt(2))))


def implied(odds: int) -> float:
    """Raw probability in an American price, vig included."""
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def fair_implied(odds: int, other: int) -> float:
    """The price's probability with the bookmaker's margin taken out."""
    a, b = implied(odds), implied(other)
    return a / (a + b)


def profit(odds: int, result: str) -> float:
    if result == "win":
        return round(odds / 100 if odds > 0 else 100 / -odds, 4)
    return -1.0 if result == "loss" else 0.0


def candidates(conn, season: int, week: int) -> list[dict]:
    """Every qualifying underdog in the week, with its value. Best first."""
    rows = conn.execute(
        "SELECT g.game_id, g.gameday, g.gametime, g.home_team, g.away_team, "
        "  g.home_score, p.id AS prediction_id, p.projected_margin, f.payload "
        "FROM games g "
        "JOIN predictions p ON p.game_id = g.game_id AND p.superseded_by IS NULL "
        "  AND p.run_label != 'backtest' "
        "JOIN features f ON f.id = p.features_id "
        "WHERE g.season = ? AND g.week = ?",
        (season, week),
    ).fetchall()
    out = []
    for r in rows:
        market = (json.loads(r["payload"] or "{}").get("market")) or {}
        ml_home, ml_away = market.get("moneyline_home"), market.get("moneyline_away")
        if ml_home is None or ml_away is None or r["projected_margin"] is None:
            continue
        for team, odds, other, margin in (
            (r["home_team"], ml_home, ml_away, r["projected_margin"]),
            (r["away_team"], ml_away, ml_home, -r["projected_margin"]),
        ):
            if not MIN_ODDS <= odds <= MAX_ODDS:
                continue
            p = win_prob(margin)
            out.append({
                "game_id": r["game_id"],
                "gameday": r["gameday"],
                "gametime": r["gametime"],
                "home_score": r["home_score"],
                "prediction_id": r["prediction_id"],
                "team": team,
                "odds": int(odds),
                "win_prob": round(p, 4),
                "implied_prob": round(fair_implied(odds, other), 4),
                "ev": round(p * odds / 100 - (1 - p), 4),
            })
    return sorted(out, key=lambda c: -c["ev"])


def current(conn, season: int, week: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM moneydogs WHERE season = ? AND week = ?", (season, week)
    ).fetchone()
    return dict(row) if row else None


def select(conn, season: int, week: int, *, backfill: bool = False,
           now: datetime | None = None) -> dict | None:
    """Choose (or keep) the week's Moneydog and store it.

    A stored Moneydog whose game has started is final. Otherwise only games not
    yet kicked off are eligible, so the pick can never be made with hindsight.
    `backfill` rebuilds a past week from its stored packs instead.
    """
    held = current(conn, season, week)
    if held and not backfill:
        g = conn.execute(
            "SELECT gameday, gametime, home_score FROM games WHERE game_id = ?",
            (held["game_id"],),
        ).fetchone()
        if g and (g["home_score"] is not None or kicked_off(dict(g), now)):
            return held

    pool = candidates(conn, season, week)
    if not backfill:
        pool = [c for c in pool if c["home_score"] is None and not kicked_off(c, now)]
    if not pool:
        return held
    best = pool[0]
    conn.execute(
        "INSERT OR REPLACE INTO moneydogs (season, week, game_id, team, odds, "
        "win_prob, implied_prob, ev, prediction_id, picked_at, backfilled) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            season, week, best["game_id"], best["team"], best["odds"],
            best["win_prob"], best["implied_prob"], best["ev"],
            best["prediction_id"], datetime.now().isoformat(timespec="seconds"),
            int(backfill),
        ),
    )
    return current(conn, season, week)


def grade(conn, season: int) -> int:
    """Settle every Moneydog whose game has a final score. Returns how many."""
    rows = conn.execute(
        "SELECT m.season, m.week, m.team, m.odds, g.home_team, g.home_score, g.away_score "
        "FROM moneydogs m JOIN games g ON g.game_id = m.game_id "
        "WHERE m.season = ? AND g.home_score IS NOT NULL",
        (season,),
    ).fetchall()
    for r in rows:
        mine, theirs = (
            (r["home_score"], r["away_score"]) if r["team"] == r["home_team"]
            else (r["away_score"], r["home_score"])
        )
        result = "win" if mine > theirs else "loss" if mine < theirs else "push"
        conn.execute(
            "UPDATE moneydogs SET result = ?, profit_units = ? WHERE season = ? AND week = ?",
            (result, profit(r["odds"], result), r["season"], r["week"]),
        )
    return len(rows)


def record(conn, season: int) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM moneydogs WHERE season = ? ORDER BY week", (season,)
    ).fetchall()]
    graded = [r for r in rows if r["result"]]
    w = sum(r["result"] == "win" for r in graded)
    l = sum(r["result"] == "loss" for r in graded)
    p = sum(r["result"] == "push" for r in graded)
    units = round(sum(r["profit_units"] or 0 for r in graded), 2)
    return {
        "picks": len(rows),
        "record": f"{w}-{l}" + (f"-{p}" if p else ""),
        "units": units,
        "roi": round(units / len(graded), 4) if graded else None,
        "pending": len(rows) - len(graded),
        "backfilled_weeks": [r["week"] for r in rows if r["backfilled"]],
        "weeks": rows,
    }
