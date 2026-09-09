"""Claude prediction, one game at a time.

Uses structured outputs (`output_config.format`) rather than tool use, so the
response is guaranteed to parse. Opus 4.8 takes adaptive thinking and rejects
`temperature`/`top_p`/`top_k`, so none are sent.

The system prompt does two jobs beyond framing: it states the sign conventions
explicitly (a flipped spread would silently invert every pick) and it tells the
model that passing is an acceptable answer. A model that must produce a play on
all sixteen games will invent edges on the twelve where it has none.
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
- `projected_margin` you return is the HOME team's margin: positive means the home \
team wins by that many.
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
- The regression indicators are the most reliable edge in the pack. A team with a \
large positive `pythagorean_delta`, a lopsided one-score record, an extreme \
turnover margin, or a freakish opponent field goal percentage is winning games in \
ways that do not persist. Say so when you see it.
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
Usage matters as much as efficiency: a back with 160 carries at -0.08 EPA is a \
bigger problem than a third receiver at the same rate.
- `head_to_head` now reaches back roughly ten seasons with scores, lines and \
who covered. Use it for genuine patterns — a matchup that repeatedly lands \
under, a team that owns a venue — not as a narrative. Rosters and coaches turn \
over, so a 2017 result says little about this week.
- Referee effects are weak and noisy. Mention them only when genuinely extreme, \
and never build a play on them.

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
projection edge of at least 2 points (at least 3 when `efficiency_provenance` \
shows the figures are mostly prior-season, or `roster_turnover` reports \
continuity below about 0.7 for either team), OR a clear key-number edge where \
the number itself is mispositioned — taking a dog at +3.5 on a game that \
projects near a field goal, say. If the key number is doing the work, say so.

- "lean" — you have a side and mild reasons for it, but the edge is inside the \
noise. This is the honest default for most games. A lean is a recorded opinion, \
not a recommendation to bet, and saying "this is close to a coin flip, I lean X" \
is a perfectly good lean.

On a normal slate expect a handful of best bets and mostly leans. If most of a \
card comes back "best_bet", the bar has been set too low.

The edge you describe in the paragraph must match your `projected_margin` \
against the market number. Do not claim "three points of value" while your \
projection sits one point from the line.

ARGUE THE PICK, DO NOT NARRATE IT:
The market number already reflects everything obvious about both teams. So a \
write-up that lists true facts about them explains nothing — the question is \
always the same one: WHAT IS THE MARKET GETTING WRONG, AND WHY?

Every pick needs a thesis of that shape. Name the specific thing being \
mispriced, then explain the mechanism that makes it a mispricing:

  Weak (a fact, and one the market already knows):
    "Chicago has a +22 turnover margin and an 11-6 record."

  Strong (a thesis, with the causal link spelled out):
    "Chicago's 11-6 record is bought almost entirely with takeaways, and \
    takeaway rate is close to random year over year. Strip the turnover luck \
    and their point differential says 8-9. The market is pricing the record; \
    the record is not real."

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
and put the rest in `key_factors`, which is displayed separately. Prefer "a \
+22 turnover margin" to "a turnover margin of +22 (+1.29 per game) against a \
league average of +0.0". Round: 0.086 EPA/play is "+0.09", 77.4% is "77%". \
Anything past two significant figures is noise dressed as precision.
- `confidence` is 1-100 and should be honestly calibrated. Most NFL sides are close \
to a coin flip against the spread; a confidence above 65 should be rare and \
earned. Do not inflate it to seem decisive.
- `pick_type` is the market you are calling: "spread" or "total". Always one of \
the two, always with a side in `pick_side`.
- `key_factors` is 2-5 short phrases naming the specific inputs you leaned on, \
each carrying its number: "pythagorean delta +0.21", "47% defensive continuity", \
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
            "enum": ["best_bet", "lean"],
            "description": (
                "How much the pick is worth acting on. 'best_bet' clears the "
                "edge bar and is worth betting; 'lean' is a recorded opinion "
                "whose edge sits inside the noise."
            ),
        },
        "confidence": {
            "type": "integer",
            "description": (
                "Calibrated confidence from 1 to 100. Above 65 should be rare."
            ),
        },
        "projected_margin": {
            "type": "number",
            "description": "Projected home margin; positive means the home team wins by this.",
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
                        "description": "The input, named plainly: 'Pythagorean regression', 'Weather'.",
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
        "projected_margin",
        "projected_total",
        "headline",
        "paragraph",
        "key_factors",
        "decision_table",
    ],
    "additionalProperties": False,
}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.anthropic_key())


def build_prompt(pack: dict) -> str:
    game = pack["game"]
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
        "pick_type, pick_side, conviction, line_at_pick, price_at_pick, confidence, "
        "projected_margin, projected_total, headline, paragraph, key_factors, "
        "decision_table) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            game_id,
            features_id,
            result.get("_model", config.MODEL),
            datetime.now().isoformat(timespec="seconds"),
            run_label,
            result["pick_type"],
            result["pick_side"],
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
