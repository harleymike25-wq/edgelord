"""Why a losing pick lost.

Two halves, deliberately separable. `compute_miss` derives everything it can
from what is already stored -- how far the projection was off, how badly the
pick lost against its number, which rows of the model's own decision table
argued for the losing side -- and costs nothing. `explain` then hands those
figures back to the model to interpret, which costs a call.

The split is the point. The arithmetic is checkable and the prose is not, so a
post-mortem whose numbers are computed can be regenerated and unit-tested,
while one that is entirely model-written is a second opinion with no audit
trail. When the model is unavailable or the budget is spent, the maths still
lands.

A post-mortem is not automatically a lesson. Nine losses over one week of
football is a sample that teaches noise far more readily than signal, so the
prompt below is written to let the model return "this was variance, change
nothing" -- and that verdict is a success, not a failure to find something.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import config, track

# How much a decision-table row moved the pick, as a sortable number.
WEIGHT_RANK = {"decisive": 4, "strong": 3, "moderate": 2, "slight": 1, "none": 0}

# `favors` values that name no side.
NEUTRAL_FAVORS = {"", "neither", "none", "n/a"}

VERDICTS = ("thesis_wrong", "thesis_right_variance", "bad_input", "data_gap")


def _severity(points_short: float) -> str:
    """How badly the pick lost against its number.

    Separating a half-point loss from a three-touchdown one is most of the
    value here: they are the same -1.00 in the ledger and completely different
    events. Only the second is evidence the reasoning was wrong.
    """
    if points_short <= 1:
        return "photo_finish"
    if points_short <= 3:
        return "near_miss"
    if points_short <= 7:
        return "clear"
    if points_short <= 14:
        return "decisive"
    return "blowout"


def _factor_split(decision_table: list[dict], pick_side: str) -> dict:
    """Sort the model's own ledger into the rows that were right and wrong.

    A row favouring the side we backed argued for a pick that lost, so it was
    wrong on this game. A row favouring the other side was right and got
    outvoted -- those are the ones worth reading.
    """
    wrong: list[dict] = []
    right: list[dict] = []
    unavailable: list[dict] = []

    for d in decision_table:
        favors = str(d.get("favors") or "").strip()
        weight = str(d.get("weight") or "").strip().lower()
        row = {
            "factor": d.get("factor"),
            "reading": d.get("reading"),
            "favors": favors,
            "weight": weight,
        }
        if weight == "none" or favors.lower() in NEUTRAL_FAVORS:
            unavailable.append(row)
        elif favors == pick_side:
            wrong.append(row)
        else:
            right.append(row)

    by_weight = lambda r: -WEIGHT_RANK.get(r["weight"], 0)  # noqa: E731
    wrong.sort(key=by_weight)
    right.sort(key=by_weight)

    return {
        "argued_for_pick": wrong,
        "argued_against_pick": right,
        "carried_no_side": unavailable,
        "heaviest_wrong": wrong[0] if wrong else None,
        "heaviest_right": right[0] if right else None,
    }


UNAVAILABLE = ("Out", "Doubtful")


def status_changes(pack: dict, final: list[dict]) -> list[dict]:
    """Starters whose availability changed between the pick and kickoff.

    The pack holds the injury report as it stood when the pick was made; the
    final report can say something different by game day. Without this the
    review saw only the pick and the score, so a pick that named "if Daniels is
    ruled out the pick dies", lost after Daniels was ruled out, and was never
    re-run came back as variance.

    `final` is that week's nflverse injury rows for both teams. Only players
    who matter are kept: anyone flagged a starter at pick time, and any
    quarterback. A player newly ruled out who was not on the report at all has
    no usage figure in the pack, so only quarterbacks are reported from that
    group rather than guessing at who else started.
    """
    final_by = {
        (r.get("team"), r.get("full_name")): r.get("report_status") for r in final
    }
    changes: list[dict] = []
    seen: set[tuple] = set()

    for side in ("home", "away"):
        block = pack.get(side) or {}
        team = block.get("team")
        for inj in block.get("injuries") or []:
            key = (team, inj.get("player"))
            seen.add(key)
            if not (inj.get("starter") or inj.get("position") == "QB"):
                continue
            before = inj.get("status")
            after = final_by.get(key)
            was_out, now_out = before in UNAVAILABLE, after in UNAVAILABLE
            if was_out != now_out:
                changes.append({
                    "team": team, "player": inj.get("player"),
                    "position": inj.get("position"),
                    "status_at_pick": before, "final_status": after,
                })

    teams = {(pack.get(s) or {}).get("team") for s in ("home", "away")}
    for r in final:
        key = (r.get("team"), r.get("full_name"))
        if (key in seen or r.get("team") not in teams or r.get("position") != "QB"
                or r.get("report_status") not in UNAVAILABLE):
            continue
        changes.append({
            "team": r.get("team"), "player": r.get("full_name"), "position": "QB",
            "status_at_pick": None, "final_status": r.get("report_status"),
        })
    return changes


def compute_miss(row: dict, final_injuries: list[dict] | None = None) -> dict:
    """Everything about a loss that can be derived rather than asserted.

    `row` is a prediction joined to its result and its game. Sign convention
    follows the rest of the codebase: `line_at_pick` reads "the side we picked
    is favoured by this many points", so a negative line is a dog.
    """
    pick_type = row["pick_type"]
    side = row["pick_side"]
    home = row["home_team"]
    hs, as_ = row["home_score"], row["away_score"]

    line = track.effective_line(
        pick_type, side, home, row["line_at_pick"],
        row.get("spread_line"), row.get("total_line"),
    )

    miss: dict = {
        "pick_type": pick_type,
        "pick_side": side,
        "line": line,
        "home_team": home,
        "away_team": row["away_team"],
        "home_score": hs,
        "away_score": as_,
        "confidence": row.get("confidence"),
        "conviction": row.get("conviction"),
        "clv_points": row.get("clv_points"),
        "profit_units": row.get("profit_units"),
    }

    if pick_type == "spread" and line is not None:
        actual = (hs - as_) if side == home else (as_ - hs)
        projected_home = row.get("projected_margin")
        projected = (
            None if projected_home is None
            else (projected_home if side == home else -projected_home)
        )
        points_short = line - actual

        miss.update({
            "underdog": line < 0,
            "actual_margin": actual,
            "projected_margin": projected,
            # What the model thought it was getting. A pick that lost with a
            # projected edge of 0.5 was never much of a bet in the first place.
            "projected_edge": None if projected is None else round(projected - line, 2),
            "projection_error": (
                None if projected is None else round(projected - actual, 2)
            ),
            "points_short": round(points_short, 2),
            "severity": _severity(points_short),
        })
    elif pick_type == "total" and line is not None:
        actual_total = hs + as_
        projected_total = row.get("projected_total")
        points_short = (
            (line - actual_total) if side == "over" else (actual_total - line)
        )
        miss.update({
            "underdog": None,
            "actual_total": actual_total,
            "projected_total": projected_total,
            "projected_edge": (
                None if projected_total is None
                else round(
                    (projected_total - line) if side == "over"
                    else (line - projected_total), 2
                )
            ),
            "projection_error": (
                None if projected_total is None
                else round(projected_total - actual_total, 2)
            ),
            "points_short": round(points_short, 2),
            "severity": _severity(points_short),
        })
    else:
        # No number to grade against; the result row exists but there is no
        # arithmetic to do. Recorded rather than skipped so the gap is visible.
        miss.update({"underdog": None, "points_short": None, "severity": None})

    # A pick whose own projection sat on the wrong side of its own number was
    # never a positive-expectation bet, whatever the game then did. Computed
    # rather than left to the reviewer, because reading it off the signs is
    # exactly the arithmetic that has already gone wrong once: the DAL/NYG
    # write-up argued for "Dallas plus the field goal" while Dallas was laying
    # three, and the first review accepted that framing and called it variance.
    edge = miss.get("projected_edge")
    miss["contradicted_own_projection"] = None if edge is None else edge <= 0

    try:
        decision = json.loads(row.get("decision_table") or "[]")
    except (ValueError, TypeError):
        decision = []
    miss["factors"] = _factor_split(decision, side)

    try:
        miss["key_factors"] = json.loads(row.get("key_factors") or "[]")
    except (ValueError, TypeError):
        miss["key_factors"] = []

    # None means the comparison could not be made, which is not the same as an
    # empty list saying nothing changed.
    try:
        pack = json.loads(row.get("pack") or "null")
    except (ValueError, TypeError):
        pack = None
    miss["changed_after_pick"] = (
        None if pack is None or final_injuries is None
        else status_changes(pack, final_injuries)
    )

    return miss


LOSS_SQL = """
    SELECT p.id, p.game_id, p.pick_type, p.pick_side, p.line_at_pick,
           p.confidence, p.conviction, p.projected_margin, p.projected_total,
           p.headline, p.paragraph, p.key_factors, p.decision_table,
           g.season, g.week, g.home_team, g.away_team, g.spread_line,
           g.total_line, g.gameday,
           r.home_score, r.away_score, r.clv_points, r.profit_units,
           f.data_gaps, f.payload AS pack,
           pm.prediction_id AS existing
    FROM results r
    JOIN predictions p ON p.id = r.prediction_id
    JOIN games g ON g.game_id = r.game_id
    LEFT JOIN features f ON f.id = p.features_id
    LEFT JOIN post_mortems pm ON pm.prediction_id = p.id
    WHERE r.pick_result = 'loss'
      AND p.superseded_by IS NULL
      AND p.run_label != 'backtest'
"""


def losing_picks(conn, *, season: int | None = None, week: int | None = None,
                 only_missing: bool = True) -> list[dict]:
    """Live losing picks, most recent first.

    Superseded re-predicts are excluded for the same reason the record excludes
    them: they are the same bet reconsidered, not separate losses. Backtests are
    excluded because they never risked anything.
    """
    sql = LOSS_SQL
    params: list = []
    if season is not None:
        sql += " AND g.season = ?"
        params.append(season)
    if week is not None:
        sql += " AND g.week = ?"
        params.append(week)
    if only_missing:
        # "Missing" means missing a narrative, not missing a row. A `--no-model`
        # pass stores the arithmetic with no prose, and that must not be what
        # stops the model pass from ever filling it in.
        sql += " AND (pm.prediction_id IS NULL OR pm.explanation IS NULL)"
    sql += " ORDER BY g.season DESC, g.week DESC, g.gameday DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


SYSTEM_PROMPT = """\
You are reviewing a losing NFL bet that you yourself made, to work out what \
should be learned from it -- if anything.

You are given the original write-up and pick, the factors you weighed at the \
time, the actual result, and a computed breakdown of the miss.

THE CENTRAL QUESTION is not "why did this lose" -- you can read the score. It \
is whether the REASONING was wrong, or whether the reasoning was sound and the \
game simply landed the other way. Those demand opposite responses and \
conflating them is how a model talks itself into chasing noise.

A single NFL game carries roughly 13 points of standard error against any \
projection. So:

- A pick that lost by half a point, or lost while your projection was within a \
few points of the real margin, is almost always variance. Say so plainly and \
recommend changing nothing. "The process was fine and the result was bad" is a \
complete and correct answer.
- A pick that lost by three touchdowns, or where your projection was 20+ points \
from the actual margin, is evidence something in the reasoning was actually \
broken. Find the specific thing.

Do not manufacture a lesson to seem useful. Do not treat one game as proof of \
a pattern. If the honest answer is that you would make the same pick again, \
that is the answer.

ONE EXCEPTION, AND IT IS NOT NEGOTIABLE. If \
`contradicted_own_projection` is true, the pick needed the side to beat a \
number that your own projection said it would not beat -- `projected_edge` is \
zero or negative. That is not a close call that went badly; it is a bet with no \
edge by its own arithmetic, and it would have been wrong even if it had won. \
You may NOT return "thesis_right_variance" in that case. Say plainly that the \
pick contradicted its own number, and check whether the write-up misread which \
side was favoured -- `line` is stated as "the side we picked is favoured by \
this many points", so a POSITIVE line means the pick was LAYING those points, \
not receiving them. Describing a positive line as "plus the points" or as \
getting push protection is a sign error, and it is the error to report.

A SECOND EXCEPTION. `changed_after_pick` lists starters whose availability \
changed between when the pick was made and kickoff. If one of them is a \
quarterback, or a player the write-up named as a condition ("if X is ruled out \
the pick dies"), the pick was made on information that was no longer true when \
the game was played. That is "bad_input", not "thesis_right_variance", even \
when the projection error looks like ordinary noise -- the thesis was never \
tested against the game that was actually played. Say which change it was and \
that the pick should have been re-run. A change to a minor player, or one the \
write-up already assumed, does not trigger this. An empty list means nothing \
changed; null means the comparison was unavailable.

`factors.argued_for_pick` lists the rows of your own decision table that \
pointed at the side that lost -- those are the candidates for having been \
wrong. `factors.argued_against_pick` lists the rows that pointed the other way \
and got outvoted; if one of those turned out to be the thing that decided the \
game, it was underweighted, and that is the most useful finding available.

SET `verdict` TO ONE OF:

- "thesis_right_variance" -- the argument was sound, the projection was close, \
the game landed badly. Expect this often; it is the honest verdict for most \
losses.
- "thesis_wrong" -- the central claim about what the market was mispricing was \
simply incorrect, and the game showed why.
- "bad_input" -- the reasoning followed correctly from a figure that was itself \
misleading (stale prior-season efficiency, a roster continuity number that \
missed a key departure, an injury not reflected).
- "data_gap" -- something absent from the pack decided the game, and no \
reasoning over what was present could have caught it.

`explanation` is 160-240 words, three short paragraphs, whatever the verdict. \
A variance call needs as much evidence as a broken thesis, not less.
1. The result against the projection: projected margin, actual margin, how \
far apart in standard-error terms, and how much the pick missed covering by.
2. A factor audit. Take the two or three heaviest rows in \
`argued_for_pick` and say whether the result is consistent with each one or \
cuts against it. Then name the strongest row in `argued_against_pick` and say \
whether it looks like the thing that decided the game. Use only what you are \
given: you have the final score and the computed miss, not the play-by-play, \
so do not invent drives, turnovers or injuries.
3. The verdict and the evidence for it. No hedging filler.

`lesson` is one or two sentences, under 40 words, stating what to do \
differently in future. A lesson must be transferable to other games: "weight \
prior-season efficiency lower when continuity is under 50%" is useful, \
"Carolina is bad" is not. When the honest answer is that nothing should \
change, say "No change:" and then the specific reason this game was variance \
(e.g. "lost by one point on a projection two points from the real margin") -- \
never a stock phrase that could be pasted onto any loss.\
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": list(VERDICTS),
            "description": (
                "Whether the reasoning was wrong or the game was variance."
            ),
        },
        "explanation": {
            "type": "string",
            "description": (
                "160-240 words in three short paragraphs: the result against "
                "the projection, a factor audit, then the verdict with evidence."
            ),
        },
        "lesson": {
            "type": "string",
            "description": (
                "One or two transferable sentences under 40 words, or 'No "
                "change:' plus the specific reason this loss was variance."
            ),
        },
    },
    "required": ["verdict", "explanation", "lesson"],
    "additionalProperties": False,
}


def build_prompt(row: dict, miss: dict) -> str:
    """The original argument, the result, and the computed miss."""
    try:
        gaps = json.loads(row.get("data_gaps") or "[]")
    except (ValueError, TypeError):
        gaps = []

    return (
        f"{row['away_team']} at {row['home_team']}, "
        f"{row['season']} week {row['week']} ({row['gameday']}).\n\n"
        f"FINAL: {row['home_team']} {row['home_score']}, "
        f"{row['away_team']} {row['away_score']}\n\n"
        f"THE PICK YOU MADE\n"
        f"headline: {row.get('headline') or '(none recorded)'}\n\n"
        f"{row['paragraph']}\n\n"
        f"COMPUTED MISS\n```json\n{json.dumps(miss, indent=1)}\n```\n\n"
        f"DATA GAPS AT THE TIME ({len(gaps)})\n"
        + ("\n".join(f"- {g}" for g in gaps[:12]) if gaps else "- none recorded")
        + "\n\nReview this loss and return your assessment."
    )


def explain(conn, row: dict, miss: dict, *, model: str | None = None,
            effort: str | None = None, budget: float | None = None) -> dict:
    """Ask the model to interpret its own loss. One call.

    Routed through the same budget guard and usage recording as a prediction,
    so review calls cannot quietly escape the monthly ceiling.
    """
    # Imported here so the deterministic path never needs the anthropic SDK.
    import anthropic  # noqa: F401

    from . import predict as predictor

    model = model or config.MODEL
    effort = effort or config.PREDICT_EFFORT
    predictor.check_budget(conn, budget=budget)

    request = {
        "model": model,
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        "messages": [{"role": "user", "content": build_prompt(row, miss)}],
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
    cost = predictor._record(
        conn, row["game_id"], "postmortem", response.model, usage
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined to review {row['game_id']}")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"no text block returned for {row['game_id']}")

    out = json.loads(text)
    out["_model"] = response.model
    out["_cost_usd"] = cost
    return out


def store(conn, row: dict, miss: dict, narrative: dict | None) -> None:
    """Persist one post-mortem, replacing any earlier review of the same pick."""
    conn.execute(
        "INSERT OR REPLACE INTO post_mortems (prediction_id, game_id, created_at, "
        "model, miss, verdict, explanation, lesson) VALUES (?,?,?,?,?,?,?,?)",
        (
            row["id"],
            row["game_id"],
            datetime.now().isoformat(timespec="seconds"),
            (narrative or {}).get("_model"),
            json.dumps(miss),
            (narrative or {}).get("verdict"),
            (narrative or {}).get("explanation"),
            (narrative or {}).get("lesson"),
        ),
    )


def load(conn, season: int, *, week: int | None = None) -> dict[int, dict]:
    """Stored post-mortems by prediction id, for rendering."""
    sql = (
        "SELECT pm.* FROM post_mortems pm "
        "JOIN games g ON g.game_id = pm.game_id WHERE g.season = ?"
    )
    params: list = [season]
    if week is not None:
        sql += " AND g.week = ?"
        params.append(week)

    out: dict[int, dict] = {}
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        try:
            d["miss"] = json.loads(d["miss"])
        except (ValueError, TypeError):
            d["miss"] = {}
        out[d["prediction_id"]] = d
    return out


def _final_injuries(seasons: set[int]) -> dict[tuple, list[dict]] | None:
    """The last injury report for each (season, week), or None if unavailable."""
    if not seasons:
        return {}
    try:
        from .sources import nflverse
        df = nflverse.injuries(sorted(seasons))
    except Exception:  # noqa: BLE001 -- a missing report must not stop the review
        return None
    out: dict[tuple, list[dict]] = {}
    for r in df.select(
        "season", "week", "team", "full_name", "position", "report_status"
    ).to_dicts():
        out.setdefault((r["season"], r["week"]), []).append(r)
    return out


def generate(conn, *, season: int | None = None, week: int | None = None,
             regenerate: bool = False, with_model: bool = True,
             budget: float | None = None, limit: int | None = None,
             on_event=None) -> dict:
    """Write a post-mortem for every losing pick that lacks one.

    The computed miss is always stored. The narrative is attempted per loss and
    a failure on one does not abandon the rest -- a budget ceiling reached
    halfway through a slate should still leave the maths for every loss and the
    prose for the ones that fit.
    """
    from . import predict as predictor

    rows = losing_picks(conn, season=season, week=week, only_missing=not regenerate)
    if limit is not None:
        rows = rows[:limit]

    out = {"losses": len(rows), "computed": 0, "explained": 0,
           "failed": 0, "cost_usd": 0.0, "errors": []}

    injuries = _final_injuries({r["season"] for r in rows})

    for row in rows:
        final = None
        if injuries is not None:
            final = injuries.get((row["season"], row["week"]), [])
        miss = compute_miss(row, final)
        narrative = None

        if with_model:
            try:
                narrative = explain(conn, row, miss, budget=budget)
                out["cost_usd"] += narrative.get("_cost_usd") or 0.0
                out["explained"] += 1
            except predictor.BudgetExceeded as exc:
                # Stop calling, but keep what has already been computed.
                out["errors"].append(f"{row['game_id']}: {exc}")
                with_model = False
            except Exception as exc:  # noqa: BLE001
                out["failed"] += 1
                out["errors"].append(f"{row['game_id']}: {exc}")

        store(conn, row, miss, narrative)
        conn.commit()
        out["computed"] += 1
        if on_event:
            on_event(row, miss, narrative)

    out["cost_usd"] = round(out["cost_usd"], 4)
    return out
