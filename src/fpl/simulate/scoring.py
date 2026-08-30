"""FPL points-scoring rules.

Deliberately isolated from the simulation engine so that a rules change
(new season, new bonus categories) is a change in exactly one place.
Ports the logic embedded in `calc_fantasy_points` inside the old
`FPL_24-25.ipynb`.

Known gap vs. current FPL rules: defensive contribution points (DEF/MID/
FWD points for tackles + interceptions + clearances, or CBIT for
midfielders/forwards) are not modelled. Understat doesn't carry that
data, so this needs another source (FPL's own per-gameweek stats, or
something like FBref) before it can be added — see README.

TODO: port the position-dependent scoring table, and double-check the
per-action point values against the current FPL rules (they're liable to
have changed since the original code was written).
"""
from __future__ import annotations

# Points that don't depend on position.
POINTS_PLAYED = 1          # for any minutes played
POINTS_PLAYED_60 = 1       # additional point for >=60 minutes
POINTS_PER_ASSIST = 3
POINTS_PER_YELLOW = -1
POINTS_PER_RED = -3

# Position-dependent points: goals scored and clean sheets.
GOAL_POINTS = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
SAVES_PER_POINT = 3         # 1 point per 3 saves, goalkeepers only
GOALS_CONCEDED_PER_POINT_LOSS = 2  # -1 point per 2 goals conceded, GKP/DEF only

# TODO: Implement defensive contribution points
# For defenders: 2 points for accumulating 10 clearances, blocks, interceptions, and tackles
# For MID/FWD: 2 points for accumulating 12 clearances, blocks, interceptions, tackles, AND RECOVERIES
# These points don't stack e.g. a defender doesn't get 4 points for 20 clearances, blocks, interceptions, and tackles

# TODO: Other points to implement (which would be more difficult to simulate):
# - Bonus points (BPS)
# - Penalty saves
# - Penalty misses
# - Own goals

# TODO: Check that players who play 60+ minutes and were subbed off before a goal was conceded are still being awarded clean sheet points

# TODO: Check that red cards for two yellows are simulated and that the player only gets the red card reduction in that case

def calc_fantasy_points(
    position: str,
    minutes: int,
    goals: int,
    assists: int,
    clean_sheet: bool,
    goals_conceded: int,
    saves: int,
    yellow_cards: int,
    red_cards: int,
) -> float:
    """Compute FPL points for one player's match statline.

    Mirrors the original `calc_fantasy_points`, just with explicit
    keyword arguments instead of indexing into a numpy row by position.
    """
    points = 0.0
    if minutes > 0:
        points += POINTS_PLAYED
    if minutes >= 60:
        points += POINTS_PLAYED_60

    points += assists * POINTS_PER_ASSIST
    points += yellow_cards * POINTS_PER_YELLOW
    points += red_cards * POINTS_PER_RED
    points += goals * GOAL_POINTS.get(position, 0)

    if clean_sheet:
        points += CLEAN_SHEET_POINTS.get(position, 0)

    if position in ("GKP", "DEF"):
        points -= goals_conceded // GOALS_CONCEDED_PER_POINT_LOSS

    if position == "GKP":
        points += saves // SAVES_PER_POINT

    return points
