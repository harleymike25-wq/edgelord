"""What the graded picks say about the model's own habits. Free.

The post-mortems keep naming the same faults in prose: injury counts overriding
a team-strength gap, a backup quarterback trusted on a handful of dropbacks.
Prose never reaches a prompt, so those findings went nowhere. This turns each
one into a tag that code can put on a pick, counts it on every graded pick --
wins as well as losses, because a habit that loses nine times and wins eleven
is not a fault -- and says when a tag has earned a change to the arithmetic.

Nothing here changes a pick. A tag that crosses the bar is a reason to change
the code that sums the factors (cap one, shrink one), in the open, the way the
no-injury replay is: see `no_injury.py`. The bar was fixed before any game it
judges was played.

Three tables:

- `tags`: the named habits, each with its record.
- `factors`: every checklist factor, as the record of picks that leaned on it
  and of picks that went against it.
- `how_played`: from the play-by-play, whether the picked side was out-played
  or won the snaps, for wins and losses alike. A loss on bounces is not a
  lesson; a win while out-played is not a skill.
"""

from __future__ import annotations

import json

from .evidence import binomial_tail
from .shadow import CHECKLIST, FACTOR_KEYS

# Weeks before this are hindsight: the tags were written after reading them.
# Same line as the no-injury replay, set 2026-11-16 before Week 11 kicked off.
START_WEEK = 11

# A factor "leans" a pick one way when it carries at least this many points.
LEAN_POINTS = 1.0
# A quarterback read rests on a thin sample below this many dropbacks this
# season -- the same figure the quarterback model shrinks toward replacement on.
THIN_DROPBACKS = 200

# The bar, on test-period picks only: enough of them, and a win rate that would
# be this unlikely if the habit were a coin flip.
MIN_PICKS = 20
P_BAR = 0.10

# Efficiency edges inside these are an even game (the post-mortem's own bands).
EVEN_EPA = 0.05
EVEN_SUCCESS = 0.03

TAGS: dict[str, str] = {
    "injuries_over_strength": (
        "Injury points of 1+ toward the pick, while team strength favoured the "
        "other side"
    ),
    "thin_quarterback_read": (
        f"Quarterback points of 1+ toward the pick, with an expected starter "
        f"under {THIN_DROPBACKS} dropbacks this season"
    ),
    "against_team_strength": "Picked the side team strength pointed away from",
    "matchup_over_strength": (
        "Pass, run and pressure points of 1+ toward the pick, while team "
        "strength favoured the other side"
    ),
}


def toward_pick(factor_points: dict, pick_is_home: bool) -> dict[str, float]:
    """Each factor's corrected points, positive when they favour the picked side."""
    m = factor_points.get("multipliers") or {}
    sign = 1.0 if pick_is_home else -1.0
    raw = factor_points.get("raw") or {}
    return {k: float(raw.get(k) or 0.0) * m.get(k, 1.0) * sign for k in FACTOR_KEYS}


def thin_quarterback(pack: dict) -> bool:
    """True when either team's expected starter has a small sample this season."""
    for side in ("home", "away"):
        sit = (pack.get(side) or {}).get("quarterback_situation") or {}
        name = sit.get("expected_starter")
        for c in sit.get("candidates") or []:
            if c.get("player") == name:
                form = c.get("form_this_season") or {}
                if (form.get("dropbacks") or 0) < THIN_DROPBACKS:
                    return True
    return False


def tags_for(points: dict[str, float], pack: dict) -> list[str]:
    """The habits this pick shows. `points` is from `toward_pick`."""
    strength_against = points["team_strength"] < 0
    matchup = points["pass_game"] + points["run_game"] + points["pressure"]
    out = []
    if points["availability"] >= LEAN_POINTS and strength_against:
        out.append("injuries_over_strength")
    if points["quarterback"] >= LEAN_POINTS and thin_quarterback(pack):
        out.append("thin_quarterback_read")
    if strength_against:
        out.append("against_team_strength")
    if matchup >= LEAN_POINTS and strength_against:
        out.append("matchup_over_strength")
    return out


def how_played(box: dict | None) -> str | None:
    """'outplayed', 'won_snaps' or 'even', from the picked side's box score."""
    if not box:
        return None
    epa = box.get("edge_epa_per_play_ex_turnovers")
    success = box.get("edge_success_rate")
    if epa is None or success is None:
        return None
    if epa <= -EVEN_EPA and success <= -EVEN_SUCCESS:
        return "outplayed"
    if epa >= EVEN_EPA and success >= EVEN_SUCCESS:
        return "won_snaps"
    return "even"


def _blank() -> dict:
    return {"wins": 0, "losses": 0, "pushes": 0}


def _add(block: dict, result: str) -> None:
    block[{"win": "wins", "loss": "losses", "push": "pushes"}[result]] += 1


def verdict(block: dict) -> dict:
    """A record with its win rate and whether it has crossed the bar.

    'act' means the habit lost often enough, on enough picks made after the
    tag was written, that it should be taken out of the sum. 'hold' means
    enough picks and no case. Several tags are watched at once, so one 'act'
    in a season is roughly what chance alone would produce: read it as a
    reason to look, and check the hindsight weeks point the same way.
    """
    w, l = block["wins"], block["losses"]
    n = w + l
    out = {**block, "record": f"{w}-{l}" + (f"-{block['pushes']}" if block["pushes"] else ""),
           "win_pct": round(w / n, 3) if n else None}
    if n < MIN_PICKS:
        out["verdict"] = "too few"
        out["needs"] = MIN_PICKS - n
        return out
    # Chance of this few wins or fewer from a coin flip.
    p = 1.0 - binomial_tail(w + 1, n, 0.5)
    out["p_value"] = round(p, 3)
    out["verdict"] = "act" if p < P_BAR else "hold"
    return out


def _rows(conn, season: int):
    return conn.execute(
        """
        SELECT p.id, p.game_id, g.week, p.pick_side, p.factor_points,
               g.home_team, g.away_team, r.pick_result, f.payload
        FROM predictions p
        JOIN games g ON g.game_id = p.game_id
        JOIN results r ON r.prediction_id = p.id
        LEFT JOIN features f ON f.id = p.features_id
        WHERE g.season = ? AND p.run_label = 'blind' AND p.superseded_by IS NULL
          AND p.pick_type = 'spread' AND p.factor_points IS NOT NULL
        ORDER BY g.week, p.game_id
        """,
        (season,),
    ).fetchall()


def _period() -> dict:
    return {
        "picks": 0,
        "tags": {t: _blank() for t in TAGS},
        "factors": {k: {"leaned_on": _blank(), "went_against": _blank()}
                    for k in FACTOR_KEYS},
        "how_played": {r: {"outplayed": 0, "even": 0, "won_snaps": 0, "unknown": 0}
                       for r in ("win", "loss")},
    }


def tally(conn, season: int, *, pbp=None) -> dict:
    """Every graded blind pick, tagged, split at START_WEEK.

    `pbp` is the season's play-by-play for the how-played table; without it
    that table reads unknown and the rest is unaffected.
    """
    from . import postmortem

    periods = {"hindsight": _period(), "test": _period()}
    tagged: list[dict] = []
    for r in _rows(conn, season):
        home, away, side = r["home_team"], r["away_team"], r["pick_side"]
        points = toward_pick(json.loads(r["factor_points"]), side == home)
        try:
            pack = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            pack = {}
        result = r["pick_result"]
        period = periods["test" if r["week"] >= START_WEEK else "hindsight"]
        period["picks"] += 1

        tags = tags_for(points, pack)
        for t in tags:
            _add(period["tags"][t], result)
        for k in FACTOR_KEYS:
            if points[k] >= LEAN_POINTS:
                _add(period["factors"][k]["leaned_on"], result)
            elif points[k] <= -LEAN_POINTS:
                _add(period["factors"][k]["went_against"], result)

        played = None
        if pbp is not None and result in ("win", "loss"):
            played = how_played(
                postmortem.box_score(pbp, r["game_id"], "spread", side, home, away)
            )
        if result in ("win", "loss"):
            period["how_played"][result][played or "unknown"] += 1
        if tags:
            tagged.append({"game_id": r["game_id"], "week": r["week"], "pick": side,
                           "result": result, "tags": tags, "how_played": played})

    labels = {k: label for k, label, _ in CHECKLIST}
    out = {"start_week": START_WEEK, "min_picks": MIN_PICKS, "p_bar": P_BAR,
           "tag_meaning": TAGS, "tagged_picks": tagged}
    for name, period in periods.items():
        out[name] = {
            "picks": period["picks"],
            "tags": {t: verdict(b) for t, b in period["tags"].items()},
            "factors": {
                k: {"label": labels[k],
                    "leaned_on": verdict(v["leaned_on"]),
                    "went_against": verdict(v["went_against"])}
                for k, v in period["factors"].items()
            },
            "how_played": period["how_played"],
        }
    # Hindsight records are shown, never judged: the tags were written from them.
    for block in out["hindsight"]["tags"].values():
        block["verdict"] = "hindsight"
    for f in out["hindsight"]["factors"].values():
        f["leaned_on"]["verdict"] = f["went_against"]["verdict"] = "hindsight"
    return out
