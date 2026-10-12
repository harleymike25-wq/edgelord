"""Claude prediction, one game at a time.

Uses structured outputs (`output_config.format`) rather than tool use, so the
response is guaranteed to parse. Opus 4.8 takes adaptive thinking and rejects
`temperature`/`top_p`/`top_k`, so none are sent.

The system prompt does two jobs beyond framing. It states the sign conventions
explicitly, since a flipped spread would silently invert every pick. And it asks
for the number as a move off the market line -- `market_adjustment` -- rather
than as a margin projected from scratch, because a from-scratch margin drifts
toward a pick'em and a projection nearer zero than the spread argues for the
underdog in every game it touches. `derived_margin` turns the move back into the
home margin the rest of the system stores.
"""

from __future__ import annotations

import json
from datetime import datetime

import anthropic

from . import config

SYSTEM_PROMPT = """\
You are a quantitative NFL handicapper. For each game you receive a JSON pack of \
market, efficiency, situational and contextual data, and you produce one written \
assessment plus a recommended play.

CONVENTIONS — read carefully, these are easy to invert:
- `spread_home` is positive when the HOME team is favoured. A `current_spread_home` \
of 3.0 means the home team is laying 3 points.
- `market_adjustment` is what you return in place of a margin: how many points \
you move the market spread, positive toward the HOME team. 0 means the number is \
right. Moving a home favourite of 3 by -2 makes it a 1-point home win; moving it \
by +2 makes it a 5-point home win.
- Efficiency EPA values are per play. For OFFENSE, higher is better. For DEFENSE, \
LOWER is better (a defensive EPA of -0.10 is a good defence).
- `epa_adj` and `success_adj` are opponent-adjusted; prefer them over the raw values.

HOW TO WEIGH THE INPUTS:
- The market number is the single sharpest forecast available. Treat it as the \
prior and look for reasons it may be mispriced, rather than building your own \
number from scratch and being surprised when it disagrees.
- Key numbers matter disproportionately. In the NFL roughly one game in seven \
lands on exactly 3 and one in seventeen on exactly 7. Crossing 3 is worth far \
more than half a point anywhere else.
- `season_record` is each team's record and point differential this season. \
Luck measures (record against points scored, close-game record, turnover \
margin, field-goal percentages, last season's luck) are deliberately not in \
the pack: the line already prices them, and "due to regress" is not a reason \
to take a side. Build the case from matchups, quarterbacks, injuries and the \
number itself.
- Recent-form splits (`efficiency_last_5`) matter more than season-to-date when \
they diverge sharply, but small samples are noisy — say which you are leaning on.
- `matchup.unit_ratings` pairs each offence against the defence it will actually \
face, which is the question a game turns on. Read it before the team blocks: a \
team can be better overall while losing the pairing that decides the game. \
`edge` is offence minus what the defence allows, so positive favours the \
offence; pressure is the exception and is stated from the defence's side. \
`biggest_mismatch` names the largest gap — lead from it when it is real.
- `player_form` is where team efficiency hides things. A team can carry a good \
season EPA while its quarterback has collapsed over the last month — compare \
`quarterback_season` against `quarterback_last_5` and say so when they diverge. \
Those describe whoever has thrown the most, not who plays this week. When a \
team has `quarterback_situation`, its listed starter is hurt or did not start \
last time: judge the quarterback by the expected starter's own line in \
`candidates`, weigh its sample size, and say if the starter is still uncertain. \
Usage matters as much as efficiency: a back with 160 carries at -0.08 EPA is a \
bigger problem than a third receiver at the same rate.
- `head_to_head` now reaches back roughly ten seasons with scores, lines and \
who covered. Use it for genuine patterns — a matchup that repeatedly lands \
under, a team that owns a venue — not as a narrative. Rosters and coaches turn \
over, so a 2017 result says little about this week.
- There is no officiating data. Do not list referees or officiating as a factor.

STATE YOUR NUMBER AS A MOVE, NOT A SCORE:
You do not return a projected margin. You return `market_adjustment` — how far \
you move the market's number, and which way. The size of that move is your edge \
in points; its direction names the side you should be taking. Those are not two \
separate judgements, and they must agree: if you move the number toward the away \
team, the away team is your pick.

This is asked for in this shape on purpose. A margin produced from scratch drifts \
toward a close game, because a number near a pick'em is the safest guess when the \
inputs are noisy. But the spread is ALREADY the market's best estimate, and a \
projection that sits closer to zero than the spread makes the underdog look like \
value in every game it happens to — regardless of what the matchup says. An edge \
manufactured that way is an artefact of hedging, not a read, and it points at the \
dog every time.

So treat a move toward a closer game as a claim like any other. Make it only when \
you can name the mechanism and say roughly what it is worth. If you cannot say \
WHY the market's margin is too wide, the honest adjustment is 0.

0 is a good answer and should be a common one. Most games are priced correctly \
and the right response to a correctly priced game is a small adjustment and a \
"coin_flip", not a manufactured reason to move the number. Moving it toward the \
favourite is equally available to you whenever the case is there.

ALWAYS PICK A SIDE, THEN RATE YOUR CONVICTION:
Every game gets a side. There is no pass option and no "none" -- if the pack is \
thin, say so in the write-up and still name the side you would take at gunpoint. \
Even a coin-flip game leans fractionally one way, and that view is worth \
recording. What varies is not whether you have a pick but how much it is worth \
acting on, and that is what `conviction` captures.

A single NFL game outcome has a standard error of roughly 13 points against any \
projection, so your number differing from the market by a point or two is \
usually noise. The market number is set by people with better information than \
this pack contains. That does not stop you having a lean — it stops the lean \
being worth betting.

Set `conviction` to one of:

- "best_bet" — you would actually put money on this. Requires EITHER a \
`market_adjustment` of at least 2 points toward the side you are taking (at \
least 3 when `efficiency_provenance` \
shows the figures are mostly prior-season, or `roster_turnover` reports \
continuity below about 0.7 for either team), OR a move of at least a point \
that carries the number across 3 or 7, when the figures are not mostly \
prior-season. If the key number is doing the work, say so.

- "lean" — you have a side and mild reasons for it, but the edge is inside the \
noise. A lean is a recorded opinion, \
not a recommendation to bet. A lean needs a `market_adjustment` of at least 1 \
point toward your side.

- "coin_flip" — your `market_adjustment` is under 1 point either way: you think \
the line is about right and are naming a side only because every game gets one. \
Call it that in the write-up: start the paragraph with "Coin flip:" and the side \
(e.g. "Coin flip: Rams -3.5."), never "Lean". Then say in a sentence why the \
number looks right, and what tipped you to this side.

On a normal slate expect a handful of best bets, then leans and coin flips. If most of a \
card comes back "best_bet", the bar has been set too low.

The edge you describe in the paragraph must match `market_adjustment`. Do not \
claim "three points of value" while moving the number by one.

ARGUE THE PICK, DO NOT NARRATE IT:
The market number already reflects everything obvious about both teams. So a \
write-up that lists true facts about them explains nothing — the question is \
always the same one: WHAT IS THE MARKET GETTING WRONG, AND WHY?

Every pick needs a thesis of that shape. Name the specific thing being \
mispriced, then explain the mechanism that makes it a mispricing:

  Weak (a fact, and one the market already knows):
    "Chicago has a +22 turnover margin and an 11-6 record."

  Also weak (a well-known pattern, not a mispricing):
    "Chicago's record is built on turnover luck, so they are due to regress."

  Strong (a thesis, with the causal link spelled out):
    "Chicago's season EPA is still being priced, but it was built with a left \
    tackle who went on IR three weeks ago. Since then their pressure rate \
    allowed has doubled and the quarterback's EPA per dropback has gone from \
    +0.15 to -0.05. The line has moved half a point; the offence it is pricing \
    no longer exists."

The test for every claim you make: does it explain why the NUMBER is wrong, or \
does it just describe a team? If it only describes a team, it belongs in \
`key_factors` as a stat, not in the prose as an argument.

Be concrete about the mechanism. "Regression" is not an argument by itself — \
say what regresses, why it regresses, and roughly how many points it is worth \
against this specific line. If your case rests on a quarterback's recent form, \
say what changed and what it costs per drive. If it rests on a key number, say \
which number and why the game is likely to land near it.

DATA GAPS:
The `data_gaps` array lists what is missing or unavailable for this game. Reason \
around those gaps — do not fill them in from memory or assumption. If line \
movement is unavailable, do not speculate about which way the number moved. If \
public betting percentages are null, do not guess at them; that data has no free \
source and its absence is expected.

YOUR OUTPUT:
- `headline` is one sentence under 20 words: the call and the reason the market \
is wrong, with no statistics in it. It is what someone reads while scrolling a \
slate of sixteen games, so it should carry the argument, not just the side. \
"Take the Jets plus the points" says nothing; "Baltimore is priced on a healthy \
Lamar Jackson who has not shown up in a month" says everything.

- `paragraph` is 150-220 words in THREE SHORT PARAGRAPHS separated by blank \
lines. Never one unbroken block. Each does a distinct job:

  (1) THE THESIS. The call, and the one thing the market is mispricing. Lead \
with the disagreement, not with a description of the teams.

  (2) THE MECHANISM. Why that mispricing exists and what it is worth in points. \
This is the paragraph that has to earn the pick — walk the causal chain from \
the evidence to the number.

  (3) THE CASE AGAINST. The strongest argument for the other side, and the \
specific thing that would kill the pick. If a move to 13 would end it, say so.

  Write so it can be read at a glance. A wall of prose with figures buried \
mid-sentence is unreadable — carry at most two or three numbers per paragraph \
and put the rest in `key_factors`, which is displayed separately. Prefer "an \
8% sack rate" to "a sack rate of 8.1% (26 sacks on 321 dropbacks) against a \
league average of 6.9%". Round: 0.086 EPA/play is "+0.09", 77.4% is "77%". \
Anything past two significant figures is noise dressed as precision.
- `confidence` is 1-100 and should be honestly calibrated. Most NFL sides are close \
to a coin flip against the spread; a confidence above 65 should be rare and \
earned. Do not inflate it to seem decisive.
- `pick_type` is the market you are calling: "spread" or "total". Always one of \
the two, always with a side in `pick_side`.
- `key_factors` is 2-5 short phrases naming the specific inputs you leaned on, \
each carrying its number: "Herbert -0.16 EPA/dropback", "47% defensive continuity", \
"line sits on 3". These are rendered as tags beside the write-up, so this is \
where precise figures belong rather than in the prose.
- `decision_table` is the ledger behind the call: 5-10 rows, one per factor \
you actually weighed. Unlike the paragraph, which argues a case, this must \
include the factors that cut against your pick and the ones that turned out \
not to matter -- a table showing only supporting evidence is not a record of \
a decision. Set `favors` to the team abbreviation a factor points to, or \
"neither". Set `weight` honestly: most rows in a coin-flip game are "slight" \
or "moderate", and "decisive" should appear at most once. If a factor was \
unavailable, say so in `reading` and give it weight "none" rather than \
omitting the row.\
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "pick_type": {
            "type": "string",
            "enum": ["spread", "total"],
            "description": "Which market you are calling. A side is required.",
        },
        "pick_side": {
            "type": "string",
            "description": (
                "Team abbreviation for a spread pick, or 'over'/'under' for a "
                "total. Never empty -- every game gets a side."
            ),
        },
        "conviction": {
            "type": "string",
            "enum": ["best_bet", "lean", "coin_flip"],
            "description": (
                "How much the pick is worth acting on. 'best_bet' clears the "
                "edge bar and is worth betting; 'lean' is a modest view at least "
                "a point off the line; 'coin_flip' is under a point, the line "
                "about right."
            ),
        },
        "confidence": {
            "type": "integer",
            "description": (
                "Calibrated confidence from 1 to 100. Above 65 should be rare."
            ),
        },
        "market_adjustment": {
            "type": "number",
            "description": (
                "How many points you move the market spread, positive toward "
                "the HOME team. 0 means the number is right. Moving a home "
                "favourite of 3 by -2 makes it a 1-point home win. The size of "
                "this move is your edge in points and its direction names your "
                "side, so it must agree with pick_side."
            ),
        },
        "projected_total": {
            "type": "number",
            "description": "Projected combined points.",
        },
        "headline": {
            "type": "string",
            "description": (
                "One sentence, under 20 words: the call and the single reason "
                "for it. No statistics -- this is the line someone reads while "
                "scrolling."
            ),
        },
        "paragraph": {
            "type": "string",
            "description": (
                "150-220 words in two or three short paragraphs separated by a "
                "blank line. Conclusion first, then the evidence, then the "
                "case against."
            ),
        },
        "key_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-5 short phrases naming the inputs that drove the pick.",
        },
        "decision_table": {
            "type": "array",
            "description": (
                "5-10 rows auditing the decision, including factors that argued "
                "against the pick and factors that were unavailable."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "factor": {
                        "type": "string",
                        "description": "The input, named plainly: 'Quarterback form', 'Weather'.",
                    },
                    "reading": {
                        "type": "string",
                        "description": "What it says, carrying the figure. Under 15 words.",
                    },
                    "favors": {
                        "type": "string",
                        "description": "Team abbreviation this points to, or 'neither'.",
                    },
                    "weight": {
                        "type": "string",
                        "enum": ["decisive", "strong", "moderate", "slight", "none"],
                        "description": "How much this moved the pick.",
                    },
                },
                "required": ["factor", "reading", "favors", "weight"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "pick_type",
        "pick_side",
        "conviction",
        "confidence",
        "market_adjustment",
        "projected_total",
        "headline",
        "paragraph",
        "key_factors",
        "decision_table",
    ],
    "additionalProperties": False,
}


def derived_margin(pack: dict, result: dict) -> float:
    """The home margin implied by the model's move off the market number.

    The model is asked how far it moves the line, not what the final margin
    will be, and this turns that move back into a margin so nothing downstream
    has to know the difference.

    Asking for the margin directly produced numbers systematically shrunk
    toward a pick'em, and a projection closer to zero than the spread makes the
    underdog look like value whatever the matchup says -- so the side was being
    chosen by the shrinkage rather than by the factors. Stating the move makes
    it an argument the write-up has to carry instead of a hedge the format
    invites. A missing market number falls back to a pick'em baseline, which
    keeps the field meaning the same thing in the rare game with no line.
    """
    spread = (pack.get("market") or {}).get("current_spread_home")
    base = 0.0 if spread is None else float(spread)
    return round(base + float(result["market_adjustment"]), 2)


# The best-bet bar the prompt describes, applied in code. Two weeks of stored
# picks showed the model does not hold itself to it: Week 2 had seven picks
# moving the number 2+ points and none were rated best_bet. The prompt is left
# alone so the picks themselves are unchanged; only the rating moves out of the
# model's hands.
BEST_BET_EDGE = 2.0
# Raised while the efficiency figures are mostly last season's, or a roster has
# largely turned over -- the same conditions the prompt names.
BEST_BET_EDGE_THIN = 3.0
LOW_CONTINUITY = 0.7
# A move of at least a point that carries the number across 3 or 7 also
# qualifies: that is where a point is worth the most.
KEY_NUMBERS = (3.0, 7.0)
KEY_NUMBER_MIN_EDGE = 1.0
# Under a point off the line the model is saying the number is right and naming
# a side only because every game gets one. From 2026 Week 6 those are labelled
# coin flips, so "lean" means a real if modest view rather than 71% of picks.
COIN_FLIP_EDGE = 1.0


def _thin_evidence(pack: dict) -> bool:
    for side in ("home", "away"):
        block = pack.get(side) or {}
        prov = block.get("efficiency_provenance") or {}
        if (prov.get("prior_season_weight") or 0) >= 0.5:
            return True
        cont = (block.get("roster_turnover") or {}).get("overall_continuity")
        if cont is not None and cont < LOW_CONTINUITY:
            return True
    return False


def align_side(pack: dict, result: dict) -> bool:
    """Make the pick the side the model's own number favours. True if it moved.

    The prompt says the move and the side must agree, but nothing enforced it:
    2026 W1 took DAL with its own projection 3.5 points on the Giants' side of
    the line. A pick against its own number is not a judgement, it is a slip,
    so the side follows the number and the write-up says so up front.
    A zero move leaves the model's side alone -- every game still gets one.
    """
    market = pack.get("market") or {}
    game = pack.get("game") or {}
    side = result.get("pick_side")
    if result.get("pick_type") == "spread":
        if market.get("current_spread_home") is None:
            return False
        adj = float(result["market_adjustment"])
        home, away = game.get("home_team"), game.get("away_team")
        want = home if adj > 0 else away if adj < 0 else side
        gap = abs(adj)
    elif result.get("pick_type") == "total":
        total = market.get("current_total")
        if total is None:
            return False
        diff = float(result["projected_total"]) - float(total)
        want = "over" if diff > 0 else "under" if diff < 0 else side
        gap = abs(diff)
    else:
        return False
    if want == side:
        return False
    result["pick_side"] = want
    # The number moved the side, but the reasoning argued the other one, so a
    # switched pick is never rated above a lean.
    result["_side_switched"] = True
    result["paragraph"] = (
        f"[Pick switched from {side} to {want}: the model's own projection "
        f"favours {want} by {gap:g} against the line.]\n\n" + result["paragraph"]
    )
    return True


def computed_conviction(pack: dict, result: dict) -> str:
    """'best_bet', 'lean' or 'coin_flip', decided by arithmetic, not the model.

    Edge is the move off the line toward the picked side, in points. Spread
    picks work in the picked side's terms: the line is the market's margin for
    that side (positive = favoured), the projection is the line plus the edge,
    and a key number counts when the projection reaches it from a line short
    of it -- a dog at +3.5 projected to lose by 2.5, a favourite at -2.5
    projected to win by 3.
    """
    market = pack.get("market") or {}
    thin = _thin_evidence(pack)
    if result["pick_type"] == "spread":
        spread = market.get("current_spread_home")
        if spread is None:
            return "lean"
        home = result["pick_side"] == pack["game"]["home_team"]
        adj = float(result["market_adjustment"])
        edge = adj if home else -adj
        line = float(spread) if home else -float(spread)
        proj = line + edge
        crosses = any(
            line < k <= proj for key in KEY_NUMBERS for k in (key, -key)
        )
        # The key-number shortcut is for a sharp number, not a soft one. It used
        # to skip the thin-evidence bar entirely: 2026 W5 LV +3.5 was promoted
        # on a 1.5-point edge with 60% of both teams' figures from 2025, and
        # lost by 24.5.
        if crosses and edge >= KEY_NUMBER_MIN_EDGE and not thin:
            return "lean" if result.get("_side_switched") else "best_bet"
    elif result["pick_type"] == "total":
        total = market.get("current_total")
        if total is None:
            return "lean"
        diff = float(result["projected_total"]) - float(total)
        edge = diff if result["pick_side"] == "over" else -diff
    else:
        return "lean"
    bar = BEST_BET_EDGE_THIN if thin else BEST_BET_EDGE
    if edge >= bar:
        return "lean" if result.get("_side_switched") else "best_bet"
    return "coin_flip" if edge < COIN_FLIP_EDGE else "lean"


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.anthropic_key())


# What the model sees of each team's record. The rest of `regression_indicators`
# is luck measures, and `prior_season_record` is last season's: both are priced
# into the line (tested on 2017-2025), yet the model rated them "strong" on
# about half of 2026's bigger edges, nearly all underdogs. They stay in the
# stored pack and on the site.
SEASON_RECORD_FIELDS = (
    "gp", "wins", "losses", "ties", "points_for", "points_against",
    "point_diff_per_game",
)


def model_view(pack: dict) -> dict:
    """The pack as sent to the model, with the luck measures removed."""
    view = {**pack}
    for side in ("home", "away"):
        block = dict(pack.get(side) or {})
        reg = block.pop("regression_indicators", None)
        block.pop("prior_season_record", None)
        if reg:
            block["season_record"] = {k: reg[k] for k in SEASON_RECORD_FIELDS if k in reg}
        view[side] = block
    return view


def build_prompt(pack: dict) -> str:
    game = pack["game"]
    pack = model_view(pack)
    return (
        f"Analyse this game and return your assessment.\n\n"
        f"{game['away_team']} at {game['home_team']} — "
        f"{game['gameday']} {game.get('gametime_et') or ''} ET, "
        f"week {game['week']} of {game['season']}.\n\n"
        f"```json\n{json.dumps(pack, indent=1)}\n```"
    )


class BudgetExceeded(RuntimeError):
    """Raised before a call that would push this month past the spend ceiling."""


def month_spend(conn, when: datetime | None = None) -> float:
    """Model spend so far this calendar month, in USD."""
    month = (when or datetime.now()).strftime("%Y-%m")
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) total FROM api_usage "
        "WHERE strftime('%Y-%m', called_at) = ?",
        (month,),
    ).fetchone()
    return float(row["total"])


def check_budget(conn, *, budget: float | None = None) -> float:
    """Stop before the call, not after. Returns spend so far."""
    ceiling = config.MONTHLY_BUDGET_USD if budget is None else budget
    spent = month_spend(conn)
    if spent >= ceiling:
        raise BudgetExceeded(
            f"month-to-date model spend ${spent:.2f} has reached the "
            f"${ceiling:.2f} ceiling; raise EDGELORD_MONTHLY_BUDGET_USD to continue"
        )
    return spent


def _record(conn, game_id: str | None, run_label: str, model: str,
            usage: dict) -> float:
    cost = config.cost_usd(model, usage["input_tokens"], usage["output_tokens"])
    conn.execute(
        "INSERT INTO api_usage (called_at, game_id, run_label, model, "
        "input_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?,?,?)",
        (
            datetime.now().isoformat(timespec="seconds"),
            game_id, run_label, model,
            usage["input_tokens"], usage["output_tokens"], round(cost, 6),
        ),
    )
    conn.commit()
    return cost


def _sum_usage(response) -> dict:
    """Total tokens across every attempt, not just the one that answered.

    With fallbacks enabled a refused attempt and its rescue both appear in
    `usage.iterations`; the top-level `usage` covers only the attempt that
    produced the returned message, so billing off it alone under-counts.
    """
    iterations = getattr(response.usage, "iterations", None) or []
    if iterations:
        inp = sum(getattr(i, "input_tokens", 0) or 0 for i in iterations)
        out = sum(getattr(i, "output_tokens", 0) or 0 for i in iterations)
        if inp or out:
            return {"input_tokens": inp, "output_tokens": out}
    return {
        "input_tokens": response.usage.input_tokens or 0,
        "output_tokens": response.usage.output_tokens or 0,
    }


def predict(
    pack: dict,
    conn,
    *,
    model: str | None = None,
    effort: str | None = None,
    run_label: str = "manual",
    budget: float | None = None,
) -> dict:
    """One game, one call.

    Takes a connection so the spend guard and usage recording cannot be
    skipped by a caller that forgets them.
    """
    model = model or config.MODEL
    effort = effort or config.PREDICT_EFFORT
    check_budget(conn, budget=budget)

    request = {
        "model": model,
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        "messages": [{"role": "user", "content": build_prompt(pack)}],
    }

    client = _client()
    if model in config.ALWAYS_THINKING_MODELS:
        # Safety classifiers on these models can decline a request outright.
        # Without a fallback the call just fails; with one the API re-serves it
        # on the fallback model inside the same request. A decline before any
        # output is not billed, and the rescue bills at the fallback's rates.
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": config.FALLBACK_MODEL}],
            **request,
        )
    else:
        response = client.messages.create(**request)

    usage = _sum_usage(response)
    cost = _record(conn, pack["game"]["game_id"], run_label, response.model, usage)

    if response.stop_reason == "refusal":
        raise RuntimeError(
            f"model and fallback both declined for {pack['game']['game_id']}"
        )

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"no text block returned for {pack['game']['game_id']}")

    out = json.loads(text)
    align_side(pack, out)
    # Derived here rather than at storage time so the CLI, the report and the
    # stored row all read the same number off one calculation.
    out["projected_margin"] = derived_margin(pack, out)
    out["_model"] = response.model
    out["_usage"] = usage
    out["_cost_usd"] = cost
    return out


def _line_at_pick(pack: dict, result: dict) -> tuple[float | None, int | None]:
    """The number actually available when the pick was made.

    Stored so grading can separate 'was the pick right' from 'did we get the
    better side of the number', which is what closing line value measures.
    """
    market = pack.get("market", {})
    best = market.get("best_available") or {}

    if result["pick_type"] == "spread":
        side = result["pick_side"]
        home = pack["game"]["home_team"]
        book = best.get("best_home_spread" if side == home else "best_away_spread")
        if book:
            return book.get("line"), book.get("price")
        spread = market.get("current_spread_home")
        if spread is None:
            return None, None
        return (spread if side == home else -spread), None

    if result["pick_type"] == "total":
        book = best.get("best_over" if result["pick_side"] == "over" else "best_under")
        if book:
            return book.get("line"), book.get("price")
        return market.get("current_total"), None

    return None, None


def store(conn, game_id: str, features_id: int | None, pack: dict, result: dict,
          *, run_label: str) -> int:
    """Persist a prediction. Supersedes any earlier live prediction for this game."""
    line, price = _line_at_pick(pack, result)

    cur = conn.execute(
        "INSERT INTO predictions (game_id, features_id, model, created_at, run_label, "
        "pick_type, pick_side, conviction, model_conviction, line_at_pick, "
        "price_at_pick, confidence, projected_margin, projected_total, headline, "
        "paragraph, key_factors, decision_table) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            game_id,
            features_id,
            result.get("_model", config.MODEL),
            datetime.now().isoformat(timespec="seconds"),
            run_label,
            result["pick_type"],
            result["pick_side"],
            computed_conviction(pack, result),
            result.get("conviction", "lean"),
            line,
            price,
            result["confidence"],
            result["projected_margin"],
            result["projected_total"],
            result.get("headline"),
            result["paragraph"],
            json.dumps(result.get("key_factors", [])),
            json.dumps(result.get("decision_table", [])),
        ),
    )
    new_id = cur.lastrowid

    # Keep the older call on record rather than overwriting it -- the trail of
    # what the bot thought and when it changed its mind is the interesting part.
    if run_label != "backtest":
        conn.execute(
            "UPDATE predictions SET superseded_by = ? WHERE game_id = ? AND id != ? "
            "AND superseded_by IS NULL AND run_label != 'backtest'",
            (new_id, game_id, new_id),
        )
    return new_id
