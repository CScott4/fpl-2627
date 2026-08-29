"""Ongoing (in-season) refresh of the FPL <-> Understat reference tables.

Ported from `RefreshLiveFPLReferences.py`. Re-runs the matching in
`fpl.reference.build.build_player_reference` against the *live* FPL
bootstrap API, so ids stay correct as the season progresses (new
signings, id churn, etc.), reusing the baseline `teams_reference` written
by the season-start `fpl.reference.build.run()`.

Extended beyond the original script: teams promoted since the baseline
season (e.g. Coventry/Hull/Ipswich for 2026/27) have no `us_id` in that
baseline, and `build_player_reference` inner-joins on `us_id` - so without
a fallback, promoted teams' current squads would be silently dropped from
`player_reference` entirely (not even reported as unmatched). We fill
missing `us_id`/`us_name` from this season's own scraped Understat
fixtures instead.
"""
from __future__ import annotations

import pandas as pd
import requests

from fpl.config import FPL_BOOTSTRAP_URL, UNDERSTAT_SEASON
from fpl.db import read_table, replace_table
from fpl.reference.build import (
    UNDERSTAT_TO_FPL,
    UNMATCHED_FILE,
    build_player_reference,
    load_manual_matches,
)


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    response = requests.get(FPL_BOOTSTRAP_URL, timeout=30)
    response.raise_for_status()
    bootstrap = response.json()

    teams_fpl = pd.DataFrame(bootstrap["teams"]).rename(
        columns={"id": "fpl_id", "name": "fpl_name", "short_name": "fpl_short", "code": "fpl_code"}
    )[["fpl_id", "fpl_name", "fpl_short", "fpl_code"]]

    players_fpl = pd.DataFrame(bootstrap["elements"]).rename(
        columns={"id": "fpl_id", "code": "fpl_code", "team": "fpl_team_id"}
    )
    players_fpl["fpl_name"] = players_fpl["first_name"] + " " + players_fpl["second_name"]
    players_fpl = players_fpl.merge(
        teams_fpl[["fpl_id", "fpl_name"]], left_on="fpl_team_id", right_on="fpl_id", suffixes=("", "_team")
    )
    players_fpl["fpl_name_team"] = players_fpl["fpl_name_team"].astype(str)
    players_fpl = players_fpl[["fpl_id", "fpl_code", "fpl_name", "fpl_name_team"]]

    baseline_teams = read_table("teams_reference")
    rosters = read_table("understat_rosters")
    if baseline_teams.empty or rosters.empty:
        raise ValueError("Run fpl.reference.build first to establish a baseline team reference")

    # Fallback for teams missing from the baseline (promoted since then):
    # take their us_id/us_name straight from this season's own Understat data.
    # UNDERSTAT_TO_FPL only knows last season's 20 teams, so newly promoted
    # ones (not in that dict) are matched by unique substring instead, e.g.
    # Understat's "Hull" <-> FPL's "Hull City".
    current_fixtures = read_table("understat_fixtures", where=f"date >= '{UNDERSTAT_SEASON}-06-01'")
    current_teams = pd.concat(
        [
            current_fixtures[["home_team", "h_id"]].rename(columns={"home_team": "us_name", "h_id": "us_id"}),
            current_fixtures[["away_team", "a_id"]].rename(columns={"away_team": "us_name", "a_id": "us_id"}),
        ]
    ).drop_duplicates()
    current_teams["fpl_name"] = current_teams["us_name"].map(UNDERSTAT_TO_FPL)
    unmapped = current_teams["fpl_name"].isna()
    if unmapped.any():
        fpl_names = teams_fpl["fpl_name"].tolist()

        def guess_fpl_name(us_name: str) -> str | None:
            candidates = [
                name for name in fpl_names if us_name.lower() in name.lower() or name.lower() in us_name.lower()
            ]
            return candidates[0] if len(candidates) == 1 else None

        current_teams.loc[unmapped, "fpl_name"] = current_teams.loc[unmapped, "us_name"].map(guess_fpl_name)
    current_by_fpl_name = (
        current_teams.dropna(subset=["fpl_name"]).drop_duplicates("fpl_name").set_index("fpl_name").to_dict("index")
    )

    # Reuse the baseline's us_id/us_name per FPL team name; only current FPL
    # ids/codes come from the live bootstrap (they can churn season to season).
    # Prefer `current` (this season's own scraped fixtures) whenever it has
    # an entry - it's always at least as authoritative as the baseline, and
    # crucially self-heals a bad value the baseline might have picked up on
    # an earlier run (baseline_teams is read from the very table this
    # overwrites, so a wrong value can otherwise perpetuate itself forever).
    # Baseline is only needed as a fallback before a team's first fixture of
    # the season has been scraped.
    fpl_to_understat = {fpl: us for us, fpl in UNDERSTAT_TO_FPL.items()}
    baseline_by_fpl_name = baseline_teams.set_index("fpl_name").to_dict("index")
    rows = []
    for _, team in teams_fpl.iterrows():
        fallback_name = fpl_to_understat.get(team["fpl_name"], team["fpl_name"])
        current = current_by_fpl_name.get(team["fpl_name"], {})
        baseline = baseline_by_fpl_name.get(team["fpl_name"], {})
        if not pd.isna(current.get("us_id")):
            us_id = current.get("us_id")
            us_name = current.get("us_name") or fallback_name
        else:
            us_id = baseline.get("us_id")
            us_name = baseline.get("us_name") or fallback_name
        rows.append(
            {
                "fpl_id_24_25": int(team["fpl_id"]),
                "fpl_id": int(team["fpl_id"]),
                "fpl_name": team["fpl_name"],
                "fpl_short": team["fpl_short"],
                "fpl_code": int(team["fpl_code"]),
                "us_id": us_id,
                "us_name": us_name,
            }
        )
    team_reference = pd.DataFrame(rows)

    player_reference, unmatched = build_player_reference(
        players_fpl, rosters, team_reference, load_manual_matches()
    )

    if player_reference["fpl_code"].duplicated().any():
        raise ValueError("Player reference contains duplicate current FPL codes")

    replace_table(team_reference, "teams_reference")
    replace_table(player_reference, "player_reference")
    unmatched.to_csv(UNMATCHED_FILE, index=False)

    print(f"Teams: {len(team_reference)}")
    print(f"Current FPL players matched to Understat history: {len(player_reference)}")
    print(f"Players without a match: {len(unmatched)} (see {UNMATCHED_FILE})")


if __name__ == "__main__":
    run()
