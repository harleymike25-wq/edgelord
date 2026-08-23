"""Slate report rendering."""

from __future__ import annotations

import json
from datetime import datetime

from . import config, track

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
.conf { color: #666; font-size: .85rem; margin-left: .5rem; }
p.analysis { margin: .6rem 0 .4rem; }
.factors { color: #666; font-size: .85rem; }
table { border-collapse: collapse; margin: .8rem 0; font-size: .9rem; }
th, td { text-align: left; padding: .3rem .9rem .3rem 0; }
th { color: #666; font-weight: 500; }
.gaps { color: #999; font-size: .8rem; font-style: italic; }
"""


def _slate_rows(conn, season: int, week: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.*, g.home_team, g.away_team, g.gameday, g.gametime, g.weekday,
               g.stadium, g.spread_line, g.total_line, f.data_gaps
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


def render_markdown(conn, season: int, week: int) -> str:
    rows = _slate_rows(conn, season, week)
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
        factors = json.loads(r["key_factors"] or "[]")
        if factors:
            out.append("")
            out.append("_Key factors: " + "; ".join(factors) + "_")
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
        factors = json.loads(r["key_factors"] or "[]")
        if factors:
            parts.append(f"<div class='factors'>{' · '.join(factors)}</div>")
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
