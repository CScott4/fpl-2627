"""Central place for environment-derived configuration.

Nothing else in the package should call `os.getenv` directly — import
constants from here instead, so there's one place to see what's
configurable and one place to change defaults.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

# --- FPL ---------------------------------------------------------------
FPL_ENTRY_ID: str | None = os.getenv("FPL_ENTRY_ID") or None
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
FPL_ENTRY_URL_TEMPLATE = "https://fantasy.premierleague.com/api/entry/{entry_id}/"
FPL_PICKS_URL_TEMPLATE = (
    "https://fantasy.premierleague.com/api/entry/{entry_id}/event/{event_id}/picks/"
)

# --- Understat -----------------------------------------------------------
UNDERSTAT_SEASON: int = int(os.getenv("UNDERSTAT_SEASON", "2026"))
UNDERSTAT_LEAGUE = "EPL"
UNDERSTAT_BASE_URL = "https://understat.com"

# --- Database ------------------------------------------------------------
_db_path_env = os.getenv("FPL_DB_PATH")
DB_PATH = Path(_db_path_env) if _db_path_env else REPO_ROOT / "data" / "fpl.db"

# --- Stats windows ---------------------------------------------------------
# How much history to use when computing rolling stats, and the recency
# decay applied within that window (see fpl.stats).
STATS_LOOKBACK_DAYS = 365
PLAYER_STATS_LOOKBACK_DAYS = 180
RECENCY_DECAY_RATE = 0.01  # weight = exp(-RECENCY_DECAY_RATE * days_ago)

# --- League team lists (Understat naming) ---------------------------------
# Update at the start of each season when promotion/relegation changes.
# Newly promoted teams have little/no Understat history, so fpl.stats.team_gsxg
# blends their factors with the average of the just-relegated teams instead.
PROMOTED_TEAMS = ["Coventry", "Hull", "Ipswich"]
RELEGATED_TEAMS = ["Burnley", "West Ham", "Wolverhampton Wanderers"]
CURRENT_SEASON_TEAMS = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea",
    "Crystal Palace", "Everton", "Fulham", "Leeds", "Liverpool", "Manchester City",
    "Manchester United", "Newcastle United", "Nottingham Forest", "Sunderland",
    "Tottenham",
] + PROMOTED_TEAMS
