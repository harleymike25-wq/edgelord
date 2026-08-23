"""Paths, secrets and season/week resolution."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORT_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "edgelord.db"

load_dotenv(ROOT / ".env")

MODEL = os.getenv("EDGELORD_MODEL", "claude-opus-4-8")
ODDS_MONTHLY_BUDGET = int(os.getenv("EDGELORD_ODDS_MONTHLY_BUDGET", "500"))

# Effort controls thinking depth and total token spend. On Fable 5 the lower
# settings still perform very well -- often above the top settings of earlier
# models -- so medium is a genuine quality-neutral saving here, not a downgrade.
PREDICT_EFFORT = os.getenv("EDGELORD_EFFORT", "medium")

# Hard ceiling on model spend per calendar month, in USD. Checked before every
# call; the run stops rather than silently running up a bill.
MONTHLY_BUDGET_USD = float(os.getenv("EDGELORD_MONTHLY_BUDGET_USD", "25"))

# Fable 5 safety classifiers can decline a request outright. Without a fallback
# the call simply fails; with one the API re-serves it on this model inside the
# same request, billed at the fallback's cheaper rates.
FALLBACK_MODEL = os.getenv("EDGELORD_FALLBACK_MODEL", "claude-opus-4-8")

# USD per million tokens, (input, output). Used only for local spend
# accounting -- the authoritative number is always the Anthropic console.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Models where thinking is always on and the request surface differs.
ALWAYS_THINKING_MODELS = {"claude-fable-5", "claude-mythos-5"}


def price_of(model: str) -> tuple[float, float]:
    """Per-million-token (input, output) price, defaulting to Opus-tier."""
    for known, price in MODEL_PRICING.items():
        if model.startswith(known):
            return price
    return MODEL_PRICING["claude-opus-4-8"]


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = price_of(model)
    return (input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out

# Seasons we keep a full historical feature base for.
BACKFILL_SEASONS = [2024, 2025]

# nflverse marks these as the roof types with no weather exposure.
INDOOR_ROOFS = {"dome", "closed"}


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def anthropic_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return key


def odds_key() -> str:
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return key


def current_season(today: date | None = None) -> int:
    """NFL seasons are labelled by their starting year and run into February.

    Anything before March belongs to the previous year's season.
    """
    today = today or date.today()
    return today.year - 1 if today.month < 3 else today.year


def season_bounds(season: int) -> tuple[date, date]:
    """Rough window used only to bucket dates into a season, not for scheduling."""
    return date(season, 8, 1), date(season + 1, 3, 1)


def week_of(gameday: date, season_opener: date) -> int:
    """Week number given the season's first game date (Thursday of Week 1)."""
    # Weeks roll over on Tuesday, so shift the opener back to its Tuesday.
    tuesday = season_opener - timedelta(days=(season_opener.weekday() - 1) % 7)
    return max(1, ((gameday - tuesday).days // 7) + 1)


def parse_gameday(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
