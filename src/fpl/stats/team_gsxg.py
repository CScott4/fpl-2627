"""Team-level xG/xGC 'factor' stats by home/away and gamestate.

Ported from `TeamGSxGCalc.py` (the shrinkage/outlier-handling version -
of the old repo's three near-duplicates, this is the one actually wired
into the pipeline; `TeamGSxGCalc - Copy.py` and `_NoTimeWeighting.py`
were earlier/simpler variants and aren't carried forward).

For each team/home-or-away/gamestate bucket, computes an xG and xGC
"factor": the ratio of that bucket's recency-weighted xG-per-minute to
the league-wide average for the same bucket (so 1.0 = league average).
Buckets with under 90 weighted minutes are shrunk toward 1.0 to avoid
wild factors from small samples. Newly promoted teams (see
`fpl.config.PROMOTED_TEAMS`) have little/no history, so their factors are
instead a weighted blend with the average of last season's relegated
teams (`fpl.config.RELEGATED_TEAMS`) - the idea being a promoted team is
probably similar in strength to one that just went down.

`understat_shots` doesn't store a per-shot date (unlike the old Mongo
documents, which duplicated it from the parent fixture) - recency here
is computed by joining shots to `understat_fixtures.date` instead.

Writes to the `gsxg` and `gsxg_avg` tables via `fpl.db.replace_table`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from fpl.config import (
    CURRENT_SEASON_TEAMS,
    PROMOTED_TEAMS,
    RECENCY_DECAY_RATE,
    RELEGATED_TEAMS,
    STATS_LOOKBACK_DAYS,
)
from fpl.db import read_table, replace_table

H_A_STATES = ["h", "a"]
GAMESTATES = ["Winning", "Draw", "Losing"]


def _factor_table(shots_df: pd.DataFrame, team_col: str, gamestate_col: str, metric: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate `shots_df` into a per-(team, h_a, gamestate) xG-per-minute factor.

    `team_col`/`gamestate_col` select which side of each shot to group by
    (action_team for xG scored, opp_team for xG conceded); `metric` ('xg'
    or 'xgc') only controls the output column names. Returns (factors,
    league_avg_per_bucket).
    """
    grouped = shots_df.pivot_table(
        values=["mins_passed_weighted", "xg_weighted", "weight"],
        index=[team_col, "h_a", gamestate_col],
        aggfunc="sum",
    )
    grouped[f"{metric}_min"] = grouped["xg_weighted"] / grouped["mins_passed_weighted"]
    grouped = grouped.rename_axis(index={team_col: "team", gamestate_col: "gamestate"}).reset_index()

    # League-wide average per bucket, itself weighted so no single team's
    # small sample skews it.
    grouped[f"{metric}_min_weighted"] = grouped[f"{metric}_min"] * grouped["weight"]
    avg = grouped.pivot_table(index=["h_a", "gamestate"], values=[f"{metric}_min_weighted", "weight"], aggfunc="sum")
    avg[f"avg_{metric}_min"] = avg[f"{metric}_min_weighted"] / avg["weight"]
    avg = avg.reset_index()[["h_a", "gamestate", f"avg_{metric}_min"]]

    grouped = grouped.merge(avg, on=["h_a", "gamestate"])
    grouped[f"{metric}_factor"] = grouped[f"{metric}_min"] / grouped[f"avg_{metric}_min"]

    # Shrink toward 1.0 (league average) when a bucket has under 90 weighted minutes.
    thin_sample = grouped["mins_passed_weighted"] < 90
    thin_minutes = grouped.loc[thin_sample, "mins_passed_weighted"]
    grouped.loc[thin_sample, f"{metric}_factor"] = (
        grouped.loc[thin_sample, f"{metric}_factor"] * thin_minutes + 1.0 * (90 - thin_minutes)
    ) / 90

    return grouped[["team", "h_a", "gamestate", "mins_passed_weighted", "weight", f"{metric}_factor"]], avg


def calculate_team_gsxg() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (gsxg, gsxg_avg) dataframes ready for fpl.db.replace_table."""
    shots_df = read_table("understat_shots")
    fixtures_df = read_table("understat_fixtures")
    fixtures_df["date"] = pd.to_datetime(fixtures_df["date"])

    lookback_start = datetime.now() - timedelta(days=STATS_LOOKBACK_DAYS)
    fixtures_df = fixtures_df[fixtures_df["date"] >= lookback_start]

    shots_df = shots_df.merge(fixtures_df[["match_id", "date"]], on="match_id")
    shots_df["days_ago"] = (datetime.now() - shots_df["date"]).dt.days
    shots_df["weight"] = np.exp(-RECENCY_DECAY_RATE * shots_df["days_ago"])
    shots_df["mins_passed_weighted"] = shots_df["mins_passed"] * shots_df["weight"]
    shots_df["xg_weighted"] = shots_df["xg"] * shots_df["weight"]

    gsxg, avg_xg = _factor_table(shots_df, "action_team", "action_team_gamestate", "xg")
    gsxgc, avg_xgc = _factor_table(shots_df, "opp_team", "opp_team_gamestate", "xgc")

    gsxg_avg = avg_xg.merge(avg_xgc, on=["h_a", "gamestate"])

    gsxg = gsxg.merge(gsxgc, on=["team", "h_a", "gamestate"], suffixes=("_x", "_y"))
    gsxg = gsxg.set_index(["team", "h_a", "gamestate"]).sort_index()

    # Ensure every team/h_a/gamestate combo exists, even with zero shot history
    # (relevant for newly promoted teams before their factors are blended in below).
    index = pd.MultiIndex.from_product(
        [CURRENT_SEASON_TEAMS + RELEGATED_TEAMS, H_A_STATES, GAMESTATES], names=["team", "h_a", "gamestate"]
    )
    complete = pd.DataFrame(index=index).reset_index()
    gsxg = complete.merge(gsxg.reset_index(), on=["team", "h_a", "gamestate"], how="left").fillna(0)
    gsxg = gsxg.set_index(["team", "h_a", "gamestate"])

    ## Promoted teams: blend with the average of last season's relegated teams ##
    rel_teams = [team for team in RELEGATED_TEAMS if team in gsxg.index.get_level_values("team")]
    if rel_teams:
        rel_gsxg = gsxg.loc[rel_teams].copy()
        rel_gsxg["xg_factor_weighted"] = rel_gsxg["xg_factor"] * rel_gsxg["weight_x"]
        rel_gsxg["xgc_factor_weighted"] = rel_gsxg["xgc_factor"] * rel_gsxg["weight_y"]

        rel_avg_gsxg = rel_gsxg.pivot_table(
            index=["h_a", "gamestate"],
            values=["xg_factor_weighted", "xgc_factor_weighted", "weight_x", "weight_y"],
            aggfunc="sum",
        )
        rel_avg_gsxg["avg_xg_factor"] = rel_avg_gsxg["xg_factor_weighted"] / rel_avg_gsxg["weight_x"]
        rel_avg_gsxg["avg_xgc_factor"] = rel_avg_gsxg["xgc_factor_weighted"] / rel_avg_gsxg["weight_y"]

        for team in PROMOTED_TEAMS:
            for h_a in H_A_STATES:
                for gamestate in GAMESTATES:
                    stats = gsxg.loc[(team, h_a, gamestate)]
                    rel_avg = rel_avg_gsxg.loc[(h_a, gamestate)]

                    rel_weight_x_per_team = rel_avg["weight_x"] / len(rel_teams)
                    rel_weight_y_per_team = rel_avg["weight_y"] / len(rel_teams)

                    xg_factor = (
                        stats["xg_factor"] * stats["weight_x"] + rel_avg["avg_xg_factor"] * rel_weight_x_per_team
                    ) / (stats["weight_x"] + rel_weight_x_per_team)
                    xgc_factor = (
                        stats["xgc_factor"] * stats["weight_y"] + rel_avg["avg_xgc_factor"] * rel_weight_y_per_team
                    ) / (stats["weight_y"] + rel_weight_y_per_team)

                    gsxg.at[(team, h_a, gamestate), "xg_factor"] = xg_factor
                    gsxg.at[(team, h_a, gamestate), "xgc_factor"] = xgc_factor

    gsxg = gsxg.reset_index()
    gsxg = gsxg[gsxg["team"].isin(CURRENT_SEASON_TEAMS)][["team", "h_a", "gamestate", "xg_factor", "xgc_factor"]]
    gsxg_avg = gsxg_avg[["h_a", "gamestate", "avg_xg_min", "avg_xgc_min"]]

    return gsxg, gsxg_avg


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    gsxg, gsxg_avg = calculate_team_gsxg()
    replace_table(gsxg, "gsxg")
    replace_table(gsxg_avg, "gsxg_avg")
    print(f"Recalculated GSxG factors for {len(gsxg) // (len(H_A_STATES) * len(GAMESTATES))} teams")


if __name__ == "__main__":
    run()
