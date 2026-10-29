"""The shadow predictor: who wins first, the line last.

The live predictor hands the model the market spread as its prior and asks
how far to move it. Every pick is a nudge to the market's number, which is
why edges cluster at half a point and a point. This runs beside it on the
same games and asks the opposite way round:

1. Code computes a baseline (the QB-adjusted Elo from `edgelord.models`) and a
   fixed checklist of ten factors, each with the evidence for it lifted from
   the pack. Every game gets the same ten, so no factor can be left out.
2. The model sees the pack with the line removed -- no spread, no moneyline,
   no ATS records, no past spreads -- and reviews each factor: which team it
   helps, what it is worth in points, and how far the evidence can be
   trusted.
3. Code adds the points up. The sum IS the projected margin; the model never
   states a margin it then has to reconcile with its own factors. Each
   factor's points are first scaled by a correction learned from graded games
   (`edgelord.calibration`), so a factor the model keeps overrating counts for
   less. The prompt never changes.
4. Only then is the line brought back, in code: the side, the edge, and a
   tier that needs the model's sum and the QB-adjusted Elo to agree.

Shadow picks live in their own table. They are graded beside the live picks
by `report()` and never touch the official record, rechecks or the site. The
rules for judging them were written before the first one was made: see
VERIFIED.md, 2026-10-21.
"""

from __future__ import annotations

import json
import math
from datetime import datetime

import polars as pl

from . import config
from . import predict as predictor

# Ordered as the model should reason: the baseline first, then the
# adjustments for what this game has that the baseline does not.
CHECKLIST: tuple[tuple[str, str, str], ...] = (
    ("team_strength", "Team strength",
     "How good is each team overall, on a neutral field, with the quarterbacks "
     "and rosters their results were built on?"),
    ("quarterback", "Quarterback",
     "Is either team starting a different or diminished quarterback from the "
     "one its results were built on, and how much better is one starter than "
     "the other beyond what team strength already counts?"),
    ("availability", "Injuries and availability",
     "Which starters are out or limited, and where do the absences cluster?"),
    ("pass_game", "Pass offense vs pass defense",
     "Does either passing attack meet a defence it should beat, or one that "
     "should stop it?"),
    ("run_game", "Run offense vs run defense",
     "Does either running game meet a defence it should beat, or one that "
     "should stop it?"),
    ("pressure", "Pressure vs protection",
     "Can either pass rush beat the protection it faces?"),
    ("form", "Recent form",
     "Has either team been clearly better or worse lately than over the "
     "season, for a reason that should last?"),
    ("rest_travel", "Rest and travel",
     "Short week, bye, long trip, time zones, back-to-back road games."),
    ("weather", "Weather",
     "Wind, cold, rain or a roof, and which offence it hurts more."),
    ("home_field", "Home field",
     "The home edge at this venue, or none at a neutral site."),
)
FACTOR_KEYS = tuple(k for k, _, _ in CHECKLIST)

# One NFL game against a good projection has a standard deviation of about
# 13.5 points; the QB-adjusted Elo fit 13.5 on 2017-2021.
SIGMA = 13.5

# Tiers. `edge` is the factor sum's margin against the line toward the picked
# side; `baseline_edge` the QB-adjusted Elo's, toward the same side. The
# best-bet bar was 2.0, carried over from the live predictor, whose edges are
# nudges off the line. A blind sum lands 2.5-4 points off the line as a matter
# of course, so 2.0 made 9 of Week 7's 14 picks best bets. Raised to 4.0 at the
# owner's call on 2026-10-25, before any of those games kicked off.
BEST_BET_EDGE = 4.0
BEST_BET_BASELINE_EDGE = 1.0
LEAN_EDGE = 1.0


# --- what the model sees -----------------------------------------------------

def blind_view(pack: dict) -> dict:
    """The pack as the live model sees it, minus everything that reveals the line.

    The market block goes, and so does anything priced off a spread: ATS
    splits, and head-to-head spreads and covers. Straight-up records stay --
    they are results, not the market's opinion.
    """
    view = predictor.model_view(pack)
    view.pop("market", None)
    for side in ("home", "away"):
        block = dict(view.get(side) or {})
        splits = block.get("splits")
        if isinstance(splits, dict):
            block["splits"] = {
                k: ({kk: vv for kk, vv in v.items() if "ats" not in kk}
                    if isinstance(v, dict) else v)
                for k, v in splits.items()
                # As favourite / as underdog are the market's labels.
                if not k.startswith("as_")
            }
        view[side] = block
    matchup = dict(view.get("matchup") or {})
    h2h = matchup.get("head_to_head")
    if isinstance(h2h, dict):
        matchup["head_to_head"] = {
            k: ([{kk: vv for kk, vv in m.items() if kk not in ("spread_line", "covered")}
                 for m in v] if k == "recent" and isinstance(v, list) else v)
            for k, v in h2h.items()
            if "ats" not in k
        }
    view["matchup"] = matchup
    return view


def _units(pack: dict, offense: str) -> dict | None:
    for u in ((pack.get("matchup") or {}).get("unit_ratings") or {}).get("units") or []:
        if str(u.get("matchup", "")).startswith(f"{offense} offense"):
            return u
    return None


def _eff(pack: dict, side: str, window: str, unit: str, *keys: str) -> dict:
    block = ((pack.get(side) or {}).get(window) or {}).get(unit) or {}
    return {k: block.get(k) for k in keys if k in block}


def checklist(pack: dict, baseline: dict | None) -> list[dict]:
    """The ten factors, each with its evidence, in the order to review them."""
    home = pack["game"]["home_team"]
    away = pack["game"]["away_team"]
    sit = pack.get("situation") or {}
    b = baseline or {}

    def team(side, key):
        return (pack.get(side) or {}).get(key)

    def record(side):
        reg = team(side, "regression_indicators") or {}
        return {k: reg.get(k) for k in ("wins", "losses", "ties", "point_diff_per_game") if k in reg}

    evidence = {
        "team_strength": {
            "elo_neutral_points_home_minus_away": b.get("strength_points"),
            "note": ("Elo from every final score since 2002, before home field and "
                     "before any quarterback change; points on a neutral field."),
            home: {"record": record("home"),
                   "season_efficiency_adj": {
                       "offense_epa": _eff(pack, "home", "efficiency_season", "offense", "epa_adj").get("epa_adj"),
                       "defense_epa_allowed": _eff(pack, "home", "efficiency_season", "defense", "epa_adj").get("epa_adj")}},
            away: {"record": record("away"),
                   "season_efficiency_adj": {
                       "offense_epa": _eff(pack, "away", "efficiency_season", "offense", "epa_adj").get("epa_adj"),
                       "defense_epa_allowed": _eff(pack, "away", "efficiency_season", "defense", "epa_adj").get("epa_adj")}},
            "data_provenance": {home: team("home", "efficiency_provenance"),
                                away: team("away", "efficiency_provenance")},
        },
        "quarterback": {
            home: {"starter": team("home", "quarterback"),
                   "situation": team("home", "quarterback_situation"),
                   "season": (team("home", "player_form") or {}).get("quarterback_season"),
                   "last_5": (team("home", "player_form") or {}).get("quarterback_last_5")},
            away: {"starter": team("away", "quarterback"),
                   "situation": team("away", "quarterback_situation"),
                   "season": (team("away", "player_form") or {}).get("quarterback_season"),
                   "last_5": (team("away", "player_form") or {}).get("quarterback_last_5")},
            "computed_qb_change_points_home_minus_away": b.get("qb_points"),
            "note": ("The computed figure is how much better or worse each team's "
                     "listed starter is than the quarterbacks its results were "
                     "built on, net of the other side. Zero means no change."),
        },
        "availability": {
            home: {"injuries": team("home", "injuries"),
                   "roster_continuity": (team("home", "roster_turnover") or {}).get("overall_continuity")},
            away: {"injuries": team("away", "injuries"),
                   "roster_continuity": (team("away", "roster_turnover") or {}).get("overall_continuity")},
        },
        "pass_game": {
            f"{home} pass offense": _eff(pack, "home", "efficiency_season", "offense", "pass_epa", "sack_rate"),
            f"{away} pass defense": _eff(pack, "away", "efficiency_season", "defense", "pass_epa"),
            f"{away} pass offense": _eff(pack, "away", "efficiency_season", "offense", "pass_epa", "sack_rate"),
            f"{home} pass defense": _eff(pack, "home", "efficiency_season", "defense", "pass_epa"),
        },
        "run_game": {
            f"{home} run offense": _eff(pack, "home", "efficiency_season", "offense", "rush_epa"),
            f"{away} run defense": _eff(pack, "away", "efficiency_season", "defense", "rush_epa"),
            f"{away} run offense": _eff(pack, "away", "efficiency_season", "offense", "rush_epa"),
            f"{home} run defense": _eff(pack, "home", "efficiency_season", "defense", "rush_epa"),
        },
        "pressure": {
            f"{home} offense vs {away} defense": (_units(pack, home) or {}).get("pressure"),
            f"{away} offense vs {home} defense": (_units(pack, away) or {}).get("pressure"),
        },
        "form": {
            home: {"season": _eff(pack, "home", "efficiency_season", "offense", "epa_adj", "success_adj"),
                   "last_5": _eff(pack, "home", "efficiency_last_5", "offense", "epa_adj", "success_adj"),
                   "def_season": _eff(pack, "home", "efficiency_season", "defense", "epa_adj"),
                   "def_last_5": _eff(pack, "home", "efficiency_last_5", "defense", "epa_adj")},
            away: {"season": _eff(pack, "away", "efficiency_season", "offense", "epa_adj", "success_adj"),
                   "last_5": _eff(pack, "away", "efficiency_last_5", "offense", "epa_adj", "success_adj"),
                   "def_season": _eff(pack, "away", "efficiency_season", "defense", "epa_adj"),
                   "def_last_5": _eff(pack, "away", "efficiency_last_5", "defense", "epa_adj")},
        },
        "rest_travel": {home: sit.get("home"), away: sit.get("away"),
                        "kickoff_slot": sit.get("kickoff_slot")},
        "weather": pack.get("weather"),
        "home_field": {"neutral_site": sit.get("neutral_site"),
                       "international": sit.get("international"),
                       "divisional": sit.get("divisional"),
                       "venue": sit.get("venue"),
                       "computed_home_field_points": b.get("home_field_points")},
    }
    return [{"factor": k, "label": label, "question": q, "evidence": evidence[k]}
            for k, label, q in CHECKLIST]


SYSTEM_PROMPT = """\
You are predicting an NFL game: who wins and by how much. You are NOT shown \
the betting line, on purpose. Predict the game itself, from the football.

You get the full data pack, a computed baseline, and a CHECKLIST of ten \
factors with the evidence for each. Review every factor, in order, and score \
it. Your projected margin is the SUM of your factor points -- it is added up \
for you -- so the number and the reasoning cannot drift apart.

HOW TO SCORE A FACTOR:
- `favors`: the team it helps, or "neither".
- `points`: what it is worth on the final margin, toward that team, in points \
(0 or more). Zero is a fine answer when the factor shows nothing.
- `evidence`: "solid" (a season of this year's data or a clear fact such as a \
confirmed absence), "thin" (a few games, a quarterback under about 200 \
dropbacks, one noisy split), or "stale" (mostly last season's figures, or a \
roster that has largely turned over). Score thin and stale evidence smaller.
- `reading`: one sentence, carrying the figure it rests on.

DO NOT COUNT ANYTHING TWICE. `team_strength` is the baseline: how good each \
team has been overall, with the quarterbacks and rosters its results were \
built on. It already contains each team's usual passing game, running game, \
pass rush and form. Every other factor is an ADJUSTMENT for what THIS game has \
that the baseline does not:
- `quarterback`: a different, injured or clearly declining starter from the \
one the results were built on. A healthy incumbent is already in \
team_strength, so his factor is usually 0. A starting quarterback change can \
be worth 3-7 points or more.
- `availability`: starters missing now who played in the results.
- `pass_game`, `run_game`, `pressure`: a SPECIFIC mismatch in this pairing -- \
a strong unit meeting a weak one -- beyond each team's overall level. Most \
games have one real mismatch at most; a typical mismatch is worth 0.5-2 points.
- `form`: a recent change with a reason that should last (a new starter, a \
scheme change, a healed line), not a hot or cold streak.
- `rest_travel`, `weather`: usually 0-1.5 points.
- `home_field`: usually 1-2 points to the home team, 0 at a neutral site.

The computed figures in the checklist (Elo strength, the quarterback-change \
figure, home field) come from a model fit on ten seasons of results. Use them \
as your starting point for those factors. Depart from them when the pack shows \
something they cannot see -- an injury, a new starter, a roster that turned \
over -- and say why.

SIZE THE POINTS HONESTLY. Do not shade every factor toward zero to stay \
cautious: a team that is clearly better should be projected to win clearly. \
NFL margins average about ten points; a sum near zero means you genuinely \
think the game is a coin flip, not that you are unsure.

ALSO RETURN:
- `projected_total`: total points scored, from both offences against both \
defences, pace and weather.
- `headline`: one line, under 15 words: who wins and the reason, with no \
statistics or analytics terms.
- `paragraph`: three short paragraphs separated by blank lines. (1) Who wins \
and why, in a sentence or two. (2) The matchup or player that decides it. \
(3) What could flip it. Readers see this; the computed baseline means nothing \
to them, so do not mention it here -- that goes in `baseline_disagreement`.

WRITE THE HEADLINE AND PARAGRAPH FOR A FOOTBALL FAN, NOT AN ANALYST: players \
by name, the matchup that decides it, what the injury means on the field. \
Translate numbers into football -- not "-0.12 EPA per dropback" but "he has \
been holding the ball and taking sacks for a month". No EPA, success rate, \
CPOE, dropbacks or continuity in either, and at most one plain number per \
paragraph. Be confident and vivid, with some bite. The figures belong in each \
factor's `reading`, which is not shown to readers.
- `baseline_disagreement`: one sentence on the biggest reason your number \
differs from the computed baseline, or "agree".
"""

_FACTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "favors": {"type": "string", "description": "Team abbreviation, or 'neither'."},
        "points": {"type": "number", "description": "Worth on the margin toward `favors`, 0 or more."},
        "evidence": {"type": "string", "enum": ["solid", "thin", "stale"]},
        "reading": {"type": "string", "description": "One sentence with the figure."},
    },
    "required": ["favors", "points", "evidence", "reading"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "factors": {
            "type": "object",
            "properties": {k: _FACTOR_SCHEMA for k in FACTOR_KEYS},
            "required": list(FACTOR_KEYS),
            "additionalProperties": False,
        },
        "projected_total": {"type": "number"},
        "headline": {"type": "string"},
        "paragraph": {"type": "string"},
        "baseline_disagreement": {"type": "string"},
    },
    "required": ["factors", "projected_total", "headline", "paragraph",
                 "baseline_disagreement"],
    "additionalProperties": False,
}


def build_prompt(pack: dict, baseline: dict | None) -> str:
    game = pack["game"]
    b = baseline or {}
    base = {
        "projected_home_margin": b.get("projected_home"),
        "home_win_prob": b.get("home_win_prob"),
        "note": ("QB-adjusted Elo. It names winners well but is no better than "
                 "anyone at margins; treat it as a starting point, not an answer."),
    }
    return (
        f"Predict this game.\n\n"
        f"{game['away_team']} at {game['home_team']} -- "
        f"{game['gameday']} {game.get('gametime_et') or ''} ET, "
        f"week {game['week']} of {game['season']}.\n\n"
        f"BASELINE\n```json\n{json.dumps(base, indent=1)}\n```\n\n"
        f"CHECKLIST\n```json\n{json.dumps(checklist(pack, baseline), indent=1, default=str)}\n```\n\n"
        f"FULL PACK (no line)\n```json\n{json.dumps(blind_view(pack), indent=1, default=str)}\n```"
    )


# --- the computed baseline ---------------------------------------------------

def baselines(season: int, *, games=None, qbg=None) -> dict[str, dict]:
    """QB-adjusted Elo for every game of `season`, as of before each kickoff."""
    from .models import common, elo, qb

    games = games if games is not None else common.load_games(season)
    qbg = qbg if qbg is not None else qb.qb_games(season)
    ep, qp = elo.DEFAULT, qb.DEFAULT
    rep = qb.replay(games, qbg, qp, ep).filter(pl.col("season") == season)
    out = {}
    neutral = dict(zip(games["game_id"].to_list(), games["neutral"].to_list()))
    for r in rep.iter_rows(named=True):
        hfa = 0.0 if neutral.get(r["game_id"]) else ep.hfa / ep.elo_per_point
        proj = r["projected"]
        out[r["game_id"]] = {
            "projected_home": proj,
            "home_win_prob": None if proj is None else round(win_prob(proj), 3),
            "strength_points": round((r["elo_home"] - r["elo_away"]) / ep.elo_per_point, 1),
            "qb_points": None if r["qb_diff"] is None else round(qp.scale * r["qb_diff"], 1),
            "home_field_points": round(hfa, 2),
        }
    return out


def win_prob(margin: float) -> float:
    return 0.5 * (1 + math.erf(margin / (SIGMA * math.sqrt(2))))


# --- the line, brought back in code -------------------------------------------

def assemble(pack: dict, out: dict, baseline: dict | None,
             calibration: dict | None = None) -> dict:
    """Sum the factors, then compare to the line. Pure arithmetic.

    `calibration` is `edgelord.calibration.current()`: one learned multiplier
    per factor, applied to the model's points before they are summed. The raw
    points are kept beside the corrected ones so the correction can be learned
    again from what the model actually said.
    """
    home = pack["game"]["home_team"]
    away = pack["game"]["away_team"]
    raw = {}
    for k in FACTOR_KEYS:
        f = out["factors"][k]
        pts = max(0.0, float(f["points"]))
        raw[k] = pts if f["favors"] == home else -pts if f["favors"] == away else 0.0
    multipliers = (calibration or {}).get("multipliers")
    signed = ({k: round(v * multipliers.get(k, 1.0), 3) for k, v in raw.items()}
              if multipliers else dict(raw))
    margin = round(sum(signed.values()), 2)

    market = pack.get("market") or {}
    line = market.get("current_spread_home")
    base = (baseline or {}).get("projected_home")

    pick = edge = base_edge = None
    tier = None
    if line is not None:
        diff = margin - float(line)
        pick = home if diff > 0 else away if diff < 0 else (home if margin >= 0 else away)
        toward = 1 if pick == home else -1
        edge = round(diff * toward, 2)
        base_edge = None if base is None else round((base - float(line)) * toward, 2)
        if edge >= BEST_BET_EDGE and (base_edge or 0) >= BEST_BET_BASELINE_EDGE:
            tier = "best_bet"
        elif edge >= LEAN_EDGE and (base_edge or 0) > 0:
            tier = "lean"
        else:
            tier = "coin_flip"

    return {
        "raw_points": raw,
        "signed_points": signed,
        "raw_margin": round(sum(raw.values()), 2),
        "calibration": {"multipliers": multipliers,
                        "n_games": (calibration or {}).get("n_games", 0)},
        "projected_margin": margin,
        "home_win_prob": round(win_prob(margin), 3),
        "winner": home if margin > 0 else away if margin < 0 else None,
        "line_home": line,
        "total_line": market.get("current_total"),
        "pick_side": pick,
        "edge": edge,
        "baseline_margin": base,
        "baseline_edge": base_edge,
        "tier": tier,
    }


_WEIGHT_BY_POINTS = ((3.0, "decisive"), (2.0, "strong"), (1.0, "moderate"), (0.01, "slight"))


def _weight(points: float) -> str:
    return next((w for cut, w in _WEIGHT_BY_POINTS if points >= cut), "none")


def _fmt(n: float) -> str:
    return f"{n:g}"


def to_prediction(pack: dict, out: dict, calc: dict) -> dict:
    """The blind call in the shape the live `predict.store` and the site expect.

    The model named a winner without seeing the line, so its headline can call
    the Bears while the pick is the Patriots plus the points. The paragraph
    opens with one plain line tying the two together, and the headline says
    so when the pick is the side it expects to lose.
    """
    label = {k: lab for k, lab, _ in CHECKLIST}
    rows = []
    for k in FACTOR_KEYS:
        f = out["factors"][k]
        # Corrected points, so the factors shown add up to the margin shown.
        pts = abs(calc["signed_points"][k]) if "signed_points" in calc \
            else max(0.0, float(f["points"]))
        rows.append({
            "factor": label[k], "reading": f["reading"],
            "favors": f["favors"] if pts > 0 else "neither",
            "weight": _weight(pts), "_points": pts,
        })
    rows.sort(key=lambda r: -r["_points"])
    key_factors = [f"{r['factor']}: {r['favors']} +{_fmt(round(r['_points'], 1))}"
                   for r in rows if r["_points"] > 0][:5]
    for r in rows:
        r.pop("_points")

    home, away = pack["game"]["home_team"], pack["game"]["away_team"]
    margin, pick, winner = calc["projected_margin"], calc["pick_side"], calc["winner"]
    line_home = calc["line_home"]
    side_line = None if line_home is None else (line_home if pick == home else -line_home)
    # Book notation: the side laying points shows minus.
    shown = "pk" if not side_line else f"{-side_line:+g}"

    ours = f"{winner} by {_fmt(round(abs(margin), 1))}" if winner else "a dead heat"
    if not line_home:
        market = "a pick'em"
    else:
        market = f"{home if line_home > 0 else away} by {_fmt(abs(line_home))}"
    lead = f"Our number: {ours}. The market: {market}. The pick: {pick} {shown}."

    headline = out["headline"].rstrip(".")
    if winner and pick != winner:
        headline += f", but closer than the market thinks: {pick} {shown}"

    return {
        "pick_type": "spread",
        "pick_side": pick,
        # Chance the pick covers, from the edge over the line.
        "confidence": round(100 * win_prob(calc["edge"] or 0.0)),
        "projected_margin": margin,
        "projected_total": out["projected_total"],
        "headline": headline,
        "paragraph": f"{lead}\n\n{out['paragraph']}",
        "key_factors": key_factors,
        "decision_table": rows,
        "conviction": calc["tier"],
        "factor_points": {"raw": calc.get("raw_points"), "source": "model",
                          **(calc.get("calibration") or {})},
        "_model": out.get("_model"),
        "_cost_usd": out.get("_cost_usd"),
    }


def predict(pack: dict, conn, baseline: dict | None, *, model: str | None = None,
            effort: str | None = None, budget: float | None = None,
            run_label: str = "shadow") -> dict:
    """One blind call. Same spend guard and usage ledger as the live predictor."""
    model = model or config.MODEL
    effort = effort or config.PREDICT_EFFORT
    predictor.check_budget(conn, budget=budget)

    request = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        "messages": [{"role": "user", "content": build_prompt(pack, baseline)}],
    }
    client = predictor._client()
    if model in config.ALWAYS_THINKING_MODELS:
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": config.FALLBACK_MODEL}],
            **request,
        )
    else:
        response = client.messages.create(**request)

    usage = predictor._sum_usage(response)
    cost = predictor._record(conn, pack["game"]["game_id"], run_label, response.model, usage)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model and fallback both declined for {pack['game']['game_id']}")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"no text block returned for {pack['game']['game_id']}")

    out = json.loads(text)
    out["_model"] = response.model
    out["_cost_usd"] = cost
    return out


def store(conn, game_id: str, features_id: int | None, out: dict, calc: dict) -> int:
    cur = conn.execute(
        "INSERT INTO shadow_predictions (game_id, features_id, created_at, model, "
        "projected_margin, home_win_prob, projected_total, winner, baseline_margin, "
        "line_home, total_line, pick_side, edge, baseline_edge, tier, factors, "
        "headline, paragraph, baseline_disagreement, cost_usd, calibration) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            game_id, features_id, datetime.now().isoformat(timespec="seconds"),
            out.get("_model"), calc["projected_margin"], calc["home_win_prob"],
            out["projected_total"], calc["winner"], calc["baseline_margin"],
            calc["line_home"], calc["total_line"], calc["pick_side"], calc["edge"],
            calc["baseline_edge"], calc["tier"], json.dumps(out["factors"]),
            out["headline"], out["paragraph"], out["baseline_disagreement"],
            out.get("_cost_usd"), json.dumps(calc.get("calibration")),
        ),
    )
    new_id = cur.lastrowid
    conn.execute(
        "UPDATE shadow_predictions SET superseded_by = ? WHERE game_id = ? AND id != ? "
        "AND superseded_by IS NULL",
        (new_id, game_id, new_id),
    )
    return new_id


# --- grading, beside the live picks -----------------------------------------

def _ats(side_home: bool, line_home: float, margin: int) -> str:
    cover = (margin - line_home) if side_home else (line_home - margin)
    return "win" if cover > 0 else "loss" if cover < 0 else "push"


def report(conn, season: int) -> dict:
    """Shadow against live on the games both picked and that have finished.

    Spread picks are graded at the line each was made against; closing line
    value against the schedule's closing spread. Underdog and favourite picks
    are split, because 2026's live record was carried by an underdog run.
    """
    rows = conn.execute(
        """
        SELECT s.game_id, s.pick_side AS s_side, s.line_home AS s_line, s.winner AS s_winner,
               s.tier AS s_tier,
               g.home_team, g.away_team, g.home_score, g.away_score, g.spread_line AS close_home,
               p.pick_side AS l_side, p.line_at_pick AS l_line, p.pick_type AS l_type,
               p.projected_margin AS l_margin, r.pick_result AS l_result
        FROM shadow_predictions s
        JOIN games g ON g.game_id = s.game_id
        LEFT JOIN predictions p ON p.game_id = s.game_id AND p.superseded_by IS NULL
             AND p.run_label != 'backtest'
        LEFT JOIN results r ON r.prediction_id = p.id
        WHERE s.superseded_by IS NULL AND g.season = ? AND g.home_score IS NOT NULL
        """,
        (season,),
    ).fetchall()

    def blank():
        return {"w": 0, "l": 0, "p": 0}

    out = {
        "games": 0,
        "shadow": {"winners": blank(), "ats": blank(), "dog": blank(), "fav": blank(),
                   "by_tier": {}, "clv": []},
        "live": {"winners": blank(), "ats": blank(), "dog": blank(), "fav": blank(), "clv": []},
        "market_favourite_winners": blank(),
    }

    def add(block, res):
        block[{"win": "w", "loss": "l", "push": "p"}[res]] += 1

    for r in rows:
        out["games"] += 1
        margin = r["home_score"] - r["away_score"]
        actual = r["home_team"] if margin > 0 else r["away_team"] if margin < 0 else None

        # Shadow
        if r["s_winner"]:
            add(out["shadow"]["winners"], "push" if actual is None
                else "win" if r["s_winner"] == actual else "loss")
        if r["s_side"] and r["s_line"] is not None:
            home_side = r["s_side"] == r["home_team"]
            res = _ats(home_side, r["s_line"], margin)
            add(out["shadow"]["ats"], res)
            side_line = r["s_line"] if home_side else -r["s_line"]
            add(out["shadow"]["dog" if side_line < 0 else "fav"], res)
            out["shadow"]["by_tier"].setdefault(r["s_tier"], blank())
            add(out["shadow"]["by_tier"][r["s_tier"]], res)
            if r["close_home"] is not None:
                close_side = r["close_home"] if home_side else -r["close_home"]
                # Points of line value: getting more, or laying less, than close.
                out["shadow"]["clv"].append(close_side - side_line)

        # Live, spread picks only
        if r["l_type"] == "spread" and r["l_result"]:
            add(out["live"]["ats"], r["l_result"])
            home_side = r["l_side"] == r["home_team"]
            # line_at_pick reads "picked side favoured by", so negative is a dog.
            add(out["live"]["dog" if (r["l_line"] or 0) < 0 else "fav"], r["l_result"])
            if r["l_margin"] is not None and actual is not None:
                live_winner = r["home_team"] if r["l_margin"] > 0 else r["away_team"]
                add(out["live"]["winners"], "win" if live_winner == actual else "loss")
            if r["close_home"] is not None and r["l_line"] is not None:
                close_side = r["close_home"] if home_side else -r["close_home"]
                out["live"]["clv"].append(close_side - r["l_line"])

        if r["close_home"] not in (None, 0) and actual is not None:
            fav = r["home_team"] if r["close_home"] > 0 else r["away_team"]
            add(out["market_favourite_winners"], "win" if fav == actual else "loss")

    for who in ("shadow", "live"):
        c = out[who]["clv"]
        out[who]["clv"] = round(sum(c) / len(c), 2) if c else None
    return out
