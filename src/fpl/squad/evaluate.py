"""Given a 15-player squad, pick the best starting XI + captain per gameweek.

Ports `evaluate_squad` from `FPL_24-25.ipynb`: for each gameweek, choose a
valid formation (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 total) that
maximises expected points, captain the highest scorer (captain's points
count double), and sum across gameweeks using the same "weight nearer
gameweeks more heavily" scheme as the old `multipliers` list.

TODO: port the per-gameweek lineup selection logic; consider replacing
the "sort and take top N per position, then fill remaining slots" greedy
approach with a small MILP here too, since the search space is tiny (15
players) and an exact solve is essentially free.
"""
from __future__ import annotations

import pandas as pd


def evaluate_squad(squad: pd.DataFrame, points_columns: list[str], weights: list[float]) -> tuple[float, dict]:
    """Return (total_weighted_points, per_gameweek_lineups)."""
    raise NotImplementedError("Port from FPL_24-25.ipynb `evaluate_squad`")
