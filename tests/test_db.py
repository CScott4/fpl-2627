"""Sanity checks for database setup.

These don't test any pipeline logic yet (there isn't any ported yet) —
just that the schema initializes cleanly and the read/write helpers
round-trip a DataFrame correctly, on an isolated temp database.
"""
from __future__ import annotations

import pandas as pd
import pytest

import fpl.db as db_module


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point fpl.db at a throwaway SQLite file for the duration of a test."""
    db_path = tmp_path / "test_fpl.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(db_module, "_engine", None, raising=False)

    # get_db_path()/get_engine() read the module-level DB_PATH via the
    # config import, so patch that too.
    import fpl.config as config_module
    monkeypatch.setattr(config_module, "DB_PATH", db_path, raising=False)

    db_module.init_db()
    yield db_path


def test_init_db_creates_expected_tables(temp_db):
    with db_module.get_connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    expected = {
        "understat_fixtures",
        "understat_shots",
        "understat_rosters",
        "understat_player_stats",
        "gsxg",
        "gsxg_avg",
        "teams_reference",
        "player_reference",
        "squads_and_predictions",
    }
    assert expected.issubset(tables)


def test_replace_table_round_trip(temp_db):
    df = pd.DataFrame(
        {
            "team": ["Arsenal", "Arsenal"],
            "h_a": ["h", "a"],
            "gamestate": ["Winning", "Losing"],
            "xg_factor": [1.05, 0.87],
            "xgc_factor": [0.91, 1.12],
        }
    )
    db_module.replace_table(df, "gsxg")

    result = db_module.read_table("gsxg").sort_values("h_a").reset_index(drop=True)
    assert len(result) == 2
    assert set(result["team"]) == {"Arsenal"}


def test_existing_ids_empty_on_fresh_db(temp_db):
    assert db_module.existing_ids("understat_fixtures", "match_id") == set()
