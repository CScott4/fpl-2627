"""MILP-based squad selection.

Replaces the old random-squad-generation + greedy single-transfer search
(`generate_random_squad_new`, `generate_best_squad`,
`single_transfer_improvements` in `FPL_24-25.ipynb`) with a Mixed Integer
Linear Program solved via PuLP, which is both faster and provably optimal
for a fixed set of expected-points estimates.

Standard FPL squad constraints to encode:
- Exactly 15 players: 2 GKP, 5 DEF, 5 MID, 3 FWD.
- Total cost <= budget (100.0 by default).
- At most 3 players from any one club.
- (Optional, for the transfer-planning variant) penalise/limit changes
  from an existing squad, and lock in specific players as "guarantees" —
  the old notebook's `generate_squad_with_players` use case.

Objective: maximise a weighted sum of expected points across the next N
gameweeks (see the `multipliers` weighting in the old notebook, which
favours more imminent gameweeks), for a chosen starting XI + captain
subject to formation constraints (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD, 11
total) — this second layer (squad -> best XI) is `fpl.squad.evaluate`.

TODO: implement `select_squad` with PuLP (pulp.LpProblem, binary decision
variables per player, constraints as above); implement transfer-planning
as a variant that also penalises/cap the number of players changed
relative to a given current squad.
"""
from __future__ import annotations

import pandas as pd

BUDGET = 100.0
SQUAD_SIZE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3


def select_squad(
    player_pool: pd.DataFrame,
    expected_points_col: str,
    budget: float = BUDGET,
    guarantees: list[str] | None = None,
) -> pd.DataFrame:
    """Return the optimal 15-player squad from `player_pool`.

    `player_pool` must have columns: player id/name, position, team,
    cost, and `expected_points_col`. `guarantees` is an optional list of
    player ids that must be included (for "given I'm keeping these N
    players, what's the best squad" queries).
    """
    raise NotImplementedError("Implement with PuLP — see module docstring")


def run() -> None:
    """Entry point used by scripts/run_gameweek.py."""
    raise NotImplementedError("Wire up select_squad against simulation output")


if __name__ == "__main__":
    run()
