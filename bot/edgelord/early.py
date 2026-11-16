"""Which picks to bet early in the week, and which to wait on. Free.

Picks made on a Thursday sit for three days before most games kick off, and
the number can move in that time. This says, per pick, whether the number held
now is one worth taking before it goes.

It rests on key numbers and nothing else, because that is all the stored lines
support. Measured on 139 games of 2026 with two or more snapshots taken 48+
hours before kickoff (2026-11-16):

- A line that had already moved kept going 24 times and reversed 28. Which way
  a number has been moving says nothing about where it goes next, so movement
  is reported and never used.
- The favourite's number grew 24 times and shrank 38 by the close, so "bet
  favourites early, dogs late" is not a rule here either.
- Half-point hooks drift back onto the key number. Of 21 lines at 3.5, 7
  closed on 3 and 4 moved further away. Of 18 at 2.5, 3 closed on 3. The 7s
  are too few to read (12 games) and follow the same rule on the same logic.

One game in seven lands on exactly 3 and one in seventeen on 7, so the half
point either side of them is worth far more than any other. That gives four
cases:

- You hold the hook on the good side of a key number, and the line tends to
  fall back onto it: a dog at +3.5 or +7.5. BET NOW.
- You are laying less than the key number: a favourite at -2.5 or -6.5. If it
  goes to the key you have lost the most valuable half point there is. BET NOW.
- You are a half point on the wrong side: a favourite at -3.5 or -7.5, a dog
  at +2.5 or +6.5. A third of the 3.5s came back. WAIT.
- Anything else: the half points nearby are worth little. NO RUSH.

A coin flip is never worth hurrying for, and betting early gives up the
injury report, so BET NOW is kept to leans and best bets. Total picks are not
rated: totals have no key numbers worth the name.

This is graded the way it should be: `report()` shows whether the number then
got worse for the picks marked BET NOW and better for the ones marked WAIT,
from the closing line. That answers itself in weeks, not seasons.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# The two numbers that carry real mass in the NFL margin distribution.
KEYS = (3.0, 7.0)
# Inside this many hours of kickoff there is no "early" left to recommend.
MIN_HOURS = 36.0

BET_NOW, WAIT, NO_RUSH, NOT_RATED = "bet_now", "wait", "no_rush", "not_rated"


def hours_to_kickoff(game: dict, now: datetime | None = None) -> float | None:
    """Hours until kickoff. nflverse stores gametime as Eastern."""
    try:
        ko = datetime.strptime(
            f"{game['gameday']} {game.get('gametime_et') or game.get('gametime')}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=EASTERN)
    except (KeyError, TypeError, ValueError):
        return None
    now = now or datetime.now(EASTERN)
    return round((ko - now).total_seconds() / 3600, 1)


def _moved(pack: dict, side_is_home: bool) -> float | None:
    """Points the number has moved since it opened, positive = worse for our side."""
    mv = ((pack.get("market") or {}).get("movement") or {})
    move = mv.get("spread_move")
    if not mv.get("available") or move is None:
        return None
    # spread_home rising means the home side lays more: worse for a home pick.
    return round(move if side_is_home else -move, 1)


def recommend(pack: dict, pick_type: str, pick_side: str | None, tier: str | None,
              *, now: datetime | None = None) -> dict:
    """The timing call for one pick, with the reason in plain words."""
    game = pack.get("game") or {}
    hours = hours_to_kickoff(game, now)
    out: dict = {"action": NOT_RATED, "reason": "", "hours_to_kickoff": hours}

    if pick_type != "spread" or not pick_side:
        out["reason"] = "Totals are not rated for timing."
        return out
    spread = (pack.get("market") or {}).get("current_spread_home")
    if spread is None:
        out["reason"] = "No line to judge."
        return out
    if hours is not None and hours < MIN_HOURS:
        out["reason"] = "Too close to kickoff for timing to matter."
        return out

    home = pick_side == game.get("home_team")
    # "Our side is favoured by": positive lays points, negative takes them.
    line = float(spread) if home else -float(spread)
    shown = "pk" if line == 0 else f"{-line:+g}"
    out["line"] = line
    moved = _moved(pack, home)
    if moved:
        out["moved_since_open"] = moved

    action, reason = NO_RUSH, f"{shown} is not next to 3 or 7; a half point here is worth little."
    for key in KEYS:
        if line == -(key + 0.5):       # dog holding the hook: +3.5, +7.5
            action = BET_NOW
            reason = (f"{shown} has the hook on {key:g}. Lines a half point off "
                      f"a key number tend to fall back onto it; at +{key:g} a "
                      f"{key:g}-point loss is a push, not a win.")
        elif line == key - 0.5:        # favourite under the key: -2.5, -6.5
            action = BET_NOW
            reason = (f"{shown} is under {key:g}. If it goes to -{key:g}, a "
                      f"{key:g}-point win becomes a push.")
        elif line == key + 0.5:        # favourite past the key: -3.5, -7.5
            action = WAIT
            reason = (f"{shown} is a half point the wrong side of {key:g}. These "
                      f"often come back to -{key:g}; waiting costs little.")
        elif line == -(key - 0.5):     # dog short of the key: +2.5, +6.5
            action = WAIT
            reason = (f"{shown} is a half point short of +{key:g}. Worth waiting "
                      f"to see if the {key:g} shows up.")

    if action == BET_NOW and tier == "coin_flip":
        action = NO_RUSH
        reason = f"{shown} is a good number to hold, but a coin flip is not worth betting early."
    out["action"], out["reason"] = action, reason
    return out


def report(conn, season: int) -> dict:
    """Did the number then move the way each call said? From the closing line.

    `clv_points` is positive when the pick held a better number than the
    close. BET NOW is right when that is positive (it got worse after), WAIT
    is right when it is negative (it got better).
    """
    rows = conn.execute(
        """
        SELECT p.timing, r.clv_points
        FROM predictions p
        JOIN games g ON g.game_id = p.game_id
        JOIN results r ON r.prediction_id = p.id
        WHERE g.season = ? AND p.superseded_by IS NULL AND p.run_label != 'backtest'
          AND p.timing IS NOT NULL AND r.clv_points IS NOT NULL
        """,
        (season,),
    ).fetchall()
    out = {a: {"picks": 0, "got_worse": 0, "got_better": 0, "unchanged": 0,
               "avg_move": None, "_sum": 0.0}
           for a in (BET_NOW, WAIT, NO_RUSH)}
    for r in rows:
        try:
            action = json.loads(r["timing"]).get("action")
        except (ValueError, TypeError):
            continue
        b = out.get(action)
        if b is None:
            continue
        clv = r["clv_points"]
        b["picks"] += 1
        b["_sum"] += clv
        b["got_worse" if clv > 0 else "got_better" if clv < 0 else "unchanged"] += 1
    for b in out.values():
        total = b.pop("_sum")
        if b["picks"]:
            # Positive: the number got worse after the pick, so early was right.
            b["avg_move"] = round(total / b["picks"], 2)
    return out
