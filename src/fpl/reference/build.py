"""One-off, season-start build of the FPL <-> Understat reference tables.

Ported from `RebuildFPLReferences.py`. Run this once at the start of a
season against the archived vaastav/Fantasy-Premier-League CSVs, to
fuzzy-match Understat player/team names onto that season's starting FPL
ids. Ongoing in-season updates go through `fpl.reference.refresh`
instead, which reuses `build_player_reference` below against the live
FPL bootstrap API.

`ARCHIVE_SEASON`/`SEASON_START` describe the *baseline* season this was
last run against (2025/26) - bump them and re-run once a fresh archive
snapshot exists for the season this project is currently tracking.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from fpl.config import REPO_ROOT
from fpl.db import read_table, replace_table

ARCHIVE_SEASON = "2025-26"
ARCHIVE_BASE_URL = (
    f"https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{ARCHIVE_SEASON}/"
)
SEASON_START = "2025-08-01"
SEASON_END = "2026-06-01"  # after the last 2025/26 match, before 2026/27 kicks off

MANUAL_MATCH_FILE = REPO_ROOT / "data" / "manual_player_matches.csv"
DUPLICATE_MATCH_FILE = REPO_ROOT / "data" / "duplicate_player_matches.csv"
UNMATCHED_FILE = REPO_ROOT / "data" / "unmatched_understat_names.csv"

# Understat's team names -> FPL's short display names. Stable bar
# promotion/relegation, so keep this in sync with the current top flight.
UNDERSTAT_TO_FPL = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds": "Leeds",
    "Liverpool": "Liverpool",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Sunderland": "Sunderland",
    "Tottenham": "Spurs",
    "West Ham": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
}

# Known Understat/FPL name mismatches the fuzzy matcher can't bridge on its
# own (nicknames, transliteration differences, etc). `load_manual_matches`
# layers `data/manual_player_matches.csv` (hand-editable) on top of these.
MANUAL_PLAYER_MATCHES = {
    "Rodri Man City": "Rodrigo Hernandez Man City",
    "Djordje Petrovic Chelsea": "Đorđe Petrović Chelsea",
    "Casemiro Man Utd": "Carlos Henrique Casimiro Man Utd",
    "Beto Everton": "Norberto Bercique Gomes Betuncal Everton",
    "Zanka Brentford": "Mathias Jorgensen Brentford",
    "Fode Toure Fulham": "Fodé Ballo-Touré Fulham",
    "Lucas Paquetá West Ham": "Lucas Tolentino Coelho de Lima West Ham",
    "Jorginho Arsenal": "Jorge Luiz Frello Filho Arsenal",
    "Diogo Jota Arsenal": "Diogo Teixeira da Silva Arsenal",
    "Carlos Vinicius Fulham": "Carlos Vinícius Alves Morais Fulham",
    "Andrey Santos Nott'm Forest": "Andrey Nascimento dos Santos Chelsea",
    "Jonny Wolves": "Jonathan Castro Otto Wolves",
}


def normalize(value: object) -> str:
    """Strip accents/punctuation/case so names compare on letters+digits only."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_score(left: str, right: str) -> float:
    """Similarity in [0, 1]: best of whole-name token overlap and character-sequence ratio."""
    left_tokens = {normalize(token) for token in str(left).split()}
    right_tokens = {normalize(token) for token in str(right).split()}
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    sequence = SequenceMatcher(None, normalize(left), normalize(right)).ratio()
    return max(overlap, sequence)


def load_manual_matches() -> dict[str, str]:
    """Load hand-edited `<us_name> <team>` -> `<fpl_name>` overrides, if the file exists."""
    if not MANUAL_MATCH_FILE.exists():
        return {}
    manual = pd.read_csv(MANUAL_MATCH_FILE).fillna("")
    required_columns = {"us_name", "team", "fpl_name"}
    if not required_columns.issubset(manual.columns):
        raise ValueError(f"{MANUAL_MATCH_FILE} must contain: {sorted(required_columns)}")
    manual = manual[manual["fpl_name"].astype(str).str.strip() != ""]
    return {f"{row['us_name']} {row['team']}": row["fpl_name"] for _, row in manual.iterrows()}


def build_team_reference(teams_fpl: pd.DataFrame, understat_fixtures: pd.DataFrame) -> pd.DataFrame:
    understat_teams = understat_fixtures[["home_team", "h_id"]].drop_duplicates()
    understat_teams = understat_teams.rename(columns={"home_team": "us_name", "h_id": "us_id"})
    understat_teams["fpl_name"] = understat_teams["us_name"].map(UNDERSTAT_TO_FPL)

    if understat_teams["fpl_name"].isna().any():
        unmapped = understat_teams.loc[understat_teams["fpl_name"].isna(), "us_name"].tolist()
        raise ValueError(f"Unmapped Understat teams: {unmapped}")

    reference = understat_teams.merge(teams_fpl, on="fpl_name", how="outer", indicator=True)
    missing = reference[reference["_merge"] != "both"]
    if not missing.empty:
        raise ValueError(f"Incomplete team reference:\n{missing}")

    reference = reference.drop(columns="_merge")
    reference["fpl_id"] = reference["fpl_id"].astype(int)
    reference["fpl_id_24_25"] = reference["fpl_id"]
    return reference[
        ["fpl_id_24_25", "fpl_id", "fpl_name", "fpl_short", "fpl_code", "us_id", "us_name"]
    ].sort_values("fpl_id")


def build_player_reference(
    players_fpl: pd.DataFrame,
    rosters: pd.DataFrame,
    team_reference: pd.DataFrame,
    manual_matches: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match every Understat player who's appeared in `rosters` to an FPL player.

    Returns (matched_reference, unmatched_rows). Matching order per
    Understat player: manual override -> exact normalized-name match ->
    unique substring match -> best fuzzy score within the player's team
    (threshold 0.62) -> best fuzzy score overall, only if the team has no
    FPL players at all e.g. newly promoted (threshold 0.72).
    """
    us_players = rosters[["player", "player_id", "team_id"]].drop_duplicates()
    us_players = us_players.rename(
        columns={"player": "us_name", "player_id": "us_id", "team_id": "us_team_id"}
    )
    us_players = us_players.merge(
        team_reference[["us_id", "fpl_name"]], left_on="us_team_id", right_on="us_id", suffixes=("", "_team")
    )
    us_players["us_name_id"] = us_players["us_name"] + " " + us_players["fpl_name"]

    fpl_players = players_fpl.copy()
    fpl_players["fpl_name_id"] = fpl_players["fpl_name"] + " " + fpl_players["fpl_name_team"]
    choices_by_team = {team: group for team, group in fpl_players.groupby("fpl_name_team")}
    exact_by_name = {name: group for name, group in fpl_players.groupby(fpl_players["fpl_name"].map(normalize))}

    matches = []
    unmatched = []
    for _, us_player in us_players.iterrows():
        choices = choices_by_team.get(us_player["fpl_name"], fpl_players.iloc[0:0])
        source_name = us_player["us_name_id"]
        target_name = MANUAL_PLAYER_MATCHES.get(source_name, source_name)
        manual_target = manual_matches.get(source_name)
        manual_candidates = (
            fpl_players[fpl_players["fpl_name"].map(normalize) == normalize(manual_target)]
            if manual_target
            else fpl_players.iloc[0:0]
        )
        exact_matches = exact_by_name.get(normalize(us_player["us_name"]), fpl_players.iloc[0:0])

        if len(manual_candidates) == 1:
            match, score = manual_candidates.iloc[0], 1.0
        elif len(exact_matches) == 1:
            match, score = exact_matches.iloc[0], 1.0
        else:
            normalized_us_name = normalize(us_player["us_name"])
            substring_matches = fpl_players[
                fpl_players["fpl_name"].map(normalize).apply(
                    lambda name: normalized_us_name in name or name in normalized_us_name
                )
            ]
            if len(substring_matches) == 1:
                match, score = substring_matches.iloc[0], 0.85
            else:
                match, score = None, 0

        if match is None and target_name in fpl_players["fpl_name_id"].values:
            match, score = fpl_players[fpl_players["fpl_name_id"] == target_name].iloc[0], 1.0
        elif match is None and target_name in choices["fpl_name_id"].values:
            match, score = choices[choices["fpl_name_id"] == target_name].iloc[0], 1.0
        elif match is None and choices.empty:
            scores = fpl_players["fpl_name"].apply(lambda name: name_score(us_player["us_name"], name))
            best_index = scores.idxmax()
            score = scores.loc[best_index]
            match = fpl_players.loc[best_index] if score >= 0.72 else None
        elif match is None:
            scores = choices["fpl_name"].apply(lambda name: name_score(us_player["us_name"], name))
            best_index = scores.idxmax()
            score = scores.loc[best_index]
            match = choices.loc[best_index] if score >= 0.62 else None

        if match is None:
            candidate_scores = fpl_players.copy()
            candidate_scores["candidate_score"] = candidate_scores["fpl_name"].apply(
                lambda name: name_score(us_player["us_name"], name)
            )
            candidate_scores = candidate_scores.sort_values("candidate_score", ascending=False).head(3)
            unmatched.append(
                {
                    "us_name": us_player["us_name"],
                    "team": us_player["fpl_name"],
                    "score": score,
                    "suggested_fpl_names": " | ".join(candidate_scores["fpl_name"]),
                    "suggested_fpl_teams": " | ".join(candidate_scores["fpl_name_team"]),
                }
            )
            continue

        matches.append(
            {
                "fpl_name": match["fpl_name"],
                "fpl_code": int(match["fpl_code"]),
                "fpl_id": int(match["fpl_id"]),
                "us_name": us_player["us_name"],
                "us_id": int(us_player["us_id"]),
                "us_team_id": int(us_player["us_team_id"]),
                "team": us_player["fpl_name"],
            }
        )

    player_reference = pd.DataFrame(matches)
    duplicate_fpl_codes = player_reference[player_reference.duplicated("fpl_code", keep=False)]
    if not duplicate_fpl_codes.empty:
        duplicate_fpl_codes.sort_values("us_id").to_csv(DUPLICATE_MATCH_FILE, index=False)
        player_reference = player_reference.drop_duplicates("fpl_code", keep="last")

    return player_reference, pd.DataFrame(unmatched)


def run() -> None:
    """One-off build of a season-start baseline reference from archived FPL data."""
    teams_fpl = pd.read_csv(f"{ARCHIVE_BASE_URL}teams.csv").rename(
        columns={"id": "fpl_id", "name": "fpl_name", "short_name": "fpl_short", "code": "fpl_code"}
    )[["fpl_id", "fpl_name", "fpl_short", "fpl_code"]]

    players_fpl = pd.read_csv(f"{ARCHIVE_BASE_URL}players_raw.csv").rename(
        columns={
            "id": "fpl_id",
            "first_name": "fpl_first_name",
            "second_name": "fpl_second_name",
            "team": "fpl_team_id",
            "code": "fpl_code",
        }
    )
    players_fpl["fpl_name"] = players_fpl["fpl_first_name"] + " " + players_fpl["fpl_second_name"]
    players_fpl = players_fpl.merge(
        teams_fpl[["fpl_id", "fpl_name"]], left_on="fpl_team_id", right_on="fpl_id", suffixes=("", "_team")
    )
    players_fpl["fpl_name_team"] = players_fpl["fpl_name_team"].astype(str)
    players_fpl = players_fpl[["fpl_id", "fpl_code", "fpl_name", "fpl_name_team"]]

    fixtures = read_table(
        "understat_fixtures", where=f"date >= '{SEASON_START}' AND date < '{SEASON_END}'"
    )
    if fixtures.empty:
        raise ValueError(f"No Understat fixtures found between {SEASON_START} and {SEASON_END}")
    rosters = read_table("understat_rosters")
    rosters = rosters[rosters["match_id"].isin(set(fixtures["match_id"]))]
    if rosters.empty:
        raise ValueError("No Understat rosters found for the baseline season")

    team_reference = build_team_reference(teams_fpl, fixtures)
    player_reference, unmatched = build_player_reference(
        players_fpl, rosters, team_reference, load_manual_matches()
    )

    if player_reference["fpl_code"].duplicated().any():
        raise ValueError("Player reference still contains duplicate FPL codes")

    replace_table(team_reference, "teams_reference")
    replace_table(player_reference, "player_reference")
    unmatched.to_csv(UNMATCHED_FILE, index=False)

    print(f"Teams: {len(team_reference)}")
    print(f"Players matched: {len(player_reference)}")
    print(f"Players unmatched: {len(unmatched)} (see {UNMATCHED_FILE})")


if __name__ == "__main__":
    run()
