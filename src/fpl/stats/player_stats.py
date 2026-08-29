"""Per-player rate stats derived from Understat rosters.

Ported from `PlayerStatsCalc.py`: aggregates `understat_rosters` (filtered
to the last `PLAYER_STATS_LOOKBACK_DAYS` days, see fpl.config) into per-90
rates (xG, xA, cards), start vs. sub minute splits, and appearance/start
probabilities, handling players who've changed teams mid-window.

Writes the result to `understat_player_stats` via `fpl.db.replace_table`
(fully recalculated each run, like the original).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from fpl.config import PLAYER_STATS_LOOKBACK_DAYS, UNDERSTAT_SEASON
from fpl.db import read_table, replace_table

SEASON_START = f"{UNDERSTAT_SEASON}-08-01"


def calculate_player_stats() -> pd.DataFrame:
    rosters_df = read_table("understat_rosters")
    fixtures_df = read_table("understat_fixtures")

    lookback_start = datetime.now() - timedelta(days=PLAYER_STATS_LOOKBACK_DAYS)
    fixtures_df["date"] = pd.to_datetime(fixtures_df["date"])
    fixtures_df = fixtures_df[fixtures_df["date"] >= lookback_start]
    this_season_df = fixtures_df[fixtures_df["date"] >= SEASON_START]

    match_ids = fixtures_df["match_id"].tolist()
    match_ids_this_season = set(this_season_df["match_id"])

    rosters_df = rosters_df[rosters_df["match_id"].isin(match_ids)].copy()

    rosters_df["time_avg"] = rosters_df["time"]  # so minutes can be summed and averaged
    rosters_df["app"] = 1
    rosters_df["start"] = rosters_df["position"].apply(lambda x: 1 if x != "Sub" else 0)
    rosters_df["sixty"] = rosters_df["time"].apply(lambda x: 1 if x >= 60 else 0)
    rosters_df["started"] = rosters_df["start"]
    rosters_df["this_season"] = rosters_df["match_id"].isin(match_ids_this_season).astype(int)

    # Split each player into games started vs. sub appearances, to get avg mins in each situation.
    player_stats = rosters_df.pivot_table(
        index=["player_id", "player", "team_id", "started"],
        values=[
            "app", "start", "sixty", "goals", "own_goals", "assists", "shots", "xg", "xa",
            "time", "time_avg", "yellow_card", "red_card", "xg_chain", "xg_buildup", "this_season",
        ],
        aggfunc={
            "app": "sum", "start": "sum", "sixty": "sum", "goals": "sum", "own_goals": "sum",
            "assists": "sum", "shots": "sum", "xg": "sum", "xa": "sum", "time": "sum", "time_avg": "mean",
            "yellow_card": "sum", "red_card": "sum", "xg_chain": "sum", "xg_buildup": "sum", "this_season": "sum",
        },
    ).reset_index()

    player_stats["time_avg_sub"] = player_stats["time_avg"] * (1 - player_stats["started"])
    player_stats["time_avg_start"] = player_stats["time_avg"] * player_stats["started"]

    # Combine each player's started/sub rows back into a single row.
    player_stats_grouped = player_stats.pivot_table(
        index=["player_id", "player", "team_id"], aggfunc="sum"
    ).reset_index()

    # Mark players who are (probably) new this season, for a different appearance-prob calc below.
    player_stats_grouped["new_player"] = (
        player_stats_grouped["this_season"] == player_stats_grouped["app"]
    ).astype(int)

    ## Team stats ##
    team_matches = rosters_df.pivot_table(
        index=["team_id", "match_id"],
        values=["goals", "own_goals", "assists", "shots", "xg", "xa", "yellow_card", "red_card"],
        aggfunc="sum",
    ).reset_index()
    team_matches["games"] = 1
    team_matches["games_this_season"] = team_matches["match_id"].isin(match_ids_this_season).astype(int)

    team_stats = team_matches.pivot_table(
        index="team_id",
        values=[
            "games", "games_this_season", "goals", "own_goals", "assists", "shots", "xg", "xa",
            "yellow_card", "red_card",
        ],
        aggfunc="sum",
    ).reset_index()
    team_stats["team_id"] = pd.to_numeric(team_stats["team_id"])
    team_stats = team_stats.rename(
        columns={"games": "team_games", "games_this_season": "team_games_this_season", "xa": "team_xa", "xg": "team_xg"}
    )
    team_stats_slim = team_stats[["team_id", "team_games", "team_games_this_season", "team_xa", "team_xg"]]

    player_stats_grouped["team_id"] = pd.to_numeric(player_stats_grouped["team_id"])
    extended_stats = player_stats_grouped.merge(team_stats_slim, on="team_id")
    extended_stats = extended_stats[
        [
            "player_id", "player", "team_id", "team_games", "team_games_this_season", "app", "start", "sixty",
            "time_avg_start", "time_avg_sub", "time", "goals", "assists", "own_goals", "xg", "xa",
            "yellow_card", "red_card", "team_xg", "team_xa", "new_player",
        ]
    ]

    # Players who've changed teams mid-window get two rows here; keep only the
    # new_player=1 (current team) window's team stats, discard the old team's.
    duplicated_mask = extended_stats.duplicated(subset=["player_id"], keep=False)
    duplicated_players = extended_stats[duplicated_mask].copy()
    extended_stats.loc[duplicated_mask, "team_id"] = duplicated_players["team_id"] * duplicated_players["new_player"]
    extended_stats.loc[duplicated_mask, "team_games"] = (
        duplicated_players["team_games"] * (1 - duplicated_players["new_player"])
    )
    extended_stats.loc[duplicated_mask, "team_games_this_season"] = (
        duplicated_players["team_games_this_season"] * duplicated_players["new_player"]
    )
    extended_stats.loc[duplicated_mask, "time_avg_start"] = (
        duplicated_players["time_avg_start"] * duplicated_players["new_player"]
    )
    extended_stats.loc[duplicated_mask, "time_avg_sub"] = (
        duplicated_players["time_avg_sub"] * duplicated_players["new_player"]
    )
    extended_stats.loc[duplicated_mask, "new_player"] = 0
    extended_stats = extended_stats.pivot_table(index=["player_id", "player"], aggfunc="sum").reset_index()

    # Per-90 rates; np.maximum guards against inflated rates from tiny minute totals.
    minutes_p90 = np.maximum(extended_stats["time"], 450) / 90
    extended_stats["xg_p90"] = extended_stats["xg"] / minutes_p90
    extended_stats["xa_p90"] = extended_stats["xa"] / minutes_p90
    extended_stats["reds_p90"] = extended_stats["red_card"] / minutes_p90
    extended_stats["yellows_p90"] = extended_stats["yellow_card"] / minutes_p90

    extended_stats["team_xg_p90"] = extended_stats["team_xg"] / extended_stats["team_games"]
    extended_stats["team_xa_p90"] = extended_stats["team_xa"] / extended_stats["team_games"]

    extended_stats["app_prob"] = extended_stats.apply(
        lambda row: row["app"] / max(row["team_games"], 1)
        if row["new_player"] == 0
        else row["app"] / max(row["team_games_this_season"], 1),
        axis=1,
    )
    extended_stats["start_prob"] = extended_stats["start"] / extended_stats["app"]
    extended_stats["sixty_prob"] = extended_stats["sixty"] / extended_stats["start"]

    extended_stats["pct_team_xg"] = (extended_stats["xg_p90"] / extended_stats["team_xg_p90"]) * 100
    extended_stats["pct_team_xa"] = (extended_stats["xa_p90"] / extended_stats["team_xa_p90"]) * 100

    return extended_stats[
        [
            "player_id", "player", "team_id", "app", "start", "sixty", "time_avg_start", "time_avg_sub",
            "time", "goals", "assists", "own_goals", "xg", "xa", "yellow_card", "red_card", "xg_p90",
            "xa_p90", "yellows_p90", "reds_p90", "team_xg_p90", "team_xa_p90", "app_prob", "start_prob",
            "sixty_prob", "pct_team_xg", "pct_team_xa", "new_player",
        ]
    ]


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    player_stats = calculate_player_stats()
    replace_table(player_stats, "understat_player_stats")
    print(f"Recalculated stats for {len(player_stats)} players")


if __name__ == "__main__":
    run()
