"""Per-player rate stats derived from Understat rosters.

Ports `PlayerStatsCalc.py`: aggregates `understat_rosters` (filtered to
the last `PLAYER_STATS_LOOKBACK_DAYS`, see fpl.config) into per-90 rates
(xG, xA, cards), start vs. sub minute splits, and appearance/start
probabilities, handling players who've changed teams mid-window.

Writes the result to the `understat_player_stats` table via
`fpl.db.replace_table` (fully recalculated each run, like the original).

TODO: port the pivot-table logic from PlayerStatsCalc.py essentially
as-is — it's mostly pandas transforms and translates over directly, just
swap `db.Understat_Rosters.find()` for `fpl.db.read_table("understat_rosters")`
and the final `insert_many` for `fpl.db.replace_table(...)`.
"""
from __future__ import annotations

import pandas as pd


def calculate_player_stats() -> pd.DataFrame:
    raise NotImplementedError("Port from PlayerStatsCalc.py")


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    calculate_player_stats()


if __name__ == "__main__":
    run()
