"""Minute-by-minute Monte Carlo simulation of upcoming fixtures.

Ports the simulation cells from `FPL_24-25.ipynb` (`sim_match`,
`sim_gameweek`, `run_simulation`, plus the lineup/substitution helpers
`select_starting_lineup` and `generate_subs`).

Performance note: the original loops per-minute x per-simulation x
per-match in pure Python. Before considering a rewrite in another
language, profile and try:
  1. Vectorising across simulations with numpy (run all N sims for a
     match as array ops instead of a Python loop around a Python loop).
  2. A numba @njit on the hot inner loop.
Only fall back to Rust/Cython if those don't get simulation time to an
acceptable place — see README phasing notes.

TODO: port team/player lineup selection, goal-scorer/assist allocation
(weighted by `pct_team_xg` / `pct_team_xa` from understat_player_stats),
cards, and substitutions, calling `fpl.simulate.scoring.calc_fantasy_points`
for the final points conversion instead of inlining the rules here.
"""
from __future__ import annotations

import pandas as pd


def simulate_gameweek(gameweek_id: int, fixtures: pd.DataFrame, n_simulations: int = 10_000) -> pd.DataFrame:
    """Return average per-player stats/points across n_simulations for one gameweek."""
    raise NotImplementedError("Port from FPL_24-25.ipynb simulation cells")


def run(n_simulations: int = 10_000, n_gameweeks: int = 5) -> None:
    """Entry point used by scripts/run_gameweek.py."""
    raise NotImplementedError("Port from FPL_24-25.ipynb `run_simulation`")


if __name__ == "__main__":
    run()
