"""Which predictor made a pick.

The method changed about eight times in the first ten weeks of 2026, and the
record ran them all together, so no number on the site described one system.
Every pick is now stamped with the version that made it and the record can be
read one version at a time.

A version is a fingerprint of the recipe: the prompt, the reply schema, the
checklist, every threshold that turns a number into a side or a tier, the
correction settings and the computed baseline's parameters. Change any of them
and the fingerprint changes. `VERSIONS` names the fingerprints that were
changed on purpose, and a test fails when the current one is not in it -- so
the recipe cannot drift by accident. To change the predictor deliberately:
make the change, run the tests, add the new fingerprint here with a name and a
line saying what changed, and note it in VERIFIED.md.

Not part of the fingerprint, by design:
- The learned factor multipliers. They move every week from graded games; the
  rule that fits them is in the recipe, their current values are stored on
  each pick.
- The model id and the effort setting. Both come from this machine's
  settings, not the code, so they are written into the stamp beside the
  fingerprint: a switch of either shows as a different stamp.
- The feature pack's contents, which code cannot fingerprint cheaply. Bump
  `PACK_REVISION` by hand when what the model is shown changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

# Bump when the pack the model sees gains, loses or redefines a field.
PACK_REVISION = 1

# Fingerprint -> (name, what changed). Newest last.
VERSIONS: dict[str, tuple[str, str]] = {
    "ecbf3794c5": (
        "blind-v7",
        "Blind factor sum with learned corrections; totals at a 7-point gap; "
        "early-line calls; quarterback reruns need two sources (2026-11-16).",
    ),
    "5baf21ec24": (
        "blind-v8",
        "blind-v7, with team strength and home field counting half of their "
        "edge against the line; other factors in full (2026-11-25).",
    ),
    "31b432a177": (
        "blind-v9",
        "blind-v8, with each team's current situation written before the "
        "factors are scored and a hypothetical game script after (2026-11-25).",
    ),
}

# Picks made before stamping began, named by week from VERIFIED.md. Coarse on
# purpose: some changes landed mid-week, and a rerun used that day's method.
RECONSTRUCTED = "reconstructed"
HISTORY_2026: tuple[tuple[int, int, str], ...] = (
    (1, 1, "v1 margin from scratch"),
    (2, 2, "v2 anchored to the line"),
    (3, 5, "v3 computed tiers"),
    (6, 6, "v4 luck stats removed"),
    (7, 7, "v5 blind"),
    (8, 10, "v6 blind with corrections"),
)


def recipe() -> dict:
    """Everything that decides a blind pick, apart from the model and the data."""
    from . import calibration, early, shadow
    from .models import elo, qb

    return {
        "predictor": "blind",
        "pack_revision": PACK_REVISION,
        "system_prompt": shadow.SYSTEM_PROMPT,
        "response_schema": shadow.RESPONSE_SCHEMA,
        "checklist": shadow.CHECKLIST,
        "sigma": shadow.SIGMA,
        "tiers": {
            "best_bet_edge": shadow.BEST_BET_EDGE,
            "best_bet_baseline_edge": shadow.BEST_BET_BASELINE_EDGE,
            "lean_edge": shadow.LEAN_EDGE,
            "total_pick_edge": shadow.TOTAL_PICK_EDGE,
        },
        "market_priced": {
            "factors": shadow.MARKET_PRICED,
            "weight": shadow.MARKET_PRICED_WEIGHT,
        },
        "corrections": {
            "prior_sd": calibration.PRIOR_SD,
            "floor": calibration.FLOOR,
            "ceiling": calibration.CEILING,
        },
        "baseline": {"elo": asdict(elo.DEFAULT), "qb": asdict(qb.DEFAULT)},
        "timing": {"keys": early.KEYS, "min_hours": early.MIN_HOURS},
    }


def fingerprint() -> str:
    blob = json.dumps(recipe(), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]


def name() -> str:
    """The current recipe's name, or 'unregistered' if it was changed without one."""
    return VERSIONS.get(fingerprint(), ("unregistered", ""))[0]


def stamp(model: str | None = None, effort: str | None = None) -> str:
    """What is stored on a pick: name, fingerprint, then the model and effort used."""
    parts = [f"{name()}+{fingerprint()}", model, effort]
    return " ".join(p for p in parts if p)


def short(stamp_value: str | None) -> str:
    """The name alone, for grouping a record: 'blind-v7+ab12cd34ef model' -> 'blind-v7'."""
    if not stamp_value:
        return "unstamped"
    return stamp_value.split("+")[0].strip()


def backfill(conn, season: int = 2026) -> int:
    """Name the picks made before stamping began. Returns rows labelled.

    Only fills blanks, and marks every one as reconstructed.
    """
    if season != 2026:
        return 0
    n = 0
    for first, last, label in HISTORY_2026:
        cur = conn.execute(
            "UPDATE predictions SET predictor_version = ? "
            "WHERE predictor_version IS NULL AND run_label != 'backtest' "
            "AND game_id IN (SELECT game_id FROM games WHERE season = ? "
            "                AND week BETWEEN ? AND ?)",
            (f"{label}+{RECONSTRUCTED}", season, first, last),
        )
        n += cur.rowcount
    return n
