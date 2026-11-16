"""The blind picks again with the injury factor set to zero. Free.

The owner's read after Week 10: injury news keeps tipping close picks the wrong
way (ARI +9.5, LV +6.5). The numbers half agree. Of the 55 graded blind picks
through Week 10, the ones where injury points favoured the pick went 10-12 and
the rest 16-8. Replayed with injuries at zero, the 55 go 33-22 against 30-25 as
made, but halving or capping the factor changes nothing. That is three games,
and the comparison was chosen after the results were known.

So nothing changes in the model yet. This replays every graded pick from its
stored factor points (corrections included) with availability zeroed and
grades it against the line the pick saw. Weeks before START_WEEK are hindsight
and are shown apart. The test is the weeks from START_WEEK on: if the
no-injury column keeps winning there, the factor comes out.
"""

from __future__ import annotations

import json

from .track import payout

START_WEEK = 11  # pre-registered 2026-11-15, after Week 10's Sunday games


def replay(factor_points: dict, line_home: float, home: str, away: str) -> str:
    """The side the blind predictor would have taken with injury points at zero."""
    m = factor_points.get("multipliers") or {}
    pts = {k: v * m.get(k, 1.0) for k, v in factor_points["raw"].items()}
    pts["availability"] = 0.0
    margin = sum(pts.values())
    diff = margin - line_home
    # Same tie-break as shadow.assemble.
    return home if diff > 0 else away if diff < 0 else (home if margin >= 0 else away)


def _grade(side: str, home: str, line_home: float, home_score: int, away_score: int) -> str:
    cover = (home_score - away_score - line_home) * (1 if side == home else -1)
    return "win" if cover > 0 else "loss" if cover < 0 else "push"


def _tally(outcomes: list[tuple[str, int | None]]) -> dict:
    w = sum(o == "win" for o, _ in outcomes)
    l = sum(o == "loss" for o, _ in outcomes)
    p = sum(o == "push" for o, _ in outcomes)
    u = sum(payout(price) if o == "win" else -1.0 if o == "loss" else 0.0
            for o, price in outcomes)
    return {"record": f"{w}-{l}" + (f"-{p}" if p else ""), "wins": w, "losses": l,
            "units": round(u, 2)}


def _rows(conn, season: int):
    return conn.execute(
        """
        SELECT p.game_id, g.week, p.pick_side, p.line_at_pick, p.price_at_pick,
               p.factor_points, g.home_team, g.away_team, g.home_score, g.away_score
        FROM predictions p JOIN games g ON g.game_id = p.game_id
        WHERE g.season = ? AND p.run_label = 'blind' AND p.superseded_by IS NULL
          AND p.pick_type = 'spread' AND p.factor_points IS NOT NULL
          AND p.line_at_pick IS NOT NULL
        ORDER BY g.week, p.game_id
        """,
        (season,),
    ).fetchall()


def compare(conn, season: int) -> dict:
    """Picks as made beside the no-injury replay, split at START_WEEK."""
    periods = {"hindsight": ([], [], []), "test": ([], [], [])}
    upcoming = []
    for r in _rows(conn, season):
        home, away = r["home_team"], r["away_team"]
        # line_at_pick is from the picked side: +3 means that side is favoured by 3.
        line_home = r["line_at_pick"] if r["pick_side"] == home else -r["line_at_pick"]
        alt = replay(json.loads(r["factor_points"]), line_home, home, away)
        if r["home_score"] is None:
            if alt != r["pick_side"]:
                upcoming.append({"game_id": r["game_id"], "week": r["week"],
                                 "pick": r["pick_side"], "no_injury": alt})
            continue
        made, alt_out = (
            _grade(s, home, line_home, r["home_score"], r["away_score"])
            for s in (r["pick_side"], alt)
        )
        actual, replayed, differ = periods["test" if r["week"] >= START_WEEK else "hindsight"]
        actual.append((made, r["price_at_pick"]))
        # The replay has no price of its own; it takes the pick's, almost always -110.
        replayed.append((alt_out, r["price_at_pick"]))
        if alt != r["pick_side"]:
            differ.append(r["game_id"])

    out = {"start_week": START_WEEK, "upcoming": upcoming}
    for name, (actual, replayed, differ) in periods.items():
        out[name] = {
            "games": len(actual),
            "differ": len(differ),
            "as_made": _tally(actual),
            "no_injury": _tally(replayed),
        }
    return out
