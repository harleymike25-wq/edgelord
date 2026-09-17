"""Push a read-only mirror of the database to Firestore.

SQLite remains the source of truth: the scheduled jobs write there, backtests
read there, and nothing in the bot depends on this module succeeding. If
Firebase credentials are absent or the network is down, the sync no-ops and the
bot carries on.

The mirror is deliberately denormalised -- one document per game carrying the
game, its current prediction and its result -- so the dashboard renders a week
from a single query rather than joining on the client.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import config, evidence, track

# Written for the dashboard to consume in development, when there is no
# Firebase project to point at yet. The Next.js app is the repository root and
# the Python project lives in bot/, so this reaches one level up into public/.
SNAPSHOT_DIR = config.ROOT.parent / "public" / "data"

COLLECTION = "games"
META_COLLECTION = "meta"


# No Firebase project at all -- the documented development mode, and the one
# reason for not publishing that is not a mistake.
UNSET = (
    "no credentials. Set FIREBASE_CREDENTIALS to a service account json, in "
    "bot/.env rather than in one shell, or only the shell that exported it "
    "can publish"
)


def _credentials() -> tuple[Path | None, str | None]:
    """The key file, or the reason there is not one.

    Every failure here used to read as "no credentials", which sends you to
    check an environment variable that is usually already correct. The reason
    a sync did not publish is the whole diagnosis, so it travels with it.
    """
    raw = os.getenv("FIREBASE_CREDENTIALS")
    if not raw or not raw.strip():
        return None, UNSET
    # A path copied out of Windows Explorer arrives wrapped in quotes, and the
    # quoted string is not a file that exists. Nothing strips them on the way
    # in, so the result is indistinguishable from the variable being unset.
    path = Path(raw.strip().strip('"').strip("'"))
    if not path.is_absolute():
        path = config.ROOT / path
    if not path.exists():
        return None, f"FIREBASE_CREDENTIALS points at {path}, which does not exist"
    return path, None


def _credentials_path() -> Path | None:
    return _credentials()[0]


def available() -> bool:
    return _credentials_path() is not None


def _client() -> tuple[object | None, str | None]:
    """Lazily build a Firestore client, or say why there is not one."""
    creds, reason = _credentials()
    if creds is None:
        return None, reason
    try:
        import firebase_admin
        from firebase_admin import credentials as fb_credentials
        from firebase_admin import firestore
    except ImportError:
        # Deliberately distinct from a credential problem: the key is fine and
        # the optional extra is missing. Reporting this as "no credentials"
        # sends you to the Firebase console to fix a pip install.
        return None, (
            "firebase-admin is not installed in this venv -- "
            'pip install -e ".[firebase]"'
        )

    if not firebase_admin._apps:
        firebase_admin.initialize_app(fb_credentials.Certificate(str(creds)))
    return firestore.client(), None


def _game_documents(conn, season: int, week: int | None) -> list[dict]:
    """One document per game: schedule, current prediction, result if graded."""
    sql = """
        SELECT g.game_id, g.season, g.week, g.game_type, g.gameday, g.weekday,
               g.gametime, g.home_team, g.away_team, g.home_score, g.away_score,
               g.spread_line, g.total_line, g.stadium, g.roof, g.referee,
               g.div_game, g.home_coach, g.away_coach,
               p.id AS prediction_id, p.model, p.created_at, p.run_label,
               p.pick_type, p.pick_side, p.conviction, p.line_at_pick,
               p.price_at_pick, p.confidence, p.projected_margin,
               p.projected_total, p.headline, p.paragraph, p.key_factors,
               p.decision_table,
               f.data_gaps, f.payload,
               r.pick_result, r.profit_units, r.clv_points,
               r.closing_line, r.closing_total,
               pm.verdict, pm.explanation, pm.lesson, pm.miss
        FROM games g
        LEFT JOIN predictions p
               ON p.game_id = g.game_id AND p.superseded_by IS NULL
              AND p.run_label != 'backtest'
        LEFT JOIN features f ON f.id = p.features_id
        LEFT JOIN results r ON r.prediction_id = p.id
        LEFT JOIN post_mortems pm ON pm.prediction_id = p.id
        WHERE g.season = ?
    """
    params: list = [season]
    if week is not None:
        sql += " AND g.week = ?"
        params.append(week)
    sql += " ORDER BY g.week, g.gameday, g.gametime"

    docs = []
    for row in conn.execute(sql, params).fetchall():
        r = dict(row)
        doc = {
            "game_id": r["game_id"],
            "season": r["season"],
            "week": r["week"],
            "game_type": r["game_type"],
            "gameday": r["gameday"],
            "weekday": r["weekday"],
            "gametime_et": r["gametime"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "stadium": r["stadium"],
            "roof": r["roof"],
            "referee": r["referee"],
            "divisional": bool(r["div_game"]),
            "home_coach": r["home_coach"],
            "away_coach": r["away_coach"],
            "closing_spread_home": r["spread_line"],
            "closing_total": r["total_line"],
            "final": (
                {"home": r["home_score"], "away": r["away_score"]}
                if r["home_score"] is not None
                else None
            ),
            "prediction": None,
            "result": None,
        }
        # Lift the inputs the pick was argued from out of the stored feature
        # pack. The full pack is tens of kilobytes of raw inputs, so this is a
        # slice -- but a wide enough one that the page can show every factor
        # that moved the number rather than only the ones the write-up chose to
        # name. Prose cites two departures rhetorically; the table shows all of
        # them, for both teams, which is what you need to check the reasoning.
        if r.get("payload"):
            try:
                pack = json.loads(r["payload"])
                units = (pack.get("matchup") or {}).get("unit_ratings")
                if units:
                    doc["unit_ratings"] = units
                h2h = (pack.get("matchup") or {}).get("head_to_head")
                if h2h and h2h.get("meetings"):
                    doc["head_to_head"] = h2h

                factors: dict = {}
                wx = pack.get("weather")
                if wx:
                    factors["weather"] = wx
                sit = pack.get("situation")
                if sit:
                    factors["situation"] = sit
                for side in ("home", "away"):
                    blk = pack.get(side) or {}
                    picked = {
                        k: blk[k]
                        for k in ("roster_turnover", "prior_season_record", "injuries")
                        if blk.get(k) is not None
                    }
                    if picked:
                        factors[side] = picked
                if factors:
                    doc["factors"] = factors
            except (ValueError, TypeError):
                pass

        if r["prediction_id"] is not None:
            doc["prediction"] = {
                "id": r["prediction_id"],
                "model": r["model"],
                "created_at": r["created_at"],
                "run_label": r["run_label"],
                "pick_type": r["pick_type"],
                "pick_side": r["pick_side"],
                "line_at_pick": r["line_at_pick"],
                "price_at_pick": r["price_at_pick"],
                "confidence": r["confidence"],
                "projected_margin": r["projected_margin"],
                "projected_total": r["projected_total"],
                "conviction": r["conviction"],
                "headline": r["headline"],
                "paragraph": r["paragraph"],
                "key_factors": json.loads(r["key_factors"] or "[]"),
                "decision_table": json.loads(r["decision_table"] or "[]"),
                "data_gaps": json.loads(r["data_gaps"] or "[]"),
            }
        if r["pick_result"] is not None:
            doc["result"] = {
                "pick_result": r["pick_result"],
                "profit_units": r["profit_units"],
                "clv_points": r["clv_points"],
                "closing_line": r["closing_line"],
                "closing_total": r["closing_total"],
            }
        # Losses travel with their explanation. A record that shows the misses
        # but not why they happened is the same missing caveat problem as a win
        # rate with no sample size beside it.
        if r["miss"] is not None:
            try:
                miss = json.loads(r["miss"])
            except (ValueError, TypeError):
                miss = {}
            doc["post_mortem"] = {
                "verdict": r["verdict"],
                "explanation": r["explanation"],
                "lesson": r["lesson"],
                "miss": miss,
            }
        docs.append(doc)
    return docs


def _clv_series(conn, season: int) -> list[dict]:
    """Per-week CLV and units, for the trend chart."""
    rows = conn.execute(
        "SELECT g.week, AVG(r.clv_points) clv, SUM(r.profit_units) units, "
        "COUNT(*) n FROM results r "
        "JOIN predictions p ON p.id = r.prediction_id "
        "JOIN games g ON g.game_id = r.game_id "
        "WHERE g.season = ? AND p.superseded_by IS NULL AND p.pick_type != 'pass' "
        "AND p.run_label != 'backtest' "
        "GROUP BY g.week ORDER BY g.week",
        (season,),
    ).fetchall()
    return [
        {
            "week": r["week"],
            "avg_clv": round(r["clv"], 3) if r["clv"] is not None else None,
            "units": round(r["units"] or 0, 2),
            "plays": r["n"],
        }
        for r in rows
    ]


def build_payload(conn, season: int, *, week: int | None = None) -> dict:
    return {
        "season": season,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "games": _game_documents(conn, season, week),
        "record": track.record(conn, season=season),
        "weekly": _clv_series(conn, season),
        # How much the record itself should be believed -- shipped alongside
        # it so the dashboard can never show a hot streak without the caveat.
        "evidence": evidence.assess(conn, season=season),
        "synthetic": False,
    }


def write_snapshot(payload: dict, *, name: str | None = None) -> Path:
    """Local JSON the dashboard falls back to when Firestore is unconfigured."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / (name or f"season-{payload['season']}.json")
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    index = SNAPSHOT_DIR / "index.json"
    seasons = sorted(
        {int(p.stem.split("-")[1]) for p in SNAPSHOT_DIR.glob("season-*.json")}
    )
    index.write_text(
        json.dumps({"seasons": seasons, "latest": seasons[-1] if seasons else None}, indent=1),
        encoding="utf-8",
    )
    return path


def _live_week(conn, season: int) -> int | None:
    """The week the dashboard opens on, by the same rule as `run_task.ps1`.

    Mirrored even when it holds no picks, because the dashboard lands there by
    default: an unmirrored week 404s, which reads as the season being over
    rather than as a slate nobody has predicted yet.
    """
    row = conn.execute(
        'SELECT week FROM games WHERE season = ? AND gameday >= date("now", "-2 day") '
        "ORDER BY gameday, gametime LIMIT 1",
        (season,),
    ).fetchone()
    return row["week"] if row else None


def push(conn, season: int, *, week: int | None = None, snapshot: bool = True) -> dict:
    """Mirror to Firestore and optionally write the local snapshot."""
    payload = build_payload(conn, season, week=week)
    out = {
        "season": season,
        "games": len(payload["games"]),
        "predictions": sum(1 for g in payload["games"] if g["prediction"]),
        "firestore": "skipped",
        "snapshot": None,
        # Whether the dashboard actually changed. A caller that only reads the
        # prose line has to parse English to find that out.
        "published": False,
        # Whether publishing was even meant to happen. A run with no Firebase
        # project configured is development mode; a run that meant to publish
        # and could not is a fault, and the two must not report the same way.
        "configured": False,
    }

    if snapshot:
        out["snapshot"] = str(write_snapshot(payload))

    client, reason = _client()
    if client is None:
        out["firestore"] = reason
        out["configured"] = reason != UNSET
        return out
    out["configured"] = True

    live = _live_week(conn, season)
    batch = client.batch()
    written = 0
    for doc in payload["games"]:
        # Only mirror games we have something to say about; the full schedule
        # would be thousands of pointless documents. The live week is the
        # exception -- see `_live_week`.
        if (
            doc["prediction"] is None
            and doc["final"] is None
            and doc["week"] != live
        ):
            continue
        batch.set(client.collection(COLLECTION).document(doc["game_id"]), doc)
        written += 1
        if written % 400 == 0:  # Firestore caps a batch at 500 operations.
            batch.commit()
            batch = client.batch()

    batch.set(
        client.collection(META_COLLECTION).document(f"record-{season}"),
        {
            "season": season,
            "generated_at": payload["generated_at"],
            "record": payload["record"],
            "weekly": payload["weekly"],
            # Must travel with the record. Without it the deployed dashboard
            # shows a win rate and no verdict, which is the one combination
            # this project is trying to avoid.
            "evidence": payload["evidence"],
        },
    )
    batch.commit()

    out["firestore"] = f"wrote {written} game docs + record-{season}"
    out["published"] = True
    return out
