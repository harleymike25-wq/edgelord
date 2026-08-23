"""Generate a SYNTHETIC snapshot so the dashboard can be built and reviewed
before any real predictions exist.

The paragraphs here are placeholder text, not model output. The snapshot is
flagged `synthetic: true` and the dashboard renders a warning banner when it
sees that flag, so nobody mistakes this for a real read on a game.

Predictions are inserted inside a transaction that is rolled back, so the
database is left exactly as it was found.

    .venv\\Scripts\\python.exe scripts\\seed_dev_snapshot.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edgelord import db, sync, track  # noqa: E402

SEASON = 2025
random.seed(17)

PLACEHOLDER = (
    "PLACEHOLDER TEXT -- not model output. This paragraph exists so the "
    "dashboard layout can be reviewed before real predictions are generated. "
    "In the live system this slot holds 120-200 words of analysis leading with "
    "the conclusion, then the two or three factors that actually drove it, "
    "naming specific numbers from the feature pack."
)

FACTORS = [
    ["pythagorean delta +0.21", "5-1 in one-score games", "turnover margin +16"],
    ["opponent FG% 94.9 unsustainable", "rest edge +3 days", "line crossed 3"],
    ["defensive EPA -0.09 opponent-adjusted", "explosive rate 15.0%", "dome"],
    ["short week on the road", "pressure rate allowed 13.8%", "red zone TD% 55.6"],
    ["PROE -4.1 in neutral", "pace 36.0 sec/play", "divisional rematch"],
]


def main() -> int:
    with db.session() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) n FROM predictions WHERE run_label != 'backtest'"
        ).fetchone()["n"]
        if existing:
            print(
                f"refusing to seed: {existing} real predictions already exist.\n"
                "Run `edgelord sync` instead to snapshot the real data.",
                file=sys.stderr,
            )
            return 1

        games = conn.execute(
            "SELECT game_id, home_team, away_team, spread_line, total_line, "
            "home_score, away_score FROM games "
            "WHERE season = ? AND game_type = 'REG' AND week <= 6 "
            "ORDER BY week, gameday, gametime",
            (SEASON,),
        ).fetchall()

        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("BEGIN")
        for g in games:
            roll = random.random()
            if roll < 0.18:
                pick_type, side, line = "pass", "none", None
            elif roll < 0.62:
                pick_type = "spread"
                home_side = random.random() < 0.5
                side = g["home_team"] if home_side else g["away_team"]
                line = g["spread_line"] if home_side else -g["spread_line"]
            else:
                pick_type = "total"
                side = random.choice(["over", "under"])
                line = g["total_line"]

            conn.execute(
                "INSERT INTO predictions (game_id, model, created_at, run_label, "
                "pick_type, pick_side, line_at_pick, price_at_pick, confidence, "
                "projected_margin, projected_total, paragraph, key_factors) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    g["game_id"], "SYNTHETIC-PLACEHOLDER", now, "sunday",
                    pick_type, side, line, -110,
                    random.randint(50, 72) if pick_type != "pass" else random.randint(35, 49),
                    round(random.uniform(-10, 10), 1),
                    round(random.uniform(38, 52), 1),
                    PLACEHOLDER,
                    json.dumps(random.choice(FACTORS)),
                ),
            )

        track.grade(conn)
        payload = sync.build_payload(conn, SEASON)
        payload["synthetic"] = True
        path = sync.write_snapshot(payload)

        conn.execute("ROLLBACK")

    print(f"wrote SYNTHETIC snapshot -> {path}")
    print(f"  {len(payload['games'])} games, "
          f"{sum(1 for g in payload['games'] if g['prediction'])} placeholder predictions")
    print("  database left unchanged (transaction rolled back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
