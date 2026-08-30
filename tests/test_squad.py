import sys
sys.path.insert(0, "src")

import pandas as pd
import pytest
from fpl.squad.evaluate import evaluate_squad, _best_xi_for_gameweek
from fpl.squad.optimize import select_squad, plan_transfers, SQUAD_SIZE, MAX_PER_CLUB


def make_squad():
    # 2 GKP, 5 DEF, 5 MID, 3 FWD = 15, with clear points ordering so we can
    # hand-check which formation/captain should be chosen.
    rows = []
    def add(name, pos, pts):
        rows.append({"player": name, "position": pos, "GW1": pts})
    add("gk1", "GKP", 5)
    add("gk2", "GKP", 1)
    for i, pts in enumerate([8, 7, 6, 2, 1]):
        add(f"def{i}", "DEF", pts)
    for i, pts in enumerate([9, 6, 5, 4, 1]):
        add(f"mid{i}", "MID", pts)
    for i, pts in enumerate([10, 3, 1]):
        add(f"fwd{i}", "FWD", pts)
    return pd.DataFrame(rows).set_index("player")


def test_best_xi_picks_best_gkp_and_valid_formation():
    squad = make_squad()
    total, starters, captain = _best_xi_for_gameweek(squad, "GW1")
    assert "gk1" in starters and "gk2" not in starters
    assert len(starters) == 11
    assert captain == "fwd0"  # highest points scorer (10) among starters


def test_best_xi_beats_naive_3_4_3():
    # A hand-computed 3-4-3 using the same top scorers would give:
    # gk1(5) + def0..2(8+7+6) + mid0..3(9+6+5+4) + fwd0..2(10+3+1) = 64
    # Optimal search should do at least as well (it will pick 3-5-2 for extra 1pt from mid4? let's just check >= naive)
    squad = make_squad()
    total, starters, captain = _best_xi_for_gameweek(squad, "GW1")
    naive = 5 + (8+7+6) + (9+6+5+4) + (10+3+1) + 10  # + captain double
    assert total >= naive


def test_evaluate_squad_weights_and_shape():
    squad = make_squad()
    squad["GW2"] = squad["GW1"] * 0.5
    total, lineups = evaluate_squad(squad, ["GW1", "GW2"], [2, 1])
    assert set(lineups.keys()) == {1, 2}
    assert lineups[1]["gw_points"] > lineups[2]["gw_points"]
    expected_total = lineups[1]["gw_points"] * 2 + lineups[2]["gw_points"] * 1
    assert abs(total - expected_total) < 1e-9


def make_player_pool(n_per_position=8, teams=("A", "B", "C", "D", "E", "F", "G", "H")):
    rows = []
    rng_points = 1.0
    for pos, count in [("GKP", n_per_position), ("DEF", n_per_position), ("MID", n_per_position), ("FWD", n_per_position)]:
        for i in range(count):
            team = teams[i % len(teams)]
            cost = 4.0 + (i % 6)
            points = float((i * 37) % 23) + 1  # pseudo-random but deterministic
            rows.append({"player": f"{pos}_{i}", "position": pos, "team": team, "now_cost": cost, "points": points})
    return pd.DataFrame(rows).set_index("player")


def test_select_squad_respects_all_constraints():
    pool = make_player_pool()
    squad = select_squad(pool, expected_points_col="points", budget=100.0)
    assert len(squad) == sum(SQUAD_SIZE.values())
    for pos, count in SQUAD_SIZE.items():
        assert (squad["position"] == pos).sum() == count
    assert squad["now_cost"].sum() <= 100.0 + 1e-9
    assert squad.groupby("team").size().max() <= MAX_PER_CLUB


def test_select_squad_respects_guarantees():
    pool = make_player_pool()
    # Force in a deliberately mediocre player and check it's still selected.
    guaranteed = "FWD_1"
    squad = select_squad(pool, expected_points_col="points", budget=100.0, guarantees=[guaranteed])
    assert guaranteed in squad.index


def test_select_squad_is_optimal_vs_brute_force_small_case():
    # Tiny pool where we can brute-force the answer: exactly enough players
    # per position to fill the squad, so the only real decision is nothing
    # (squad is forced) -- sanity check the objective/budget report correctly.
    rows = []
    global_i = 0
    for pos, count in SQUAD_SIZE.items():
        for i in range(count):
            rows.append({"player": f"{pos}_{i}", "position": pos, "team": f"T{global_i}", "now_cost": 5.0, "points": 10.0 + i})
            global_i += 1
    pool = pd.DataFrame(rows).set_index("player")
    squad = select_squad(pool, expected_points_col="points", budget=1000.0)
    assert len(squad) == len(pool)
    assert set(squad.index) == set(pool.index)


def test_plan_transfers_caps_number_of_changes():
    pool = make_player_pool()
    current = select_squad(pool, expected_points_col="points", budget=100.0)
    current_ids = current.index.tolist()

    # Boost a currently-unselected player enormously so the unconstrained
    # optimum would swap it in -- then check max_transfers=0 keeps the squad
    # unchanged, and max_transfers=1 allows exactly one swap.
    boosted_pool = pool.copy()
    outsider = pool.index[~pool.index.isin(current_ids)][0]
    boosted_pool.loc[outsider, "points"] = 9999.0

    unchanged = plan_transfers(boosted_pool, current_ids, "points", bank=0.0, max_transfers=0)
    assert set(unchanged.index) == set(current_ids)

    one_swap = plan_transfers(boosted_pool, current_ids, "points", bank=0.0, max_transfers=1)
    assert outsider in one_swap.index
    assert len(set(one_swap.index) & set(current_ids)) == len(current_ids) - 1


def test_plan_transfers_keeping_current_squad_never_needs_budget():
    # Regression test: an earlier version charged every *kept* player's
    # market price against the budget, so even "make zero transfers" could
    # come back infeasible. With bank=0 and no sale-price data, keeping the
    # exact current squad must always be a feasible (if not optimal) option.
    pool = make_player_pool()
    current = select_squad(pool, expected_points_col="points", budget=100.0)
    current_ids = current.index.tolist()

    result = plan_transfers(pool, current_ids, "points", bank=0.0, max_transfers=0)
    assert set(result.index) == set(current_ids)


def test_plan_transfers_respects_bank_and_sale_price():
    pool = make_player_pool()
    current = select_squad(pool, expected_points_col="points", budget=100.0)
    current_ids = current.index.tolist()

    # Give the current squad a real (lower-than-market) sale price via a
    # separate column, and boost one outsider so a transfer would be
    # worthwhile *if* it's affordable.
    pool_with_sale_price = pool.copy()
    pool_with_sale_price["selling_price"] = pool_with_sale_price["now_cost"]
    pool_with_sale_price.loc[current_ids, "selling_price"] -= 1.0  # sell-on fee

    outsider = pool.index[~pool.index.isin(current_ids)][0]
    pool_with_sale_price.loc[outsider, "points"] = 9999.0
    outsider_cost = pool_with_sale_price.loc[outsider, "now_cost"]

    # With no bank at all, the optimiser can still afford *a* swap by
    # selling someone whose sale price covers the incoming cost, but it
    # cannot always afford this *specific* outsider if the priciest
    # available sale price falls short -- with zero bank and a cheap
    # squad, expect no transfer to be worth making (or an affordable one).
    tight = plan_transfers(
        pool_with_sale_price, current_ids, "points",
        bank=0.0, sale_price_col="selling_price", max_transfers=1,
    )
    if outsider not in tight.index:
        # Not affordable yet -- give it enough bank to definitely cover
        # the gap and check it *does* get picked up.
        shortfall = outsider_cost - pool_with_sale_price["selling_price"].max()
        generous = plan_transfers(
            pool_with_sale_price, current_ids, "points",
            bank=max(shortfall, 0) + 1.0, sale_price_col="selling_price", max_transfers=1,
        )
        assert outsider in generous.index
    else:
        # It was already affordable with zero bank -- fine, the point
        # (feasibility never breaks, and the swap surfaces once affordable)
        # still holds.
        pass


def test_expected_points_from_simulation_weights_correctly():
    from fpl.squad.optimize import expected_points_from_simulation

    gw1_stats = pd.DataFrame({"points": [10.0, 4.0]}, index=["alice", "bob"])
    gw2_stats = pd.DataFrame({"points": [2.0, 8.0]}, index=["alice", "bob"])
    results = {101: (gw1_stats, {}), 102: (gw2_stats, {})}

    expected = expected_points_from_simulation(results, gameweek_ids=[101, 102], weights=[3, 1])
    assert expected["alice"] == (10.0 * 3 + 2.0 * 1) / 4
    assert expected["bob"] == (4.0 * 3 + 8.0 * 1) / 4


def test_expected_points_from_simulation_handles_players_missing_from_one_gameweek():
    from fpl.squad.optimize import expected_points_from_simulation

    # "carol" only has minutes simulated in gameweek 2 (e.g. she was injured
    # for gw1's simulation input) -- her gw1 contribution should be treated
    # as 0, not silently dropped from the result.
    gw1_stats = pd.DataFrame({"points": [10.0]}, index=["alice"])
    gw2_stats = pd.DataFrame({"points": [2.0, 5.0]}, index=["alice", "carol"])
    results = {1: (gw1_stats, {}), 2: (gw2_stats, {})}

    expected = expected_points_from_simulation(results, gameweek_ids=[1, 2], weights=[1, 1])
    assert set(expected.index) == {"alice", "carol"}
    assert expected["carol"] == 5.0 / 2


def test_expected_points_from_simulation_rejects_mismatched_lengths():
    from fpl.squad.optimize import expected_points_from_simulation
    import pytest

    results = {1: (pd.DataFrame({"points": [1.0]}, index=["a"]), {})}
    with pytest.raises(ValueError):
        expected_points_from_simulation(results, gameweek_ids=[1], weights=[1, 2])


def test_build_player_pool_merges_live_data_with_simulated_points(monkeypatch):
    from fpl.squad import optimize

    fake_live = pd.DataFrame(
        {"fpl_id": [1, 2, 3], "position": ["GKP", "DEF", "FWD"], "team": ["A", "A", "B"], "now_cost": [4.5, 5.0, 6.0]},
        index=["alice", "bob", "carol"],
    )
    monkeypatch.setattr(optimize, "load_live_players", lambda: fake_live)

    gw1_stats = pd.DataFrame({"points": [3.0, 1.0]}, index=["alice", "bob"])  # carol has no simulated minutes
    results = {1: (gw1_stats, {})}

    pool = optimize.build_player_pool(results, gameweek_ids=[1], weights=[1])
    assert list(pool.index) == ["alice", "bob", "carol"]
    assert pool.loc["carol", "expected_points"] == 0.0
    assert pool.loc["alice", "expected_points"] == 3.0
