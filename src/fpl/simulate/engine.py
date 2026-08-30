"""Minute-by-minute Monte Carlo simulation of upcoming fixtures.

Ported from the simulation cells in the old `FPL_24-25.ipynb` (`sim_match`,
`sim_gameweek`, `run_simulation`, `select_starting_lineup`,
`generate_subs`), cleaned up:

- The notebook version threaded ~15 `total_*_time` profiling accumulators
  through every function signature purely for ad-hoc timing - dropped
  entirely here.
- The manual per-player start/app-probability overrides (a large block of
  hardcoded `.loc[...]` assignments for specific player names) are not
  carried forward - per the README, those should move to an editable
  CSV/YAML rather than being hardcoded in Python, and that hasn't been
  built yet.
- `player_id_to_index` + a separate id array is dropped: the player pool
  DataFrame's own row position is used as the index directly.
- Points are computed per-simulation via `fpl.simulate.scoring.calc_fantasy_points`
  instead of an inlined copy of the rules (the two floor-division terms -
  saves and goals conceded - make points non-linear in the underlying
  stats, so they must be computed before averaging across simulations,
  not after).

Enhancement over the original: `assists_per_goal` was a single league-wide
ratio (FPL's total assists / total goals_scored across every player).
Here it's computed per team instead (`_team_assists_per_goal`), since
teams plausibly differ in how often their goals are credited with a
fantasy assist, and we have the data to check.
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd
import requests

from fpl.config import FPL_BOOTSTRAP_URL, FPL_FIXTURES_URL
from fpl.db import read_table
from fpl.simulate.scoring import calc_fantasy_points

STATS = ["minutes", "goals", "assists", "clean_sheet", "saves", "goals_conceded", "yellow_cards", "red_cards", "defcons", "points"]
_STAT_IDX = {stat: i for i, stat in enumerate(STATS)}


def _normalise(values: np.ndarray) -> np.ndarray:
    """Normalise to a probability distribution; spread evenly if everything's zero."""
    probabilities = np.asarray(values, dtype=float)
    if len(probabilities) == 0:
        return probabilities
    total = probabilities.sum()
    return probabilities / total if total > 0 else np.full(len(probabilities), 1.0 / len(probabilities))


def _load_player_pool() -> pd.DataFrame:
    """Merge live FPL data with Understat-derived rates into one per-player table.

    Players with no Understat history yet (new signings, promoted teams)
    get filled with sensible league-average defaults rather than being
    dropped, mirroring the old notebook's "Data prep" cell.
    """
    bootstrap = requests.get(FPL_BOOTSTRAP_URL, timeout=30).json()

    teams_fpl = pd.DataFrame(bootstrap["teams"])[["id", "name"]].rename(columns={"id": "team_id", "name": "team"})
    positions = pd.DataFrame(bootstrap["element_types"])[["id", "singular_name_short"]].rename(
        columns={"id": "element_type", "singular_name_short": "position"}
    )

    players = pd.DataFrame(bootstrap["elements"]).rename(columns={"team": "team_id"})
    players["player"] = players["first_name"] + " " + players["second_name"]
    players = players.merge(teams_fpl, on="team_id").merge(positions, on="element_type")
    players["now_cost"] = players["now_cost"] / 10
    players["assists"] = pd.to_numeric(players["assists"])
    players["goals_scored"] = pd.to_numeric(players["goals_scored"])
    players["saves_per_90"] = pd.to_numeric(players["saves_per_90"])
    players["chance_of_playing_next_round"] = players["chance_of_playing_next_round"].fillna(100.0)
    players['defcons_per_90'] = pd.to_numeric(players['defensive_contribution']) / pd.to_numeric(players['minutes']).replace(0, 1) * 90

    player_reference = read_table("player_reference")[["fpl_code", "us_id"]]
    understat_stats = read_table("understat_player_stats").add_prefix("us_")
    understat_stats = understat_stats.merge(player_reference, left_on="us_player_id", right_on="us_id")

    pool = players.merge(understat_stats, left_on="code", right_on="fpl_code", how="left")

    pool["us_start_prob"] = pool["us_start_prob"].fillna(0.01)
    pool["us_app_prob"] = pool["us_app_prob"].fillna(0.01)
    pool["us_time_avg_start"] = pool["us_time_avg_start"].fillna(max(pool["us_time_avg_start"].mean(), 45.0))
    pool["us_time_avg_start"] = pool["us_time_avg_start"].clip(lower=45.0)
    pool["us_time_avg_sub"] = pool["us_time_avg_sub"].fillna(pool["us_time_avg_sub"].mean())
    pool["us_yellows_p90"] = pool["us_yellows_p90"].fillna(max(pool["us_yellows_p90"].mean(), 0.01))
    pool["us_reds_p90"] = pool["us_reds_p90"].fillna(max(pool["us_reds_p90"].mean(), 0.01))
    pool["us_pct_team_xg"] = pool["us_pct_team_xg"].fillna(1.0)
    pool["us_pct_team_xa"] = pool["us_pct_team_xa"].fillna(1.0)

    pool["app_prob"] = (pool["us_app_prob"] * (pool["chance_of_playing_next_round"] / 100)).fillna(0.0)
    pool["app_prob"] = pool["app_prob"].clip(0.01, 0.99)
    pool["start_prob"] = (pool["us_start_prob"] * pool["app_prob"]).fillna(0.0).clip(0.01, 0.99)
    pool["yellows_per_min"] = pool["us_yellows_p90"] / 90
    pool["reds_per_min"] = pool["us_reds_p90"] / 90

    return pool.reset_index(drop=True)


def _team_assists_per_goal(pool: pd.DataFrame) -> dict[str, float]:
    """Per-team ratio of FPL-credited assists to goals, with a league-wide fallback."""
    by_team = pool.groupby("team")[["assists", "goals_scored"]].sum()
    league_ratio = pool["assists"].sum() / pool["goals_scored"].sum()
    return {
        team: (row["assists"] / row["goals_scored"] if row["goals_scored"] > 0 else league_ratio)
        for team, row in by_team.iterrows()
    }


def _next_fixtures(n_gameweeks: int) -> pd.DataFrame:
    """Fixtures for the next `n_gameweeks` unplayed gameweeks, with Understat team names attached."""
    bootstrap = requests.get(FPL_BOOTSTRAP_URL, timeout=30).json()
    events = pd.DataFrame(bootstrap["events"])
    events["deadline_time"] = pd.to_datetime(events["deadline_time"]).dt.tz_localize(None)
    next_ids = events.loc[events["deadline_time"] > datetime.now(), "id"].head(n_gameweeks).tolist()

    fixtures = pd.DataFrame(requests.get(FPL_FIXTURES_URL, timeout=30).json())
    fixtures = fixtures[fixtures["event"].isin(next_ids)]

    teams_ref = read_table("teams_reference")[["fpl_id", "us_name", "fpl_name"]]
    teams_ref["us_name"] = teams_ref["us_name"].fillna(teams_ref["fpl_name"])

    fixtures = fixtures.merge(teams_ref, left_on="team_h", right_on="fpl_id")
    fixtures = fixtures.rename(columns={"us_name": "team_h_us", "fpl_name": "team_h_fpl"})
    fixtures = fixtures.merge(teams_ref, left_on="team_a", right_on="fpl_id")
    fixtures = fixtures.rename(columns={"us_name": "team_a_us", "fpl_name": "team_a_fpl"})
    return fixtures.sort_values("kickoff_time")


def _gamestate_scoring_rates(
    gsxg: pd.DataFrame, gsxg_avg: pd.DataFrame, home_team_us: str, away_team_us: str
) -> dict[str, dict[str, float]]:
    """Per-minute scoring rate for each side, for each gamestate (from the home team's perspective)."""
    home = gsxg[(gsxg["team"] == home_team_us) & (gsxg["h_a"] == "h")].set_index("gamestate")
    away = gsxg[(gsxg["team"] == away_team_us) & (gsxg["h_a"] == "a")].set_index("gamestate")
    avg = gsxg_avg.set_index(["h_a", "gamestate"])["avg_xg_min"]

    return {
        "home_win": {
            "h": avg[("h", "Winning")] * home.loc["Winning", "xg_factor"] * away.loc["Losing", "xgc_factor"],
            "a": avg[("a", "Losing")] * away.loc["Losing", "xg_factor"] * home.loc["Winning", "xgc_factor"],
        },
        "draw": {
            "h": avg[("h", "Draw")] * home.loc["Draw", "xg_factor"] * away.loc["Draw", "xgc_factor"],
            "a": avg[("a", "Draw")] * away.loc["Draw", "xg_factor"] * home.loc["Draw", "xgc_factor"],
        },
        "away_win": {
            "h": avg[("h", "Losing")] * home.loc["Losing", "xg_factor"] * away.loc["Winning", "xgc_factor"],
            "a": avg[("a", "Winning")] * away.loc["Winning", "xg_factor"] * home.loc["Losing", "xgc_factor"],
        },
    }


class _Pool:
    """Numpy-array view of the player pool, for fast indexed access during simulation.

    Row position in `pool` (after `reset_index`) doubles as the player id
    throughout - there's no separate id-to-index mapping to keep in sync.
    """

    def __init__(self, pool: pd.DataFrame) -> None:
        self.team = pool["team"].to_numpy()
        self.position = pool["position"].to_numpy()
        self.start_prob = pool["start_prob"].to_numpy()
        self.app_prob = pool["app_prob"].to_numpy()
        self.start_mins = pool["us_time_avg_start"].to_numpy()
        self.sub_mins = pool["us_time_avg_sub"].to_numpy()
        self.pct_team_xg = pool["us_pct_team_xg"].to_numpy()
        self.pct_team_xa = pool["us_pct_team_xa"].to_numpy()
        self.yellows_per_min = pool["yellows_per_min"].to_numpy()
        self.reds_per_min = pool["reds_per_min"].to_numpy()
        self.saves_per_90 = pool["saves_per_90"].to_numpy()
        self.defcons_per_90 = pool["defcons_per_90"].to_numpy()
        self.n_players = len(pool)
        self.team_to_indices = {team: np.where(self.team == team)[0].tolist() for team in pool["team"].unique()}


def _select_starting_lineup(indices: list[int], pool: _Pool) -> list[int]:
    """One goalkeeper plus 10 outfield players, weighted by start probability."""
    gkp = [i for i in indices if pool.position[i] == "GKP"]
    outfield = [i for i in indices if pool.position[i] != "GKP"]
    gkp_probs = _normalise(pool.start_prob[gkp])
    outfield_probs = _normalise(pool.start_prob[outfield])
    starters = np.random.choice(outfield, size=10, replace=False, p=outfield_probs).tolist()
    starters.append(random.choices(gkp, weights=gkp_probs)[0])
    return starters


def _generate_subs(indices: list[int], starting: list[int], pool: _Pool) -> tuple[list[int], list[float], list[int]]:
    """Pick which starters get subbed off (and when) and who replaces them."""
    # start_times = [np.ceil(np.random.exponential(max(pool.start_mins[i] - 45, 0.0)) + 45) for i in starting]
    start_times = [max(90 - np.random.poisson(max(90 - pool.start_mins[i], 0.0)), 45) for i in starting]
    subs_off, sub_minutes = [], []
    for position in np.argsort(start_times):
        if start_times[position] < 90 and len(subs_off) < 5:
            subs_off.append(starting[position])
            sub_minutes.append(start_times[position])
        else:
            break
    bench = [i for i in indices if i not in starting]
    probabilities = _normalise(pool.app_prob[bench])
    subs_on = np.random.choice(bench, size=len(subs_off), replace=False, p=probabilities).tolist()
    subs_on.sort(key=lambda i: pool.sub_mins[i], reverse=True)
    return subs_off, sub_minutes, subs_on


def _set_gamestate(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home_win"
    if away_score > home_score:
        return "away_win"
    return "draw"


def _simulate_match(
    scoring_rates: dict[str, dict[str, float]],
    home_team: str,
    away_team: str,
    pool: _Pool,
    assists_per_goal: dict[str, float],
) -> tuple[np.ndarray, int, int]:
    """Simulate one match minute-by-minute. Returns (per-player stats, home_score, away_score)."""
    stats = np.zeros((pool.n_players, len(STATS)))
    home_idx, away_idx = pool.team_to_indices[home_team], pool.team_to_indices[away_team]

    home_on = _select_starting_lineup(home_idx, pool)
    away_on = _select_starting_lineup(away_idx, pool)
    home_active, away_active = home_on.copy(), away_on.copy()
    home_off, home_sub_mins, home_sub_on = _generate_subs(home_idx, home_on, pool)
    away_off, away_sub_mins, away_sub_on = _generate_subs(away_idx, away_on, pool)

    for i in home_on + away_on:
        stats[i, _STAT_IDX["minutes"]] = 90
    for off, on, minute in zip(home_off, home_sub_on, home_sub_mins):
        stats[off, _STAT_IDX["minutes"]] = minute
        stats[on, _STAT_IDX["minutes"]] = 90 - minute
    for off, on, minute in zip(away_off, away_sub_on, away_sub_mins):
        stats[off, _STAT_IDX["minutes"]] = minute
        stats[on, _STAT_IDX["minutes"]] = 90 - minute

    home_score = away_score = 0
    gamestate = _set_gamestate(home_score, away_score)
    goal_rolls = np.random.rand(90, 2)
    assist_rolls = np.random.rand(90, 2)

    for minute in range(90):
        home_goal = away_goal = False
        first_side = random.randint(0, 1)
        for side in (first_side, 1 - first_side):
            team_key = "h" if side == 0 else "a"
            if goal_rolls[minute, side] < scoring_rates[gamestate][team_key]:
                if side == 0:
                    home_score += 1
                    home_goal = True
                else:
                    away_score += 1
                    away_goal = True
                gamestate = _set_gamestate(home_score, away_score)

        if away_goal:
            for i in home_active:
                stats[i, _STAT_IDX["goals_conceded"]] += 1
        if home_goal:
            for i in away_active:
                stats[i, _STAT_IDX["goals_conceded"]] += 1

        for side, (goal, active, team) in enumerate(
            [(home_goal, home_active, home_team), (away_goal, away_active, away_team)]
        ):
            if not goal:
                continue
            scorer_weights = _normalise(pool.pct_team_xg[active])
            scorer = random.choices(active, weights=scorer_weights)[0]
            stats[scorer, _STAT_IDX["goals"]] += 1
            if assist_rolls[minute, side] < assists_per_goal[team]:
                possible_assisters = [i for i in active if i != scorer]
                assist_weights = _normalise(pool.pct_team_xa[possible_assisters])
                assister = random.choices(possible_assisters, weights=assist_weights)[0]
                stats[assister, _STAT_IDX["assists"]] += 1

        if home_sub_mins and minute >= home_sub_mins[0]:
            off, on = home_off.pop(0), home_sub_on.pop(0)
            home_sub_mins.pop(0)
            home_active.remove(off)
            home_active.append(on)
        if away_sub_mins and minute >= away_sub_mins[0]:
            off, on = away_off.pop(0), away_sub_on.pop(0)
            away_sub_mins.pop(0)
            away_active.remove(off)
            away_active.append(on)

    for i in home_idx + away_idx:
        minutes = stats[i, _STAT_IDX["minutes"]]
        if random.random() < 1 - (1 - pool.yellows_per_min[i]) ** minutes:
            stats[i, _STAT_IDX["yellow_cards"]] = 1
        if random.random() < 1 - (1 - pool.reds_per_min[i]) ** minutes:
            stats[i, _STAT_IDX["red_cards"]] = 1
        if minutes >= 60 and stats[i, _STAT_IDX["goals_conceded"]] == 0:
            stats[i, _STAT_IDX["clean_sheet"]] = 1
        if pool.saves_per_90[i] > 0 and minutes > 0:
            stats[i, _STAT_IDX["saves"]] = np.random.poisson(pool.saves_per_90[i] * minutes / 90)
        if pool.defcons_per_90[i] > 0 and minutes > 0:
            stats[i, _STAT_IDX["defcons"]] = np.random.poisson(pool.defcons_per_90[i] * minutes / 90)

        stats[i, _STAT_IDX["points"]] = calc_fantasy_points(
            position=pool.position[i],
            minutes=int(minutes),
            goals=int(stats[i, _STAT_IDX["goals"]]),
            assists=int(stats[i, _STAT_IDX["assists"]]),
            clean_sheet=bool(stats[i, _STAT_IDX["clean_sheet"]]),
            goals_conceded=int(stats[i, _STAT_IDX["goals_conceded"]]),
            saves=int(stats[i, _STAT_IDX["saves"]]),
            yellow_cards=int(stats[i, _STAT_IDX["yellow_cards"]]),
            red_cards=int(stats[i, _STAT_IDX["red_cards"]]),
            defcons=int(stats[i, _STAT_IDX["defcons"]]),
        )

    return stats, home_score, away_score


def _simulate_gameweek(
    gameweek_id: int,
    fixtures: pd.DataFrame,
    pool_df: pd.DataFrame,
    gsxg: pd.DataFrame,
    gsxg_avg: pd.DataFrame,
    assists_per_goal: dict[str, float],
    n_simulations: int,
) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[tuple[int, int], float]]]:
    pool = _Pool(pool_df)
    aggregated = np.zeros((pool.n_players, len(STATS)))
    scorelines = {}
    for _, fixture in fixtures.iterrows():
        home_team, away_team = fixture["team_h_fpl"], fixture["team_a_fpl"]
        rates = _gamestate_scoring_rates(gsxg, gsxg_avg, fixture["team_h_us"], fixture["team_a_us"])
        print(f"Simulating {home_team} vs. {away_team}")
        score_counts = Counter()
        for _ in range(n_simulations):
            match_stats, home_score, away_score = _simulate_match(rates, home_team, away_team, pool, assists_per_goal)
            aggregated += match_stats
            score_counts[(home_score, away_score)] += 1
        scorelines[(home_team, away_team)] = {
            score: count / n_simulations for score, count in score_counts.items()
        }
    stats_df = pd.DataFrame(aggregated / n_simulations, index=pool_df["player"], columns=STATS)
    return stats_df, scorelines


def simulate_gameweek(
    gameweek_id: int, fixtures: pd.DataFrame, n_simulations: int = 10_000
) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[tuple[int, int], float]]]:
    """Return (per-player average stats/points, scoreline probabilities) for one gameweek.

    `fixtures` must already be filtered to just this gameweek's matches,
    with team_h_fpl/team_a_fpl/team_h_us/team_a_us columns (see
    `_next_fixtures`). Scoreline probabilities are keyed by (home_team, away_team).
    """
    pool_df = _load_player_pool()
    return _simulate_gameweek(
        gameweek_id,
        fixtures,
        pool_df,
        read_table("gsxg"),
        read_table("gsxg_avg"),
        _team_assists_per_goal(pool_df),
        n_simulations,
    )


def run(n_simulations: int = 10_000, n_gameweeks: int = 5) -> None:
    """Entry point used by scripts/run_gameweek.py."""
    results = simulate_next_gameweeks(n_simulations=n_simulations, n_gameweeks=n_gameweeks)
    for gameweek_id, (gw_stats, _) in results.items():
        print(f"\nGameweek {gameweek_id} top predicted points:")
        print(gw_stats.sort_values("points", ascending=False).head(10)[["points"]])


def simulate_next_gameweeks(
    n_simulations: int = 10_000, n_gameweeks: int = 5
) -> dict[int, tuple[pd.DataFrame, dict[tuple[str, str], dict[tuple[int, int], float]]]]:
    """Simulate the next `n_gameweeks` unplayed gameweeks.

    Returns `{gameweek_id: (per-player average stats/points, scoreline probabilities)}`,
    for further analysis (e.g. in `notebooks/weekly_analysis.ipynb`) rather
    than just printing a top-10 like `run()` does.
    """
    pool_df = _load_player_pool()
    assists_per_goal = _team_assists_per_goal(pool_df)
    gsxg = read_table("gsxg")
    gsxg_avg = read_table("gsxg_avg")
    fixtures = _next_fixtures(n_gameweeks)

    results = {}
    for gameweek_id in fixtures["event"].unique():
        print(f"\nSimulating Gameweek {gameweek_id}")
        gw_fixtures = fixtures[fixtures["event"] == gameweek_id]
        results[gameweek_id] = _simulate_gameweek(
            gameweek_id, gw_fixtures, pool_df, gsxg, gsxg_avg, assists_per_goal, n_simulations
        )
    return results


if __name__ == "__main__":
    run()
