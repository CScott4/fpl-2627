"""Team-level xG/xGC 'factor' stats by home/away and gamestate.

The old repo had three near-duplicate versions of this calculation
(`TeamGSxGCalc - Copy.py`, `TeamGSxGCalc.py`, `TeamGSxGCalc_NoTimeWeighting.py`)
— only the first was actually wired into the pipeline notebook, but the
other two are more sophisticated (weighted-average factors, shrinkage
toward 1.0 for teams with <90 weighted minutes in a bucket). Before
porting, decide which approach to keep — recommend starting from
`TeamGSxGCalc.py` (has the outlier shrinkage) rather than the simpler
"- Copy" version that happened to be live, and dropping the other two.

Writes to the `gsxg` and `gsxg_avg` tables via `fpl.db.replace_table`.

TODO:
- Port the chosen script's shot-weighting, pivot, and factor-calculation
  logic (recency weighting: see `fpl.config.RECENCY_DECAY_RATE`).
- Port the promoted/relegated-team handling (promoted teams inherit a
  weighted blend of last season's relegated teams' factors) — the
  current/relegated/promoted team lists should move to `fpl.config`
  rather than being hardcoded here, since they change every season.
"""
from __future__ import annotations

import pandas as pd


def calculate_team_gsxg() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (gsxg, gsxg_avg) dataframes ready for fpl.db.replace_table."""
    raise NotImplementedError("Port from TeamGSxGCalc.py")


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    calculate_team_gsxg()


if __name__ == "__main__":
    run()
