"""Scrape new fixtures/shots/rosters from Understat into SQLite.

Ported from the old `ScrapeUnderstatNew.py` (the version actually called
from the pipeline — `FixingUnderstatScrape.py` and
`Full_Understat_Scrape.ipynb` were earlier, superseded attempts and were
not carried forward).

Behaviour preserved from the original:
- Pull the season's fixture list from Understat's `getLeagueData` endpoint,
  keep only results (`isResult`), and skip match_ids already in the DB
  (`fpl.db.existing_ids`) instead of always re-scraping everything.
- For each new match, hit `getMatchData/{match_id}` for shots + rosters.
- Compute running score and gamestate (Winning/Draw/Losing) per shot from
  the chronological shot list, for both the acting team and the opponent.

Mongo's `insert_many` calls are replaced with `fpl.db.append_rows`, and
column names are lower_snake_case to match schema.sql (xG -> xg, etc.).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import requests

from fpl.config import UNDERSTAT_BASE_URL, UNDERSTAT_LEAGUE, UNDERSTAT_SEASON
from fpl.db import append_rows, existing_ids

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

_SHOT_COLUMNS = [
    "match_id", "minute", "result", "xg", "h_a", "h_team", "a_team", "player",
    "player_id", "h_score", "a_score", "mins_passed", "h_gamestate", "a_gamestate",
    "action_team", "action_team_gamestate", "opp_team", "opp_team_gamestate",
    "shot_num", "shotontarget_num", "goal", "competition",
]

_ROSTER_COLUMNS = [
    "match_id", "player_id", "player", "team_id", "position", "time",
    "goals", "own_goals", "assists", "shots", "xg", "xa", "xg_chain",
    "xg_buildup", "yellow_card", "red_card",
]


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


def _get_json(session: requests.Session, path: str) -> dict:
    response = session.get(f"{UNDERSTAT_BASE_URL}/{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def _fixture_record(fixture: dict) -> dict:
    # Understat's JSON encodes every id/number as a string, so cast explicitly
    # rather than relying on SQLite's type affinity to coerce it on insert.
    return {
        "match_id": int(fixture["id"]),
        "date": fixture["datetime"],
        "home_team": fixture["h"]["title"],
        "away_team": fixture["a"]["title"],
        "h_id": int(fixture["h"]["id"]),
        "a_id": int(fixture["a"]["id"]),
        "home_goals": int(fixture["goals"]["h"]),
        "away_goals": int(fixture["goals"]["a"]),
        "home_xg": float(fixture["xG"]["h"]),
        "away_xg": float(fixture["xG"]["a"]),
    }


def _process_shots(shots: list[dict], match_id: int) -> pd.DataFrame:
    """Compute running score/gamestate columns for one match's chronological shots."""
    shots_df = pd.DataFrame(shots)
    if shots_df.empty:
        return shots_df

    shots_df["match_id"] = match_id
    shots_df["minute"] = pd.to_numeric(shots_df["minute"])
    shots_df["xg"] = pd.to_numeric(shots_df["xG"])
    shots_df["competition"] = UNDERSTAT_LEAGUE
    shots_df["shot_num"] = 1
    shots_df["shotontarget_num"] = np.where(
        shots_df["result"].isin(["SavedShot", "Goal"]), 1, 0
    )
    shots_df["goal"] = np.where(shots_df["result"] == "Goal", 1, 0)
    shots_df = shots_df.sort_values("minute").reset_index(drop=True)

    # Running score per shot, resetting if a new match's shots start mid-list.
    home_goals = 0
    away_goals = 0
    previous_h_minute = 0
    previous_a_minute = 0
    for index, row in shots_df.iterrows():
        # if row["minute"] < previous_minute:
        #     home_goals = 0
        #     away_goals = 0
        shots_df.at[index, "h_score"] = home_goals
        shots_df.at[index, "a_score"] = away_goals
        if row["h_a"] == "h":
            shots_df.at[index, "mins_passed"] = row["minute"] - previous_h_minute
            previous_h_minute = row["minute"]
        else:
            shots_df.at[index, "mins_passed"] = row["minute"] - previous_a_minute
            previous_a_minute = row["minute"]

        if row["h_a"] == "h":
            if row["result"] == "Goal":
                home_goals += 1
            elif row["result"] == "OwnGoal":
                away_goals += 1
        else:
            if row["result"] == "Goal":
                away_goals += 1
            elif row["result"] == "OwnGoal":
                home_goals += 1

    # If the minute of either team's last shot is less than 90, add another row with xg = 0 and shot_num = 0 with the remaining minutes
    if previous_h_minute < 90:
        shots_df = pd.concat([
            shots_df,
            pd.DataFrame([{
                "match_id": match_id,
                "minute": np.max([previous_a_minute, 90]),
                "xg": 0,
                "shot_num": 0,
                "shotontarget_num": 0,
                "goal": 0,
                "h_a": "h",
                "h_score": home_goals,
                "a_score": away_goals,
                "mins_passed": 90 - previous_h_minute,
                "h_team": shots_df["h_team"].iloc[0],
                "a_team": shots_df["a_team"].iloc[0],
                "result": "NoShots"
            }])
        ], ignore_index=True)

    if previous_a_minute < 90:
        shots_df = pd.concat([
            shots_df,
            pd.DataFrame([{
                "match_id": match_id,
                "minute": np.max([previous_h_minute, 90]),
                "xg": 0,
                "shot_num": 0,
                "shotontarget_num": 0,
                "goal": 0,
                "h_a": "a",
                "h_score": home_goals,
                "a_score": away_goals,
                "mins_passed": 90 - previous_a_minute,
                "h_team": shots_df["h_team"].iloc[0],
                "a_team": shots_df["a_team"].iloc[0],
                "result": "NoShots"
            }])
        ], ignore_index=True)
    

    shots_df["h_gamestate"] = np.select(
        [shots_df["h_score"] > shots_df["a_score"], shots_df["h_score"] < shots_df["a_score"]],
        ["Winning", "Losing"],
        default="Draw",
    )
    shots_df["a_gamestate"] = np.select(
        [shots_df["a_score"] > shots_df["h_score"], shots_df["a_score"] < shots_df["h_score"]],
        ["Winning", "Losing"],
        default="Draw",
    )
    shots_df["action_team"] = np.where(shots_df["h_a"] == "h", shots_df["h_team"], shots_df["a_team"])
    shots_df["action_team_gamestate"] = np.where(
        shots_df["h_a"] == "h", shots_df["h_gamestate"], shots_df["a_gamestate"]
    )
    shots_df["opp_team"] = np.where(shots_df["h_a"] == "h", shots_df["a_team"], shots_df["h_team"])
    shots_df["opp_team_gamestate"] = np.where(
        shots_df["h_a"] == "h", shots_df["a_gamestate"], shots_df["h_gamestate"]
    )

    return shots_df[_SHOT_COLUMNS]


def _process_rosters(rosters: list[dict], match_id: int) -> pd.DataFrame:
    rosters_df = pd.DataFrame(rosters)
    rosters_df["match_id"] = match_id
    rosters_df = rosters_df.rename(
        columns={"xG": "xg", "xA": "xa", "xGChain": "xg_chain", "xGBuildup": "xg_buildup"}
    )
    numeric_cols = [
        "player_id", "team_id", "time", "goals", "own_goals", "assists",
        "shots", "xg", "xa", "xg_chain", "xg_buildup", "yellow_card", "red_card",
    ]
    for col in numeric_cols:
        rosters_df[col] = pd.to_numeric(rosters_df[col])

    return rosters_df[_ROSTER_COLUMNS]


def _process_match(session: requests.Session, match_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = _get_json(session, f"getMatchData/{match_id}")
    shots = [shot for side in data["shots"].values() for shot in side]
    rosters = [player for side in data["rosters"].values() for player in side.values()]
    return _process_shots(shots, match_id), _process_rosters(rosters, match_id)


def scrape_new_fixtures(season: int = UNDERSTAT_SEASON) -> pd.DataFrame:
    """Fetch and store any Understat fixtures not already in the database.

    `season` is Understat's convention of the year a season starts in (e.g.
    2025 for 2025/26) — pass it explicitly to backfill older seasons; the
    rolling stats windows (see fpl.config) need at least the previous
    season's data early in a new one.

    Returns the newly inserted fixtures as a DataFrame (empty if there was
    nothing new).
    """
    session = _session()
    league_data = _get_json(session, f"getLeagueData/{UNDERSTAT_LEAGUE}/{season}")
    fixtures = [fixture for fixture in league_data["dates"] if fixture["isResult"]]

    scraped_ids = existing_ids("understat_fixtures", "match_id")
    # Understat's fixture ids are strings; scraped_ids comes back as ints from
    # SQLite, so cast before comparing or every fixture looks "new" every time.
    new_fixtures = [fixture for fixture in fixtures if int(fixture["id"]) not in scraped_ids]

    if not new_fixtures:
        print(f"No new Understat data for {UNDERSTAT_LEAGUE} {season}/{season + 1}")
        return pd.DataFrame()

    all_shots = []
    all_rosters = []
    for number, fixture in enumerate(new_fixtures, start=1):
        print(f"Scraping {number}/{len(new_fixtures)}: {fixture['h']['title']} - {fixture['a']['title']}")
        shots_df, rosters_df = _process_match(session, fixture["id"])
        all_shots.append(shots_df)
        all_rosters.append(rosters_df)

    fixtures_df = pd.DataFrame([_fixture_record(fixture) for fixture in new_fixtures])
    append_rows(fixtures_df, "understat_fixtures")
    append_rows(pd.concat(all_shots, ignore_index=True), "understat_shots")
    append_rows(pd.concat(all_rosters, ignore_index=True), "understat_rosters")

    print(f"Inserted {len(fixtures_df)} fixtures")
    return fixtures_df


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    scrape_new_fixtures()


if __name__ == "__main__":
    try:
        run()
    except (requests.RequestException, KeyError, ValueError) as error:
        print(f"Understat scrape failed: {error}", file=sys.stderr)
        sys.exit(1)
