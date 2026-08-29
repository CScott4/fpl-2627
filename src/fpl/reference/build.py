"""One-off, season-start build of the FPL <-> Understat reference tables.

Ports `RebuildFPLReferences.py`. Run this once at the start of a season
against the archived vaastav/Fantasy-Premier-League CSVs, to fuzzy-match
Understat player/team names onto that season's starting FPL ids. Ongoing
in-season updates go through `fpl.reference.refresh` instead, which reuses
`build_player_reference` below against the live FPL bootstrap API.

TODO: port `normalize`, `name_score`, `load_manual_matches`,
`build_team_reference`, `build_player_reference`, and `main`, replacing
the CSV/Mongo I/O at the edges with `fpl.db.replace_table` and reading
`ManualPlayerMatches.csv` (kept as a plain CSV in the repo root or
data/, not a database table, since it's meant to be hand-edited).
"""
from __future__ import annotations

import pandas as pd


def build_team_reference(teams_fpl: pd.DataFrame, understat_fixtures: pd.DataFrame) -> pd.DataFrame:
    raise NotImplementedError("Port from RebuildFPLReferences.py")


def build_player_reference(
    players_fpl: pd.DataFrame,
    rosters: pd.DataFrame,
    team_reference: pd.DataFrame,
    manual_matches: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (matched_reference, unmatched_rows)."""
    raise NotImplementedError("Port from RebuildFPLReferences.py")


def run() -> None:
    """Entry point for the one-off season-start rebuild."""
    raise NotImplementedError("Port `main()` from RebuildFPLReferences.py")


if __name__ == "__main__":
    run()
