"""Given a 15-player squad, pick the best starting XI + captain per gameweek.

Ports `evaluate_squad` from `FPL_24-25.ipynb`: for each gameweek, choose a
valid formation (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 total) that
maximises expected points, captain the highest scorer (captain's points
count double), and sum across gameweeks using the same "weight nearer
gameweeks more heavily" scheme as the old `multipliers` list.

Unlike the old notebook, the formation search here isn't a fixed
GKP+3DEF+2MID+1FWD-then-fill-with-best-4 heuristic — it tries every valid
(def, mid, fwd) split and keeps the best. This is exact (not just a good
heuristic): for a *fixed* split, the optimal XI is simply the top-N
scorers within each position (positions don't compete with each other
for slots once the split is fixed), so trying every valid split and
taking the best is guaranteed to find the true optimum. With only ~9
valid splits to check this is effectively free.
"""
from __future__ import annotations

import pandas as pd

FORMATION_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
FORMATION_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
XI_SIZE = 11


def _best_xi_for_gameweek(squad: pd.DataFrame, points_col: str) -> tuple[float, list, object]:
    """Return (total_points_incl_captain, starting_player_ids, captain_id) for one gameweek.

    `squad` must have a 'position' column (GKP/DEF/MID/FWD) and the given
    points column, indexed by player id/name.
    """
    by_position = {
        pos: squad[squad["position"] == pos].sort_values(points_col, ascending=False)
        for pos in FORMATION_MIN
    }
    gkp = by_position["GKP"].head(1)
    if len(gkp) < 1:
        raise ValueError("Squad has no goalkeeper")

    best_total = None
    best_ids: list = []
    for n_def in range(FORMATION_MIN["DEF"], FORMATION_MAX["DEF"] + 1):
        for n_fwd in range(FORMATION_MIN["FWD"], FORMATION_MAX["FWD"] + 1):
            n_mid = XI_SIZE - 1 - n_def - n_fwd
            if not (FORMATION_MIN["MID"] <= n_mid <= FORMATION_MAX["MID"]):
                continue

            defs = by_position["DEF"].head(n_def)
            mids = by_position["MID"].head(n_mid)
            fwds = by_position["FWD"].head(n_fwd)
            if len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd:
                continue  # squad doesn't have enough players in this position for this split

            starters = pd.concat([gkp, defs, mids, fwds])
            total = starters[points_col].sum()
            if best_total is None or total > best_total:
                best_total = total
                best_ids = starters.index.tolist()

    if not best_ids:
        raise ValueError(
            "No valid formation (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD) fits this squad's position counts"
        )

    starters_df = squad.loc[best_ids]
    captain_id = starters_df[points_col].idxmax()
    total_with_captain = best_total + starters_df.loc[captain_id, points_col]
    return total_with_captain, best_ids, captain_id


def evaluate_squad(squad: pd.DataFrame, points_columns: list[str], weights: list[float]) -> tuple[float, dict]:
    """Return (total_weighted_points, per_gameweek_lineups).

    `squad` is a 15-row DataFrame indexed by player id/name with a
    'position' column (GKP/DEF/MID/FWD) and one expected-points column
    per upcoming gameweek (`points_columns`, e.g. ``['GW 1 points', ...]``,
    matching the simulation output shape in `fpl.simulate.engine`).
    `weights` weights each gameweek's contribution to the total — pass a
    list like the old notebook's `multipliers = [10, 9, 8, 7, 6]` to
    weight nearer gameweeks more heavily; must be the same length as
    `points_columns`.

    `per_gameweek_lineups` is ``{gameweek_number: {'lineup': [...], 'captain': ..., 'gw_points': ...}}``,
    where `gameweek_number` runs 1..len(points_columns) in the order
    `points_columns` was given (it does *not* look at real FPL gameweek
    ids — pair it up with your own gameweek_ids list if you need those).
    """
    if len(points_columns) != len(weights):
        raise ValueError("points_columns and weights must be the same length")
    if squad.shape[0] < XI_SIZE:
        raise ValueError(f"Squad has only {squad.shape[0]} players; need at least {XI_SIZE}")

    total_weighted = 0.0
    lineups: dict = {}
    for week_number, (points_col, weight) in enumerate(zip(points_columns, weights), start=1):
        gw_points, starting_ids, captain_id = _best_xi_for_gameweek(squad, points_col)
        lineups[week_number] = {
            "lineup": starting_ids,
            "captain": captain_id,
            "gw_points": gw_points,
        }
        total_weighted += gw_points * weight

    return total_weighted, lineups
