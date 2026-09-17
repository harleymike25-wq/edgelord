"""Slate report rendering."""

from __future__ import annotations

import html
import json
from datetime import datetime

from . import config, factor_tables, postmortem, track

# Plain-language equivalents of the stored enums. The raw values are fine in a
# database and unreadable on a page.
VERDICT_LABELS = {
    "thesis_wrong": "The reasoning was wrong",
    "thesis_right_variance": "The reasoning held; the game went the other way",
    "bad_input": "The reasoning followed a misleading input",
    "data_gap": "Decided by something missing from the pack",
}

SEVERITY_LABELS = {
    "photo_finish": "a point or less",
    "near_miss": "inside a key number",
    "clear": "a clear miss",
    "decisive": "the wrong side",
    "blowout": "not close",
}

CSS = """
body { font: 15px/1.6 -apple-system, Segoe UI, sans-serif; max-width: 860px;
       margin: 2rem auto; padding: 0 1.5rem; color: #1a1a1a; }
h1 { margin-bottom: .2rem; } .sub { color: #666; margin-top: 0; }
.game { border-top: 1px solid #e3e3e3; padding: 1.2rem 0; }
.matchup { font-weight: 600; font-size: 1.05rem; }
.meta { color: #666; font-size: .88rem; margin: .15rem 0 .6rem; }
.pick { display: inline-block; padding: .18rem .55rem; border-radius: 4px;
        font-weight: 600; font-size: .88rem; }
.spread, .total { background: #e8f0e8; color: #2d5c2d; }
.pass { background: #f0f0f0; color: #777; }
/* The pick's audit trail: every factor weighed, including the ones that
   argued the other way. Muted so it reads as reference beside the prose. */
table.decision { border-collapse: collapse; width: 100%; margin: .8rem 0 .2rem;
                 font-size: .82rem; }
table.decision th, table.decision td { text-align: left; padding: .3rem .5rem;
                 border-bottom: 1px solid #eee; vertical-align: top; }
table.decision thead th { color: #888; font-weight: 500; font-size: .72rem;
                 text-transform: uppercase; letter-spacing: .04em; }
table.decision tbody th { font-weight: 600; white-space: nowrap; }
table.decision td { color: #555; }
.w-decisive, .w-strong { color: #1a1a1a; font-weight: 600; }
.w-none { color: #aaa; }
/* Every measurement the pick was built on. Folded by default: it is reference
   material to check the argument against, not part of reading the slate. */
details.measures { margin: .6rem 0; }
details.measures summary { cursor: pointer; color: #666; font-size: .8rem; }
details.measures h4 { margin: 1rem 0 .3rem; font-size: .78rem; color: #444;
                 text-transform: uppercase; letter-spacing: .04em; }
table.measure { border-collapse: collapse; width: 100%; font-size: .8rem;
                 margin-bottom: .4rem; }
table.measure th, table.measure td { text-align: left; padding: .22rem .5rem;
                 border-bottom: 1px solid #f0f0f0; }
table.measure thead th { color: #888; font-weight: 500; }
table.measure tbody th { font-weight: 500; color: #333; white-space: nowrap; }
table.measure td { color: #555; text-align: right; }
.measure-note { color: #888; font-size: .76rem; margin: .2rem 0 .6rem; }
.conf { color: #666; font-size: .85rem; margin-left: .5rem; }
p.analysis { margin: .6rem 0 .4rem; }
.factors { color: #666; font-size: .85rem; }
table { border-collapse: collapse; margin: .8rem 0; font-size: .9rem; }
th, td { text-align: left; padding: .3rem .9rem .3rem 0; }
th { color: #666; font-weight: 500; }
.gaps { color: #999; font-size: .8rem; font-style: italic; }
/* Loss post-mortem. Deliberately unlike the pick it sits under -- this is a
   correction, not more of the argument, and it should not read as though the
   write-up is still making its case. */
.postmortem { border-left: 3px solid #c0392b; background: #fdf6f5;
              padding: .7rem .9rem; margin: .9rem 0;
              border-radius: 0 4px 4px 0; }
.postmortem h4 { margin: 0 0 .45rem; font-size: .74rem; letter-spacing: .05em;
              text-transform: uppercase; color: #c0392b; }
.postmortem .verdict { font-weight: 600; margin-bottom: .45rem; }
.postmortem dl { margin: 0 0 .55rem; font-size: .83rem; }
.postmortem dt { color: #777; font-weight: 500; }
.postmortem dd { margin: 0 0 .32rem; color: #333; }
.postmortem p { margin: .45rem 0; font-size: .9rem; }
.postmortem .lesson { font-weight: 600; font-size: .87rem; }
.postmortem .warn { color: #c0392b; font-weight: 600; }
"""



def _tables_md(tables: list[dict]) -> list[str]:
    """Every measurement, as markdown tables."""
    out: list[str] = []
    for t in tables:
        out += ["", f"**{t['title']}**", ""]
        if t["kind"] == "kv":
            out.append("| Measure | Value |")
            out.append("| --- | --- |")
            for k, v in t["rows"]:
                out.append(f"| {k} | {v} |")
        else:
            out.append("| " + " | ".join(str(h) for h in t["headers"]) + " |")
            out.append("| " + " | ".join("---" for _ in t["headers"]) + " |")
            for row in t["rows"]:
                out.append("| " + " | ".join(str(c) for c in row) + " |")
        if t.get("note"):
            out += ["", f"_{t['note']}_"]
    return out


def _tables_html(tables: list[dict]) -> str:
    """The same tables, folded behind a disclosure so the slate stays scannable."""
    parts: list[str] = []
    for t in tables:
        parts.append(f"<h4>{html.escape(str(t['title']))}</h4>")
        parts.append("<table class='measure'>")
        if t["kind"] == "kv":
            parts.append("<tbody>")
            for k, v in t["rows"]:
                parts.append(
                    f"<tr><th>{html.escape(str(k))}</th>"
                    f"<td>{html.escape(str(v))}</td></tr>"
                )
            parts.append("</tbody>")
        else:
            head = "".join(f"<th>{html.escape(str(h))}</th>" for h in t["headers"])
            parts.append(f"<thead><tr>{head}</tr></thead><tbody>")
            for row in t["rows"]:
                cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in row[1:])
                parts.append(
                    f"<tr><th>{html.escape(str(row[0]))}</th>{cells}</tr>"
                )
            parts.append("</tbody>")
        parts.append("</table>")
        if t.get("note"):
            parts.append(f"<p class='measure-note'>{html.escape(str(t['note']))}</p>")
    return (
        # Open by default: this is the evidence the pick is checked against,
        # and a disclosure the reader has to find is the same as not shipping it.
        "<details class='measures' open><summary>All measurements "
        f"({len(tables)} tables)</summary>{''.join(parts)}</details>"
    )


def _pack_tables(r: dict) -> list[dict]:
    try:
        pack = json.loads(r["payload"]) if r["payload"] else None
    except (ValueError, TypeError):
        return []
    if not pack:
        return []
    return factor_tables.build(pack, r["away_team"], r["home_team"])


def _slate_rows(conn, season: int, week: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.*, g.home_team, g.away_team, g.gameday, g.gametime, g.weekday,
               g.stadium, g.spread_line, g.total_line, f.data_gaps, f.payload
        FROM predictions p
        JOIN games g ON g.game_id = p.game_id
        LEFT JOIN features f ON f.id = p.features_id
        WHERE g.season = ? AND g.week = ? AND p.superseded_by IS NULL
        ORDER BY g.gameday, g.gametime
        """,
        (season, week),
    ).fetchall()
    return [dict(r) for r in rows]


def _describe_pick(r: dict) -> str:
    """Render a pick in the notation a bettor actually reads.

    `line_at_pick` is stored as "this side is favoured by N", but sportsbooks
    display the inverse: a team laying 7 shows as -7 and a team getting 7 shows
    as +7. Printing the stored value directly inverts every spread on the page.
    """
    if r["pick_type"] == "pass":
        return "No play"

    if r["pick_type"] == "total":
        line = r["line_at_pick"] if r["line_at_pick"] is not None else r["total_line"]
        return f"{r['pick_side'].title()} {line:g}" if line is not None else r["pick_side"]

    line = r["line_at_pick"]
    if line is None and r["spread_line"] is not None:
        line = r["spread_line"] if r["pick_side"] == r["home_team"] else -r["spread_line"]
    if line is None:
        return r["pick_side"]
    # `-0.0` would render as "-0" on a pick'em; normalise it away.
    return f"{r['pick_side']} {(-line if line else 0.0):+g}"


def _miss_lines(miss: dict) -> list[tuple[str, str]]:
    """The computed miss as label/value pairs, in reading order."""
    lines: list[tuple[str, str]] = []
    side = miss.get("pick_side")

    lines.append((
        "Final",
        f"{miss.get('home_team')} {miss.get('home_score')}, "
        f"{miss.get('away_team')} {miss.get('away_score')}",
    ))

    error = miss.get("projection_error")
    if miss.get("pick_type") == "spread" and miss.get("actual_margin") is not None:
        proj, actual = miss.get("projected_margin"), miss["actual_margin"]
        if proj is not None and error is not None:
            lines.append((
                "Projected vs actual",
                f"{side} {proj:+g} projected, {actual:+g} actual "
                f"(off by {abs(error):g})",
            ))
        else:
            lines.append(("Actual margin", f"{side} {actual:+g}"))
    elif miss.get("actual_total") is not None:
        proj = miss.get("projected_total")
        if proj is not None and error is not None:
            lines.append((
                "Projected vs actual",
                f"{proj:g} projected, {miss['actual_total']:g} actual "
                f"(off by {abs(error):g})",
            ))
        else:
            lines.append(("Actual total", f"{miss['actual_total']:g}"))

    short = miss.get("points_short")
    if short is not None:
        label = SEVERITY_LABELS.get(miss.get("severity") or "")
        lines.append((
            "Against the number",
            f"lost by {short:g}" + (f" — {label}" if label else ""),
        ))

    edge = miss.get("projected_edge")
    if edge is not None:
        lines.append(("Edge it claimed", f"{edge:+g} pts"))

    factors = miss.get("factors") or {}
    wrong, right = factors.get("heaviest_wrong"), factors.get("heaviest_right")
    if wrong:
        lines.append((
            "Heaviest factor that was wrong",
            f"{wrong['factor']} ({wrong['weight']}) — {wrong['reading']}",
        ))
    if right:
        lines.append((
            "Heaviest factor it outvoted",
            f"{right['factor']} ({right['weight']}) — {right['reading']}",
        ))
    return lines


def _post_mortem_md(pm: dict) -> list[str]:
    miss = pm.get("miss") or {}
    out = ["", "### Why this lost", ""]

    verdict = VERDICT_LABELS.get(pm.get("verdict") or "") or pm.get("verdict")
    if verdict:
        out += [f"**{verdict}**", ""]
    if miss.get("contradicted_own_projection"):
        out += [
            "> **No edge by its own arithmetic.** The pick needed a result its "
            "own projection did not forecast.",
            "",
        ]
    for label, value in _miss_lines(miss):
        out.append(f"- **{label}:** {value}")
    if pm.get("explanation"):
        out += ["", pm["explanation"]]
    if pm.get("lesson"):
        out += ["", f"**Lesson:** {pm['lesson']}"]
    return out


def _post_mortem_html(pm: dict) -> str:
    miss = pm.get("miss") or {}
    parts = ["<div class='postmortem'><h4>Why this lost</h4>"]

    verdict = VERDICT_LABELS.get(pm.get("verdict") or "") or pm.get("verdict")
    if verdict:
        parts.append(f"<div class='verdict'>{html.escape(str(verdict))}</div>")
    if miss.get("contradicted_own_projection"):
        parts.append(
            "<p class='warn'>No edge by its own arithmetic — the pick needed a "
            "result its own projection did not forecast.</p>"
        )

    parts.append("<dl>")
    for label, value in _miss_lines(miss):
        parts.append(
            f"<dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd>"
        )
    parts.append("</dl>")

    for para in (pm.get("explanation") or "").split("\n\n"):
        if para.strip():
            parts.append(f"<p>{html.escape(para.strip())}</p>")
    if pm.get("lesson"):
        parts.append(
            f"<p class='lesson'>Lesson: {html.escape(pm['lesson'])}</p>"
        )
    parts.append("</div>")
    return "".join(parts)


def render_markdown(conn, season: int, week: int) -> str:
    rows = _slate_rows(conn, season, week)
    mortems = postmortem.load(conn, season, week=week)
    out = [
        f"# Edgelord — {season} Week {week}",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
    ]
    if not rows:
        out.append("No predictions stored for this slate.")
        return "\n".join(out)

    plays = [r for r in rows if r["pick_type"] != "pass"]
    out.append(f"{len(plays)} plays, {len(rows) - len(plays)} passes, {len(rows)} games.")
    out.append("")

    for r in rows:
        out.append(f"## {r['away_team']} at {r['home_team']}")
        out.append(
            f"*{r['weekday']} {r['gameday']} {r['gametime'] or ''} ET — {r['stadium']}*"
        )
        out.append("")
        out.append(
            f"**{_describe_pick(r)}** · confidence {r['confidence']} · "
            f"projected {r['projected_margin']:+.1f} / {r['projected_total']:.1f}"
        )
        out.append("")
        out.append(r["paragraph"])
        decision = json.loads(r["decision_table"] or "[]")
        if decision:
            out.append("")
            out.append("| Factor | Reading | Favors | Weight |")
            out.append("| --- | --- | --- | --- |")
            for d in decision:
                out.append(
                    f"| {d['factor']} | {d['reading']} | {d['favors']} | {d['weight']} |"
                )
        factors = json.loads(r["key_factors"] or "[]")
        if factors:
            out.append("")
            out.append("_Key factors: " + "; ".join(factors) + "_")
        if r["id"] in mortems:
            out += _post_mortem_md(mortems[r["id"]])
        out += _tables_md(_pack_tables(r))
        gaps = json.loads(r["data_gaps"] or "[]")
        if gaps:
            out.append("")
            out.append(f"_Data gaps: {len(gaps)} — " + "; ".join(gaps[:3]) + "_")
        out.append("")

    rec = track.record(conn, season=season)
    if rec["overall"].get("plays"):
        o = rec["overall"]
        out += [
            "---",
            "",
            "## Season to date",
            "",
            f"- Record **{o['record']}**, {o['units']:+.2f} units, ROI {o['roi']}",
            f"- Average CLV **{o['avg_clv']}** pts, positive on {o['clv_positive_pct']} of plays",
            "",
        ]
    return "\n".join(out)


def render_html(conn, season: int, week: int) -> str:
    rows = _slate_rows(conn, season, week)
    mortems = postmortem.load(conn, season, week=week)
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>Edgelord {season} W{week}</title><style>{CSS}</style>",
        f"<h1>Edgelord — {season} Week {week}</h1>",
        f"<p class='sub'>Generated {datetime.now():%Y-%m-%d %H:%M}</p>",
    ]
    if not rows:
        parts.append("<p>No predictions stored for this slate.</p>")
        return "\n".join(parts)

    for r in rows:
        cls = r["pick_type"]
        parts.append("<div class='game'>")
        parts.append(
            f"<div class='matchup'>{r['away_team']} at {r['home_team']}</div>"
            f"<div class='meta'>{r['weekday']} {r['gameday']} "
            f"{r['gametime'] or ''} ET · {r['stadium']}</div>"
            f"<span class='pick {cls}'>{_describe_pick(r)}</span>"
            f"<span class='conf'>confidence {r['confidence']} · projected "
            f"{r['projected_margin']:+.1f} / {r['projected_total']:.1f}</span>"
        )
        parts.append(f"<p class='analysis'>{r['paragraph']}</p>")
        decision = json.loads(r["decision_table"] or "[]")
        if decision:
            body = "".join(
                "<tr><th>{}</th><td>{}</td><td>{}</td><td class='w-{}'>{}</td></tr>".format(
                    html.escape(str(d["factor"])),
                    html.escape(str(d["reading"])),
                    html.escape(str(d["favors"])),
                    html.escape(str(d["weight"])),
                    html.escape(str(d["weight"])),
                )
                for d in decision
            )
            parts.append(
                "<table class='decision'><thead><tr><th>Factor</th><th>Reading</th>"
                "<th>Favors</th><th>Weight</th></tr></thead>"
                f"<tbody>{body}</tbody></table>"
            )
        factors = json.loads(r["key_factors"] or "[]")
        if factors:
            parts.append(f"<div class='factors'>{' · '.join(factors)}</div>")
        if r["id"] in mortems:
            parts.append(_post_mortem_html(mortems[r["id"]]))
        tables = _pack_tables(r)
        if tables:
            parts.append(_tables_html(tables))
        gaps = json.loads(r["data_gaps"] or "[]")
        if gaps:
            parts.append(f"<div class='gaps'>{len(gaps)} data gap(s): {gaps[0]}</div>")
        parts.append("</div>")

    rec = track.record(conn, season=season)
    if rec["overall"].get("plays"):
        o = rec["overall"]
        parts.append("<h2>Season to date</h2><table>")
        for label, val in (
            ("Record", o["record"]), ("Units", f"{o['units']:+.2f}"),
            ("ROI", o["roi"]), ("Avg CLV", o["avg_clv"]),
            ("CLV positive", o["clv_positive_pct"]),
        ):
            parts.append(f"<tr><th>{label}</th><td>{val}</td></tr>")
        parts.append("</table>")
    return "\n".join(parts)


def write(conn, season: int, week: int) -> tuple:
    config.ensure_dirs()
    stem = config.REPORT_DIR / f"{season}_week{week:02d}"
    md, html = stem.with_suffix(".md"), stem.with_suffix(".html")
    md.write_text(render_markdown(conn, season, week), encoding="utf-8")
    html.write_text(render_html(conn, season, week), encoding="utf-8")
    return md, html
