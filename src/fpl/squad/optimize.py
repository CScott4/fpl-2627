"""MILP-based squad selection.

Replaces the old random-squad-generation + greedy single-transfer search
(`generate_random_squad_new`, `generate_best_squad`,
`single_transfer_improvements` in `FPL_24-25.ipynb`) with a Mixed Integer
Linear Program solved via PuLP, which is both faster and provably optimal
for a fixed set of expected-points estimates.

Two entry points:
- `select_squad`: best 15-player squad from scratch (or with certain
  players guaranteed a place — the old notebook's
  `generate_squad_with_players` use case).
- `plan_transfers`: best 15-player squad reachable from an existing
  squad, optionally capping how many players may change (the old
  notebook's `single_transfer_improvements`, done exactly instead of by
  greedy single-swap search).

Both maximise the *squad's* total `expected_points_col`, not the
starting XI's — pair the result with `fpl.squad.evaluate.evaluate_squad`
to get a per-gameweek lineup + captain, and see the docstring below on
what to pass as `expected_points_col` for the two to combine sensibly.
"""
from __future__ import annotations

import pandas as pd
import pulp

BUDGET = 100.0
SQUAD_SIZE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_CLUB = 3
TOTAL_SQUAD_SIZE = sum(SQUAD_SIZE.values())

# Weight nearer gameweeks more heavily when building an expected-points
# column, mirroring the old notebook's `multipliers = [10, 9, 8, 7, 6]`.
GAMEWEEK_WEIGHTS = [10, 9, 8, 7, 6]


def _base_squad_problem(
    player_pool: pd.DataFrame,
    expected_points_col: str,
    position_col: str,
    team_col: str,
) -> tuple[pulp.LpProblem, dict[object, pulp.LpVariable]]:
    """Build the formation/club constraints shared by both entry points; budget is added by the caller.

    Budget is deliberately *not* included here: `select_squad` and
    `plan_transfers` need different budget semantics (flat total cost vs.
    real buy/sell transfer economics — see `plan_transfers`'s docstring),
    so each adds its own.
    """
    problem = pulp.LpProblem("fpl_squad_selection", pulp.LpMaximize)
    include = {player: pulp.LpVariable(f"include_{player}", cat="Binary") for player in player_pool.index}

    problem += pulp.lpSum(
        player_pool.loc[player, expected_points_col] * include[player] for player in player_pool.index
    )

    problem += pulp.lpSum(include.values()) == TOTAL_SQUAD_SIZE

    for position, count in SQUAD_SIZE.items():
        players_in_position = player_pool.index[player_pool[position_col] == position]
        if len(players_in_position) < count:
            raise ValueError(f"player_pool has only {len(players_in_position)} {position}s; need {count}")
        problem += pulp.lpSum(include[player] for player in players_in_position) == count

    for team in player_pool[team_col].unique():
        players_in_team = player_pool.index[player_pool[team_col] == team]
        problem += pulp.lpSum(include[player] for player in players_in_team) <= MAX_PER_CLUB

    return problem, include


def _solve(problem: pulp.LpProblem, include: dict[object, pulp.LpVariable], player_pool: pd.DataFrame) -> pd.DataFrame:
    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(
            f"Squad selection did not find an optimal solution (status: {pulp.LpStatus[status]}). "
            "This usually means the constraints are infeasible — e.g. guarantees/current squad "
            "that can't fit the budget or club limits together."
        )
    selected = [player for player, var in include.items() if round(var.value()) == 1]
    return player_pool.loc[selected]


def select_squad(
    player_pool: pd.DataFrame,
    expected_points_col: str,
    budget: float = BUDGET,
    guarantees: list | None = None,
    cost_col: str = "now_cost",
    position_col: str = "position",
    team_col: str = "team",
) -> pd.DataFrame:
    """Return the optimal 15-player squad from `player_pool`.

    `player_pool` must be indexed by a unique player id/name, with a
    `position_col` (values 'GKP'/'DEF'/'MID'/'FWD'), `cost_col`,
    `team_col`, and `expected_points_col`. `guarantees`, if given, is a
    list of index values that must be included (e.g. players you already
    own and want to keep) — the solver fills every other slot optimally
    around them.

    What to put in `expected_points_col`: this maximises the *squad's*
    total, with no notion of bench vs. starter, so a raw single-gameweek
    points estimate will systematically over-value nailed bench fodder
    relative to a rotation-risk star. A closer proxy to "value to the
    squad" is each player's own weighted-average expected points across
    the next few gameweeks (see `GAMEWEEK_WEIGHTS`) — high for players
    who'll consistently start and score, low for fringe players — which
    is what `run()` below builds. If you want the squad chosen to
    literally maximise `evaluate_squad`'s output (i.e. account for the
    fact that only 11 of the 15 play each week), that's a much harder
    joint squad+lineup MILP; this function deliberately keeps to the
    simpler, well-defined "maximise the sum" problem the original TODO
    asked for.
    """
    guarantees = guarantees or []
    missing_guarantees = [player for player in guarantees if player not in player_pool.index]
    if missing_guarantees:
        raise ValueError(f"Guaranteed players not in player_pool: {missing_guarantees}")

    problem, include = _base_squad_problem(player_pool, expected_points_col, position_col, team_col)
    problem += (
        pulp.lpSum(player_pool.loc[player, cost_col] * include[player] for player in player_pool.index) <= budget
    )
    for player in guarantees:
        problem += include[player] == 1

    return _solve(problem, include, player_pool)


def plan_transfers(
    player_pool: pd.DataFrame,
    current_squad: list,
    expected_points_col: str,
    bank: float = 0.0,
    sale_price_col: str | None = None,
    max_transfers: int | None = None,
    cost_col: str = "now_cost",
    position_col: str = "position",
    team_col: str = "team",
) -> pd.DataFrame:
    """Return the optimal 15-player squad reachable from `current_squad`.

    Same formation/club constraints as `select_squad`, plus (if
    `max_transfers` is given) a cap on how many players may differ from
    `current_squad` — an exact replacement for the old notebook's greedy
    `single_transfer_improvements` loop, which searched one swap at a
    time and could miss combinations where e.g. two simultaneous
    transfers beat any single one on its own.

    Unlike `select_squad`, the budget constraint here models real FPL
    transfer economics rather than a flat total-cost cap: keeping a
    player costs nothing (you already own them), each player transferred
    *out* refunds their sale price, and each player transferred *in*
    costs their current market price — total incoming spend can't exceed
    `bank` plus total refunds from outgoing players. (An earlier version
    of this function used a flat `budget` cap like `select_squad`, which
    was wrong: it re-charged the market price of every kept player too,
    so it could report "no valid squad" even when you weren't proposing
    to change anything.)

    `bank` is your spare cash — e.g. `fpl.squad.my_team.fetch_my_team()`'s
    `transfer_status['bank']`, or `0.0` if you don't track it separately.
    `sale_price_col`, if given, is a column on `player_pool` with each
    *current-squad* player's real sale price (pass the `selling_price`
    column from `fpl.squad.my_team.fetch_my_team`, joined onto
    `player_pool`); if omitted, `cost_col` (current market price) is used
    as an approximation for current-squad players only, which can
    overstate what you'd actually receive for anyone who's risen in
    value since you bought them. Either way, incoming players are always
    costed at `cost_col` — you can't buy at a discount.
    """
    missing_current = [player for player in current_squad if player not in player_pool.index]
    if missing_current:
        raise ValueError(f"Current-squad players not in player_pool: {missing_current}")
    sale_price_col = sale_price_col or cost_col

    problem, include = _base_squad_problem(player_pool, expected_points_col, position_col, team_col)

    incoming_cost = pulp.lpSum(
        player_pool.loc[player, cost_col] * include[player]
        for player in player_pool.index
        if player not in current_squad
    )
    outgoing_refund = pulp.lpSum(
        player_pool.loc[player, sale_price_col] * (1 - include[player]) for player in current_squad
    )
    problem += incoming_cost <= bank + outgoing_refund

    if max_transfers is not None:
        kept = pulp.lpSum(include[player] for player in current_squad)
        problem += kept >= len(current_squad) - max_transfers

    return _solve(problem, include, player_pool)


def load_live_players() -> pd.DataFrame:
    """Live position/team/cost for every current FPL player, from the bootstrap API.

    Indexed by player name (first + second name, matching
    `fpl.simulate.engine`'s player pool), with an `fpl_id` column kept
    around so results can be cross-referenced against `.../picks/`
    responses (which key players by that same bootstrap element id).
    """
    import requests

    from fpl.config import FPL_BOOTSTRAP_URL

    bootstrap = requests.get(FPL_BOOTSTRAP_URL, timeout=30).json()
    teams_fpl = pd.DataFrame(bootstrap["teams"])[["id", "name"]].rename(columns={"id": "team_id", "name": "team"})
    positions = pd.DataFrame(bootstrap["element_types"])[["id", "singular_name_short"]].rename(
        columns={"id": "element_type", "singular_name_short": "position"}
    )
    players = pd.DataFrame(bootstrap["elements"]).rename(columns={"team": "team_id", "id": "fpl_id"})
    players["player"] = players["first_name"] + " " + players["second_name"]
    players = players.merge(teams_fpl, on="team_id").merge(positions, on="element_type")
    players["now_cost"] = players["now_cost"] / 10
    return players.set_index("player")[["fpl_id", "position", "team", "now_cost"]]


def expected_points_from_simulation(
    results: dict, gameweek_ids: list | None = None, weights: list[float] = GAMEWEEK_WEIGHTS
) -> pd.Series:
    """Weighted-average expected points per player, from a simulation run.

    `results` is `fpl.simulate.engine.simulate_next_gameweeks()`'s return
    value: ``{gameweek_id: (per_player_stats_df, scorelines)}``, where
    `per_player_stats_df` is indexed by player name with a 'points'
    column. `gameweek_ids` defaults to the first `len(weights)` of
    `results`' keys, in order — pass an explicit list to control which
    gameweeks are used (e.g. to skip one, or realign after a blank/double).
    """
    if gameweek_ids is None:
        gameweek_ids = sorted(results)
    gameweek_ids = list(gameweek_ids)[: len(weights)]
    if len(gameweek_ids) != len(weights):
        raise ValueError(
            f"Have {len(gameweek_ids)} gameweek(s) of results but {len(weights)} weight(s) — "
            "pass matching-length `gameweek_ids`/`weights`."
        )

    weighted_sum = None
    for weight, gameweek_id in zip(weights, gameweek_ids):
        gw_points = results[gameweek_id][0]["points"] * weight
        weighted_sum = gw_points if weighted_sum is None else weighted_sum.add(gw_points, fill_value=0)
    return (weighted_sum / sum(weights)).rename("expected_points")


def build_player_pool(
    results: dict, gameweek_ids: list | None = None, weights: list[float] = GAMEWEEK_WEIGHTS
) -> pd.DataFrame:
    """Live cost/position/team joined with simulated expected points, ready for `select_squad`.

    Players with no simulated minutes (e.g. league new-signings not yet
    matched to Understat history) get `expected_points = 0.0` rather than
    being dropped, so the optimiser can still see and correctly avoid them.
    """
    expected_points = expected_points_from_simulation(results, gameweek_ids, weights)
    player_pool = load_live_players().join(expected_points, how="left")
    player_pool["expected_points"] = player_pool["expected_points"].fillna(0.0)
    return player_pool


def run() -> None:
    """Entry point used by scripts/run_gameweek.py.

    Simulates the next few gameweeks (`fpl.simulate.engine`), builds each
    player's `GAMEWEEK_WEIGHTS`-weighted average expected points as the
    optimisation target, and solves for the best 15-player squad.
    """
    from fpl.simulate import engine

    results = engine.simulate_next_gameweeks(n_gameweeks=len(GAMEWEEK_WEIGHTS))
    player_pool = build_player_pool(results)

    squad = select_squad(player_pool, expected_points_col="expected_points")
    print(squad.sort_values("position"))
    print(f"\nTotal cost: {squad['now_cost'].sum():.1f}")
    print(f"Total expected points (weighted): {squad['expected_points'].sum():.2f}")


if __name__ == "__main__":
    run()
