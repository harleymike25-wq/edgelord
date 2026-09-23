"""A pre-registered search for any computable betting signal.

Asked "can the weights be tuned until it hits 60%?", the honest answer is that
any search wide enough will find 60% in-sample and none of it will hold. So this
does the version that can be believed:

1. The candidate list below was written and committed BEFORE any of it was run.
   Nothing is added, removed or re-thresholded after seeing a result.
2. Discovery: every candidate is scored on 2016-2021 only.
3. Gate (fixed in advance): a candidate goes forward only if, in discovery, it
   has at least 50 bets, a win rate at or above the 52.4% break-even at -110,
   and a one-sided p below 0.10 against a coin flip.
4. Holdout: survivors -- and only survivors -- are scored once on 2022-2025.
   To pass, a survivor must clear 52.4% there AND have a one-sided p below
   0.05 divided by the number of survivors (Bonferroni).

Every rule bets closing lines at -110; spreads and totals are nflverse's
closing numbers. Everything uses information available before kickoff. No
model calls, no cost.

CANDIDATES (side: the team or total direction the rule backs)

Spreads
  S01 home underdog                              -> home
  S02 home underdog of 7+                        -> home
  S03 favourite of 10+                           -> underdog
  S04 divisional game                            -> underdog
  S05 rest edge of 3+ days                       -> rested team
  S06 Thursday game                              -> underdog
  S07 primetime kickoff (7pm ET or later)        -> underdog
  S08 Pacific team at a 1pm ET kickoff out east  -> home
  S09 road team crossed 2+ time zones            -> home
  S10 lost its last game by 20+                  -> that team
  S11 won its last game by 20+                   -> against that team
  S12 Weeks 1-4                                  -> underdog
  S13 Weeks 15-18                                -> underdog
  S14 underdog getting exactly +3                -> underdog
  S15 underdog getting exactly +7                -> underdog
  S16 covered each of its last 3                 -> against that team
  S17 power rating 3+ points off the line        -> rating's side

Totals
  T01 wind 15+ mph                               -> under
  T02 temperature 32F or below                   -> under
  T03 total 50 or higher                         -> under
  T04 total 40 or lower                          -> over
  T05 divisional game                            -> under
  T06 dome or closed roof                        -> over
  T07 primetime kickoff                          -> under
  T08 Weeks 1-4                                  -> under

    .venv/Scripts/python.exe scripts/signal_search.py
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl

from edgelord import ratings as R
from edgelord.sources import stadiums

DISCOVERY = (2016, 2021)
HOLDOUT = (2022, 2025)
BREAKEVEN = 110 / 210
MIN_BETS = 50
GATE_P = 0.10
HOLDOUT_ALPHA = 0.05


def _schedule() -> pl.DataFrame:
    raw = pl.concat(
        [pl.read_parquet(R.nflverse._cache_path("schedules", y)) for y in range(2016, 2026)],
        how="diagonal_relaxed",
    ).select("game_id", "weekday", "gametime", "home_rest", "away_rest", "div_game",
             "roof", "temp", "wind", "total_line")
    games = R.load_games(2025).join(raw, on="game_id", how="left")
    return games.filter(
        (pl.col("game_type") == "REG") & pl.col("margin").is_not_null()
        & pl.col("spread_line").is_not_null()
    )


def _team_history(games: pl.DataFrame) -> dict:
    """(season, week, team) -> last margin and covers in the previous 3 games."""
    long = pl.concat([
        games.select("season", "week", pl.col("home_team").alias("team"),
                     pl.col("margin").alias("m"),
                     (pl.col("margin") - pl.col("spread_line")).alias("c")),
        games.select("season", "week", pl.col("away_team").alias("team"),
                     (-pl.col("margin")).alias("m"),
                     (pl.col("spread_line") - pl.col("margin")).alias("c")),
    ]).sort("season", "team", "week")
    out = {}
    for (season, team), g in long.group_by(["season", "team"], maintain_order=True):
        ms, cs = g["m"].to_list(), g["c"].to_list()
        for i, wk in enumerate(g["week"].to_list()):
            out[(season, wk, team)] = {
                "last_margin": ms[i - 1] if i >= 1 else None,
                "covered_last3": i >= 3 and all(c > 0 for c in cs[i - 3:i]),
            }
    return out


def _tz_shift(away: str, home: str, day: str) -> float | None:
    a, h = stadiums.home_venue(away), stadiums.home_venue(home)
    if not a or not h:
        return None
    return stadiums.tz_shift_hours(a, h, date.fromisoformat(day))


def frame() -> pl.DataFrame:
    games = _schedule()
    hist = _team_history(games)
    rep = R.replay(R.load_games(2025), range(2016, 2026)).select("game_id", "projected")
    games = games.join(rep, on="game_id", how="left")

    rows = []
    for g in games.iter_rows(named=True):
        hh = hist.get((g["season"], g["week"], g["home_team"]), {})
        ah = hist.get((g["season"], g["week"], g["away_team"]), {})
        neutral = g["home_field"] == 0
        shift = None if neutral else _tz_shift(g["away_team"], g["home_team"], g["gameday"])
        away_v = stadiums.home_venue(g["away_team"])
        rows.append({
            **{k: g[k] for k in ("game_id", "season", "week", "spread_line", "total_line",
                                  "margin", "div_game", "roof", "temp", "wind", "weekday",
                                  "gametime", "home_rest", "away_rest", "projected")},
            "points": g["home_score"] + g["away_score"],
            "neutral": neutral,
            "tz_shift": shift,
            "away_pacific": bool(away_v and away_v.tz in ("America/Los_Angeles",)),
            "home_last": hh.get("last_margin"), "away_last": ah.get("last_margin"),
            "home_hot": hh.get("covered_last3", False), "away_hot": ah.get("covered_last3", False),
        })
    return pl.DataFrame(rows, infer_schema_length=None)


def _dog(r) -> int | None:
    """+1 home / -1 away for the underdog; None on a pick'em."""
    s = r["spread_line"]
    return None if s == 0 else (-1 if s > 0 else 1)


def _prime(r) -> bool:
    return (r["gametime"] or "00:00") >= "19:00"


def _one_side(home_flag: bool, away_flag: bool, home_side: int) -> int | None:
    """Back (+1) or oppose (-1) the flagged team; skip when both or neither."""
    if home_flag == away_flag:
        return None
    return home_side if home_flag else -home_side


SPREAD = {
    "S01 home underdog": lambda r: 1 if r["spread_line"] < 0 else None,
    "S02 home underdog of 7+": lambda r: 1 if r["spread_line"] <= -7 else None,
    "S03 favourite of 10+": lambda r: _dog(r) if abs(r["spread_line"]) >= 10 else None,
    "S04 divisional game": lambda r: _dog(r) if r["div_game"] == 1 else None,
    "S05 rest edge of 3+ days": lambda r: (
        None if r["home_rest"] is None or r["away_rest"] is None
        else 1 if r["home_rest"] - r["away_rest"] >= 3
        else -1 if r["away_rest"] - r["home_rest"] >= 3 else None),
    "S06 Thursday game": lambda r: _dog(r) if r["weekday"] == "Thursday" else None,
    "S07 primetime kickoff": lambda r: _dog(r) if _prime(r) else None,
    "S08 Pacific team, 1pm ET, out east": lambda r: (
        1 if r["away_pacific"] and r["gametime"] == "13:00" and (r["tz_shift"] or 0) >= 2
        else None),
    "S09 road team crossed 2+ zones": lambda r: (
        1 if r["tz_shift"] is not None and abs(r["tz_shift"]) >= 2 else None),
    "S10 lost last game by 20+": lambda r: _one_side(
        (r["home_last"] or 0) <= -20, (r["away_last"] or 0) <= -20, 1),
    "S11 won last game by 20+": lambda r: _one_side(
        (r["home_last"] or 0) >= 20, (r["away_last"] or 0) >= 20, -1),
    "S12 Weeks 1-4": lambda r: _dog(r) if r["week"] <= 4 else None,
    "S13 Weeks 15-18": lambda r: _dog(r) if r["week"] >= 15 else None,
    "S14 underdog at exactly +3": lambda r: _dog(r) if abs(r["spread_line"]) == 3 else None,
    "S15 underdog at exactly +7": lambda r: _dog(r) if abs(r["spread_line"]) == 7 else None,
    "S16 covered each of last 3": lambda r: _one_side(r["home_hot"], r["away_hot"], -1),
    "S17 rating 3+ off the line": lambda r: (
        None if r["projected"] is None or abs(r["projected"] - r["spread_line"]) < 3
        else (1 if r["projected"] > r["spread_line"] else -1)),
}

TOTAL = {
    "T01 wind 15+ mph": lambda r: -1 if (r["wind"] or 0) >= 15 else None,
    "T02 temp 32F or below": lambda r: -1 if r["temp"] is not None and r["temp"] <= 32 else None,
    "T03 total 50+": lambda r: -1 if r["total_line"] >= 50 else None,
    "T04 total 40 or lower": lambda r: 1 if r["total_line"] <= 40 else None,
    "T05 divisional game": lambda r: -1 if r["div_game"] == 1 else None,
    "T06 dome or closed roof": lambda r: 1 if r["roof"] in ("dome", "closed") else None,
    "T07 primetime kickoff": lambda r: -1 if _prime(r) else None,
    "T08 Weeks 1-4": lambda r: -1 if r["week"] <= 4 else None,
}


def _p_one_sided(w: int, n: int, p0: float = 0.5) -> float:
    if not n:
        return 1.0
    z = (w - n * p0) / math.sqrt(n * p0 * (1 - p0))
    return 0.5 * math.erfc(z / math.sqrt(2))


def score(df: pl.DataFrame, rule, market: str) -> dict:
    w = l = 0
    for r in df.iter_rows(named=True):
        side = rule(r)
        if side is None:
            continue
        if market == "spread":
            edge = r["margin"] - r["spread_line"]
        else:
            if r["total_line"] is None:
                continue
            edge = r["points"] - r["total_line"]
        res = (edge > 0) - (edge < 0)
        if res == 0:
            continue
        if res == side:
            w += 1
        else:
            l += 1
    n = w + l
    return {"w": w, "l": l, "n": n, "pct": w / n if n else float("nan"),
            "p": _p_one_sided(w, n), "units": w * 100 / 110 - l}


def _holm(ps: dict) -> dict:
    order = sorted(ps, key=ps.get)
    m, adj, run = len(order), {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[k]))
        adj[k] = run
    return adj


def _line(name, s, extra=""):
    return (f"  {name:<36} {s['w']:>4}-{s['l']:<4} {s['pct']:>6.1%} "
            f"p={s['p']:.3f} {s['units']:>+7.1f}u {extra}")


def main() -> None:
    df = frame()
    disc = df.filter(pl.col("season").is_between(*DISCOVERY))
    hold = df.filter(pl.col("season").is_between(*HOLDOUT))
    rules = [(k, f, "spread") for k, f in SPREAD.items()] + [(k, f, "total") for k, f in TOTAL.items()]

    print(f"{df.height} games. Discovery {DISCOVERY[0]}-{DISCOVERY[1]} "
          f"({disc.height}), holdout {HOLDOUT[0]}-{HOLDOUT[1]} ({hold.height}). "
          f"Break-even {BREAKEVEN:.1%}.\n")
    print("DISCOVERY")
    res = {k: score(disc, f, m) for k, f, m in rules}
    holm = _holm({k: r["p"] for k, r in res.items()})
    survivors = []
    for k, _, _ in rules:
        s = res[k]
        passed = s["n"] >= MIN_BETS and s["pct"] >= BREAKEVEN and s["p"] < GATE_P
        if passed:
            survivors.append(k)
        print(_line(k, s, f"holm={holm[k]:.2f}" + ("   <- through the gate" if passed else "")))

    print(f"\n{len(survivors)} of {len(rules)} through the discovery gate.")
    if not survivors:
        print("Nothing to take to the holdout.")
        return
    alpha = HOLDOUT_ALPHA / len(survivors)
    print(f"\nHOLDOUT (looked at once; pass = win% >= {BREAKEVEN:.1%} and p < {alpha:.4f})")
    fns = {k: (f, m) for k, f, m in rules}
    for k in survivors:
        f, m = fns[k]
        s = score(hold, f, m)
        ok = s["pct"] >= BREAKEVEN and s["p"] < alpha
        print(_line(k, s, "PASS" if ok else "fail"))


if __name__ == "__main__":
    main()
