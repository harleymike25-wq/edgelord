"""Team power ratings, computed from final scores -- no model calls.

Every pick so far has had its number produced by the LLM: it reads the pack and
states how far it moves the line. Measured against the market that number was
slightly worse than the line itself (RMSE 13.69 vs 13.47 on Week 1), and it
carries the model's habits -- shrinkage toward a pick'em, a lean to the dog on
big spreads. This module is the other way round: the number is arithmetic, so
it can be replayed over a decade of games for nothing and judged on thousands
of results rather than thirty-two.

The rating is a weighted least-squares fit of game margins:

    home_margin = home_field * (not neutral) + rating[home] - rating[away]

fitted on every game played before the week being projected. A rating is
points better than an average team on a neutral field. Three choices keep it
from chasing noise:

- margins are capped, so a 45-7 garbage-time blowout counts as a big win and
  not as five touchdowns of information;
- last season's games are included at reduced weight, which is how the prior
  enters and why Week 1 has a rating at all;
- a ridge penalty pulls every team toward average, most strongly when there are
  few games to go on.

The replay walks forward week by week and never fits on a game at or after the
week it projects. Parameters are chosen on 2017-2021 and the verdict is read
off 2022 onward, which the tuning never saw.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import polars as pl

from .sources import nflverse

FIRST_SEASON = 2016
TUNE_SEASONS = range(2017, 2022)
TEST_FROM = 2022

# Franchises that moved inside the cached window, mapped to today's codes so a
# team's history is one series.
RELOCATED = {"SD": "LAC", "STL": "LA", "OAK": "LV"}

VIG_WIN = 100 / 110


@dataclass(frozen=True)
class Params:
    """Defaults are the `tune()` winner on 2017-2021 (RMSE 13.58 vs the margin).

    The optimum sits inside the grid for prior weight and ridge; the margin cap
    is nearly flat past 21 (13.56 uncapped), so it is not doing much either way.
    """
    prior_weight: float = 0.2     # weight of a last-season game vs a this-season one
    ridge: float = 3.0            # pull toward average, in games' worth of weight
    margin_cap: float = 28.0
    recency: float = 0.95         # per-week decay within the current season


DEFAULT = Params()


def load_games(through_season: int, *, refresh: bool = False) -> pl.DataFrame:
    df = nflverse.schedules(range(FIRST_SEASON, through_season + 1), refresh=refresh)
    return (
        df.select(
            "game_id", "season", "week", "game_type", "gameday", "location",
            pl.col("home_team").replace(RELOCATED),
            pl.col("away_team").replace(RELOCATED),
            "home_score", "away_score", "spread_line",
        )
        .with_columns(
            (pl.col("home_score") - pl.col("away_score")).alias("margin"),
            (pl.col("location") != "Neutral").cast(pl.Float64).alias("home_field"),
        )
        .sort("season", "week", "gameday")
    )


def _training(games: pl.DataFrame, season: int, week: int, p: Params) -> pl.DataFrame:
    """Games finished before `season`/`week`, with their weight."""
    played = games.filter(pl.col("margin").is_not_null())
    this = played.filter((pl.col("season") == season) & (pl.col("week") < week))
    last = played.filter(pl.col("season") == season - 1)
    return pl.concat([
        this.with_columns(
            (p.recency ** (week - 1 - pl.col("week"))).alias("w")
        ),
        last.with_columns(pl.lit(p.prior_weight).alias("w")),
    ])


def fit(games: pl.DataFrame, season: int, week: int, p: Params = DEFAULT) -> tuple[dict, float]:
    """Ratings as they stood before kickoff of `season`/`week`, plus home field."""
    train = _training(games, season, week, p)
    teams = sorted(set(train["home_team"]) | set(train["away_team"]))
    if not teams:
        return {}, 0.0
    idx = {t: i for i, t in enumerate(teams)}
    n, k = train.height, len(teams)

    X = np.zeros((n + k, k + 1))
    y = np.zeros(n + k)
    w = np.zeros(n + k)
    rows = train.select("home_team", "away_team", "home_field", "margin", "w").iter_rows()
    for i, (h, a, hf, m, wt) in enumerate(rows):
        X[i, idx[h]] = 1.0
        X[i, idx[a]] = -1.0
        X[i, k] = hf
        y[i] = max(-p.margin_cap, min(p.margin_cap, m))
        w[i] = wt
    # Ridge rows: each rating is also "observed" at zero with weight `ridge`.
    # Home field is left unpenalised.
    for j in range(k):
        X[n + j, j] = 1.0
        w[n + j] = p.ridge

    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    ratings = coef[:k] - coef[:k].mean()
    return {t: float(ratings[idx[t]]) for t in teams}, float(coef[k])


def project(ratings: dict, home_field: float, home: str, away: str, neutral: bool) -> float | None:
    if home not in ratings or away not in ratings:
        return None
    return (0.0 if neutral else home_field) + ratings[home] - ratings[away]


def replay(games: pl.DataFrame, seasons, p: Params = DEFAULT, *, regular_only: bool = True) -> pl.DataFrame:
    """Walk forward: project each week from a fit on everything before it."""
    out = []
    targets = games.filter(pl.col("season").is_in(list(seasons)))
    if regular_only:
        targets = targets.filter(pl.col("game_type") == "REG")
    for (season, week), wk in targets.group_by(["season", "week"], maintain_order=True):
        ratings, hfa = fit(games, season, week, p)
        for g in wk.iter_rows(named=True):
            proj = project(ratings, hfa, g["home_team"], g["away_team"], g["home_field"] == 0)
            out.append({
                "game_id": g["game_id"], "season": season, "week": week,
                "home_team": g["home_team"], "away_team": g["away_team"],
                "projected": None if proj is None else round(proj, 2),
                "market": g["spread_line"], "margin": g["margin"],
            })
    return pl.DataFrame(out, infer_schema_length=None)


def _ats(sub: pl.DataFrame) -> dict:
    """Record betting the model's side against the market, at -110."""
    edge = sub["projected"] - sub["market"]
    cover = sub["margin"] - sub["market"]
    side = np.sign(edge.to_numpy())
    res = np.sign(cover.to_numpy()) * side
    w, l = int((res > 0).sum()), int((res < 0).sum())
    p = len(res) - w - l
    n = w + l
    return {
        "w": w, "l": l, "p": p,
        "win_pct": round(w / n, 4) if n else None,
        "units": round(w * VIG_WIN - l, 2),
        # How many standard errors the win rate sits above the 52.38% break-even.
        "z_vs_breakeven": round((w / n - 0.5238) / math.sqrt(0.25 / n), 2) if n else None,
    }


def evaluate(rep: pl.DataFrame) -> dict:
    """Is the rating any use next to the market?

    Three views, in the order they should be trusted:
    - `market_weight`: regress the actual margin's miss vs the market on the
      model's disagreement with it. 0 means the rating adds nothing the line
      does not already have; 1 means it should replace the line.
    - error vs actual margin, model against market;
    - ATS record at increasing disagreement thresholds. The noisiest, and the
      one that pays.
    """
    d = rep.drop_nulls(["projected", "market", "margin"])
    if d.is_empty():
        return {"games": 0}
    m, mk, pr = d["margin"].to_numpy(), d["market"].to_numpy(), d["projected"].to_numpy()
    dis, miss = pr - mk, m - mk
    beta = float((dis * miss).sum() / (dis * dis).sum()) if (dis * dis).sum() else 0.0
    resid = miss - beta * dis
    se = float(math.sqrt((resid ** 2).sum() / max(len(d) - 1, 1) / (dis * dis).sum())) if (dis * dis).sum() else None

    def err(x):
        return {"mae": round(float(np.abs(m - x).mean()), 2), "rmse": round(float(np.sqrt(((m - x) ** 2).mean())), 2)}

    ats = {}
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        sub = d.filter((d["projected"] - d["market"]).abs() >= max(t, 0.01))
        ats[f"{t:g}+"] = {"games": sub.height, **_ats(sub)}

    fav = d.filter((d["projected"] - d["market"]).abs() >= 0.01)
    took_dog = int(((np.sign((fav["projected"] - fav["market"]).to_numpy()) != np.sign(fav["market"].to_numpy())) & (fav["market"].to_numpy() != 0)).sum())

    return {
        "games": d.height,
        "model": err(pr),
        "market": err(mk),
        "market_weight": {"beta": round(beta, 3), "se": round(se, 3) if se else None},
        "mean_abs_disagreement": round(float(np.abs(dis).mean()), 2),
        "dog_share": round(took_dog / fav.height, 3) if fav.height else None,
        "ats": ats,
    }


def tune(games: pl.DataFrame) -> tuple[Params, list[dict]]:
    """Grid search on the tuning seasons only, scored on RMSE vs the margin.

    Scored on predicting the game, not on the ATS record: tuning for wins
    against the spread over five seasons would find whichever settings happened
    to catch the lucky covers.
    """
    grid = []
    for pw in (0.2, 0.35, 0.5, 0.75):
        for rg in (3.0, 6.0, 10.0):
            for cap in (17.0, 21.0, 28.0):
                for rc in (0.95, 1.0):
                    p = Params(pw, rg, cap, rc)
                    ev = evaluate(replay(games, TUNE_SEASONS, p))
                    grid.append({**asdict(p), "rmse": ev["model"]["rmse"], "mae": ev["model"]["mae"]})
    grid.sort(key=lambda r: r["rmse"])
    best = grid[0]
    return Params(best["prior_weight"], best["ridge"], best["margin_cap"], best["recency"]), grid


def table(games: pl.DataFrame, season: int, week: int, p: Params = DEFAULT) -> dict:
    """Ratings for display: this week's, with last week's for the change."""
    now, hfa = fit(games, season, week, p)
    before, _ = fit(games, season, week - 1, p) if week > 1 else ({}, 0.0)
    rows = sorted(now.items(), key=lambda kv: -kv[1])
    teams = [
        {
            "rank": i + 1, "team": t, "rating": round(r, 1),
            "change": round(r - before[t], 1) if t in before else None,
        }
        for i, (t, r) in enumerate(rows)
    ]
    slate = []
    wk = games.filter((pl.col("season") == season) & (pl.col("week") == week))
    for g in wk.iter_rows(named=True):
        proj = project(now, hfa, g["home_team"], g["away_team"], g["home_field"] == 0)
        slate.append({
            "game_id": g["game_id"], "home_team": g["home_team"], "away_team": g["away_team"],
            "projected": None if proj is None else round(proj, 1),
            "market": g["spread_line"],
        })
    return {"season": season, "week": week, "home_field": round(hfa, 2), "teams": teams, "slate": slate}


def next_week(games: pl.DataFrame, season: int) -> int:
    """The first week of `season` with a game still to play.

    Deliberately not the dashboard's live week, which stays on a finished week
    for two days after it ends: ratings are only useful for games not yet
    played, and should already include the week just finished.
    """
    left = games.filter((pl.col("season") == season) & pl.col("margin").is_null())
    return int(left["week"].min()) if left.height else int(
        games.filter(pl.col("season") == season)["week"].max()
    )


def payload(season: int, week: int | None = None, *, games: pl.DataFrame | None = None) -> dict:
    """Everything the dashboard's ratings page shows, verdict included.

    The replay travels with the table for the same reason the evidence block
    travels with the record: a list of ratings with projected spreads beside
    the market looks like a betting tool whether or not it is one.
    """
    from datetime import datetime

    games = games if games is not None else load_games(season)
    out = table(games, season, week or next_week(games, season))
    test = evaluate(replay(games, range(TEST_FROM, season)))
    live = evaluate(replay(games, [season]))
    out.update({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params": asdict(DEFAULT),
        "tuned_on": [TUNE_SEASONS.start, TUNE_SEASONS.stop - 1],
        "test_seasons": [TEST_FROM, season - 1],
        "replay": test,
        "live": live,
    })
    return out
