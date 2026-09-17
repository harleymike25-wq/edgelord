"""Grading and running record.

Sign convention throughout: a stored `line_at_pick` is expressed as "the team we
picked is favoured by this many points", so it is `spread_home` for a home pick
and `-spread_home` for an away pick. The picked side covers when its actual
margin exceeds that number.

Closing line value is the reason `line_at_pick` exists. Win rate over a
seventeen-week sample is mostly noise; whether the bot was consistently on the
better side of the number is not.
"""

from __future__ import annotations

from datetime import datetime

# Books price standard sides at -110 unless we captured something better.
DEFAULT_PRICE = -110


def payout(price: int | None) -> float:
    """Profit on a one-unit win at American odds."""
    price = price if price is not None else DEFAULT_PRICE
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def effective_line(pick_type: str, pick_side: str, home: str, line_at_pick: float | None,
                   spread_line: float | None, total_line: float | None) -> float | None:
    """The number a pick is actually graded against.

    `line_at_pick` is what was available when we picked; with no snapshot we
    fall back to the nflverse closing number. Grading and the post-mortem have
    to agree on this or they are describing two different bets.
    """
    if line_at_pick is not None:
        return line_at_pick
    if pick_type == "spread":
        if spread_line is None:
            return None
        return spread_line if pick_side == home else -spread_line
    if pick_type == "total":
        return total_line
    return None


def _spread_grade(pick_side: str, home: str, line: float, home_score: int, away_score: int):
    margin = (home_score - away_score) if pick_side == home else (away_score - home_score)
    if margin > line:
        return "win"
    if margin < line:
        return "loss"
    return "push"


def _total_grade(pick_side: str, line: float, home_score: int, away_score: int):
    total = home_score + away_score
    if total == line:
        return "push"
    if pick_side == "over":
        return "win" if total > line else "loss"
    return "win" if total < line else "loss"


def _clv(pick_type: str, pick_side: str, home: str, line: float | None,
         closing_spread: float | None, closing_total: float | None) -> float | None:
    """Positive means we held a better number than the market closed at."""
    if line is None:
        return None
    if pick_type == "spread":
        if closing_spread is None:
            return None
        close = closing_spread if pick_side == home else -closing_spread
        # Lower is better for the side we backed, so beating the close means
        # our number was below where it settled.
        return round(close - line, 2)
    if pick_type == "total":
        if closing_total is None:
            return None
        return round(
            (closing_total - line) if pick_side == "over" else (line - closing_total), 2
        )
    return None


def grade(conn, *, regrade: bool = False) -> int:
    """Grade every prediction whose game has finished. Returns rows written."""
    where = "" if regrade else "AND r.prediction_id IS NULL"
    rows = conn.execute(
        f"""
        SELECT p.id, p.game_id, p.pick_type, p.pick_side, p.line_at_pick,
               p.price_at_pick, g.home_team, g.home_score, g.away_score,
               g.spread_line, g.total_line
        FROM predictions p
        JOIN games g ON g.game_id = p.game_id
        LEFT JOIN results r ON r.prediction_id = p.id
        WHERE g.home_score IS NOT NULL {where}
        """
    ).fetchall()

    written = 0
    for r in rows:
        pick_type, side, line = r["pick_type"], r["pick_side"], r["line_at_pick"]
        home, hs, as_ = r["home_team"], r["home_score"], r["away_score"]

        line = effective_line(
            pick_type, side, home, line, r["spread_line"], r["total_line"]
        )

        if pick_type == "pass" or line is None:
            outcome, profit = "push", 0.0
        elif pick_type == "spread":
            outcome = _spread_grade(side, home, line, hs, as_)
            profit = payout(r["price_at_pick"]) if outcome == "win" else (
                -1.0 if outcome == "loss" else 0.0
            )
        else:
            outcome = _total_grade(side, line, hs, as_)
            profit = payout(r["price_at_pick"]) if outcome == "win" else (
                -1.0 if outcome == "loss" else 0.0
            )

        conn.execute(
            "INSERT OR REPLACE INTO results (prediction_id, game_id, home_score, "
            "away_score, closing_line, closing_total, pick_result, profit_units, "
            "clv_points, graded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"], r["game_id"], hs, as_, r["spread_line"], r["total_line"],
                outcome, round(profit, 4),
                _clv(pick_type, side, home, r["line_at_pick"],
                     r["spread_line"], r["total_line"]),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        written += 1
    return written


def _summarise(rows: list) -> dict:
    graded = [r for r in rows if r["pick_type"] != "pass"]
    wins = sum(r["pick_result"] == "win" for r in graded)
    losses = sum(r["pick_result"] == "loss" for r in graded)
    pushes = sum(r["pick_result"] == "push" for r in graded)
    profit = sum(r["profit_units"] or 0 for r in graded)
    clvs = [r["clv_points"] for r in graded if r["clv_points"] is not None]
    decided = wins + losses
    staked = wins + losses  # one unit risked per decided play

    return {
        "plays": len(graded),
        "passes": len(rows) - len(graded),
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_pct": round(wins / decided, 3) if decided else None,
        "units": round(profit, 2),
        "roi": round(profit / staked, 3) if staked else None,
        "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else None,
        "clv_positive_pct": (
            round(sum(c > 0 for c in clvs) / len(clvs), 3) if clvs else None
        ),
    }


def record(conn, *, season: int | None = None) -> dict:
    """Running performance, overall and sliced by market and confidence."""
    # Backtests are excluded for the same reason they never supersede a live
    # pick: they are predictions made about games that had already finished, so
    # counting them would let a favourable replay inflate a record that is
    # supposed to describe money at risk. The pending count below already
    # filtered them; this clause is what stops them reaching the record itself.
    sql = (
        "SELECT p.pick_type, p.pick_side, p.confidence, p.conviction, "
        "r.pick_result, r.profit_units, r.clv_points, g.season "
        "FROM results r JOIN predictions p ON p.id = r.prediction_id "
        "JOIN games g ON g.game_id = r.game_id "
        "WHERE p.superseded_by IS NULL AND p.run_label != 'backtest'"
    )
    params: tuple = ()
    if season is not None:
        sql += " AND g.season = ?"
        params = (season,)

    rows = conn.execute(sql, params).fetchall()

    # Live picks that have not been graded yet. Counted separately so a slate
    # that has been picked but not played reads as pending rather than as
    # nothing at all.
    pending_sql = (
        "SELECT COUNT(*) n FROM predictions p JOIN games g ON g.game_id = p.game_id "
        "LEFT JOIN results r ON r.prediction_id = p.id "
        "WHERE p.superseded_by IS NULL AND p.run_label != 'backtest' "
        "AND r.prediction_id IS NULL"
    )
    if season is not None:
        pending_sql += " AND g.season = ?"
    pending = conn.execute(pending_sql, params).fetchone()["n"]

    if not rows:
        # A complete zero summary, not a stub: the dashboard renders these
        # fields directly and a missing key shows as a blank cell.
        return {
            "best_bets": _summarise([]),
            "overall": {**_summarise([]), "pending": pending},
            "by_conviction": {},
            "by_market": {},
            "by_confidence": {},
        }

    buckets = {"50-59": (50, 59), "60-64": (60, 64), "65-69": (65, 69), "70+": (70, 101)}

    best = [r for r in rows if r["conviction"] == "best_bet"]

    return {
        # The headline. Leans are opinions; best bets are what you would
        # actually have staked, so they get their own record rather than being
        # averaged into one number with everything else.
        "best_bets": _summarise(best),
        "overall": {**_summarise(rows), "pending": pending},
        "by_conviction": {
            k: _summarise([r for r in rows if r["conviction"] == k])
            for k in ("best_bet", "lean")
            if any(r["conviction"] == k for r in rows)
        },
        "by_market": {
            m: _summarise([r for r in rows if r["pick_type"] == m])
            for m in ("spread", "total")
            if any(r["pick_type"] == m for r in rows)
        },
        # If the model's own confidence signal is meaningful, the high buckets
        # should outperform the low ones. Often they do not.
        "by_confidence": {
            name: _summarise(
                [r for r in rows if r["confidence"] is not None and lo <= r["confidence"] <= hi]
            )
            for name, (lo, hi) in buckets.items()
            if any(
                r["confidence"] is not None and lo <= r["confidence"] <= hi for r in rows
            )
        },
    }
