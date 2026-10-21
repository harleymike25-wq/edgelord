"""A pre-registered holdout of the Elo and QB-adjusted models.

Both models are tuned on 2017-2021 only (`edgelord/models/elo.py`,
`edgelord/models/qb.py`; parameters frozen in their `Params` defaults before
this script was run). The least-squares rating from `edgelord/ratings.py` is
reported beside them for comparison, with its existing frozen parameters.

THE RULES, written and committed before the holdout was run. Nothing below is
changed after seeing a result.

1. Holdout: 2022-2025 regular season, closing nflverse spreads and moneylines,
   looked at once. Each model's win-probability sigma is fit on 2017-2021 by
   log loss, never on the holdout.
2. WINNER test, per model. PASS requires BOTH:
   a. straight-up accuracy no more than 2.0 percentage points below the
      closing line's favourite on the same games; and
   b. Brier score no more than 0.010 worse than the line's.
   A pass means the model is good enough to name winners on the site beside
   the line. It says nothing about betting.
3. SPREAD test, per model, the same bar the EPA rating failed (2026-10-18).
   PASS requires BOTH:
   a. market weight: regressing the line's miss on the model's disagreement
      gives beta > 0 at least 2 standard errors above zero; and
   b. betting the model's side where it is 2+ points off the line wins at
      least 52.4% with one-sided p < 0.05.
   Only a model that passes this may influence which side the bot bets.
4. Reported either way: accuracy, Brier and log loss beside the line's; how
   often the model was right when it named a different winner from the line;
   RMSE/MAE against the margin; ATS at every threshold; the underdog share.
5. The 2026 season to date is printed as a live look and graded by nothing.

No model calls, no cost.

    .venv/Scripts/python.exe scripts/model_holdout.py
"""

from __future__ import annotations

import math

import polars as pl

from edgelord import ratings as R
from edgelord.models import common, elo, qb

BREAKEVEN = 110 / 210
MIN_EDGE = 2.0
SU_MARGIN = 0.02
BRIER_MARGIN = 0.010


def _p_one_sided(w: int, n: int) -> float:
    if not n:
        return 1.0
    z = (w - n * 0.5) / math.sqrt(n * 0.25)
    return 0.5 * math.erfc(z / math.sqrt(2))


def _with_market_prob(rep: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    if "market_prob" in rep.columns:
        return rep
    return rep.join(games.select("game_id", "market_prob"), on="game_id", how="left")


def models(games: pl.DataFrame, through: int) -> dict[str, pl.DataFrame]:
    """Each model's walk-forward projections, regular season only."""
    seasons = range(common.TUNE_SEASONS.start, through + 1)
    out = {
        "elo": elo.regular(elo.replay(games), seasons),
        "qb_elo": elo.regular(qb.replay(games, qb.qb_games(through)), seasons),
    }
    ls_games = R.load_games(through)
    out["least_squares"] = _with_market_prob(R.replay(ls_games, seasons), games)
    return out


def verdict(card: dict) -> tuple[bool, bool]:
    w = card["winners"]
    su = w["model"]["accuracy"] >= w["line"]["accuracy"] - SU_MARGIN
    br = w["model"]["brier"] <= w["line"]["brier"] + BRIER_MARGIN
    s = card["spread"]
    mw = s["market_weight"]
    a = mw["beta"] > 0 and bool(mw["se"]) and mw["beta"] >= 2 * mw["se"]
    two = s["ats"][f"{MIN_EDGE:g}+"]
    b = ((two["win_pct"] or 0) >= BREAKEVEN
         and _p_one_sided(two["w"], two["w"] + two["l"]) < 0.05)
    return su and br, a and b


def show(name: str, card: dict, *, graded: bool = True) -> None:
    w, s = card["winners"], card["spread"]
    print(f"\n{name.upper()}  ({card['games']} games, sigma {card['sigma']})")
    print(f"  straight-up  model {w['model']['accuracy']:.1%}   line {w['line']['accuracy']:.1%}")
    print(f"  brier        model {w['model']['brier']:.4f}   line {w['line']['brier']:.4f}")
    print(f"  log loss     model {w['model']['log_loss']:.4f}   line {w['line']['log_loss']:.4f}")
    d = w["disagreements"]
    if d["games"]:
        print(f"  named a different winner from the line in {d['games']} games, "
              f"right in {d['model_right']} ({d['model_right_pct']:.1%})")
    print(f"  RMSE vs margin  model {s['model']['rmse']}   line {s['market']['rmse']}")
    print(f"  MAE  vs margin  model {s['model']['mae']}   line {s['market']['mae']}")
    mw = s["market_weight"]
    print(f"  market weight   beta {mw['beta']} (se {mw['se']}), "
          f"mean |disagreement| {s['mean_abs_disagreement']}, dog share {s['dog_share']}")
    for k, v in s["ats"].items():
        n = v["w"] + v["l"]
        if not n:
            continue
        print(f"  ATS {k:>3} off  {v['w']}-{v['l']}-{v['p']}  {v['win_pct']:.1%}  "
              f"p={_p_one_sided(v['w'], n):.3f}  {v['units']:+.1f}u")
    if graded:
        win, spread = verdict(card)
        print(f"  WINNER test: {'PASS' if win else 'FAIL'}   SPREAD test: {'PASS' if spread else 'FAIL'}")


def main() -> None:
    games = common.load_games(2026)
    reps = models(games, 2026)
    hold, tune_s = list(common.HOLDOUT_SEASONS), list(common.TUNE_SEASONS)
    print(f"HOLDOUT {hold[0]}-{hold[-1]}, regular season; sigma fit on {tune_s[0]}-{tune_s[-1]}")
    for name, rep in reps.items():
        sigma = common.fit_sigma(rep.filter(pl.col("season").is_in(tune_s)))
        show(name, common.report_card(rep.filter(pl.col("season").is_in(hold)), sigma))

    print("\n--- 2026 to date: a live look, graded by nothing ---")
    for name, rep in reps.items():
        sigma = common.fit_sigma(rep.filter(pl.col("season").is_in(tune_s)))
        live = rep.filter(pl.col("season") == 2026)
        card = common.report_card(live, sigma)
        if card["games"]:
            show(name, card, graded=False)


if __name__ == "__main__":
    main()
