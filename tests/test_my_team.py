"""Tests for fpl.squad.my_team (authenticated sale-price lookups).

All HTTP is mocked -- these never make real requests to FPL, so they're
safe to run without credentials and don't depend on the live site.
"""
import sys

sys.path.insert(0, "src")

from unittest.mock import MagicMock, patch

import pytest

import pandas as pd
import pytest

def make_fake_session(my_team_json, login_cookies=None):
    fake_session = MagicMock()
    login_response = MagicMock()
    login_response.raise_for_status = lambda: None
    fake_session.post.return_value = login_response
    fake_session.cookies.get_dict.return_value = login_cookies if login_cookies is not None else {"pl_profile": "abc"}

    get_response = MagicMock()
    get_response.raise_for_status = lambda: None
    get_response.json.return_value = my_team_json
    fake_session.get.return_value = get_response
    return fake_session


def test_fetch_my_team_happy_path(monkeypatch):
    import fpl.config as config
    monkeypatch.setattr(config, "FPL_EMAIL", "me@example.com")
    monkeypatch.setattr(config, "FPL_PASSWORD", "hunter2")

    from fpl.squad import my_team
    monkeypatch.setattr(my_team, "FPL_EMAIL", "me@example.com")
    monkeypatch.setattr(my_team, "FPL_PASSWORD", "hunter2")

    fake_my_team_response = {
        "picks": [
            {"element": 101, "position": 1, "selling_price": 45, "purchase_price": 40,
             "multiplier": 1, "is_captain": False, "is_vice_captain": False, "is_sub": False},
            {"element": 202, "position": 2, "selling_price": 60, "purchase_price": 65,
             "multiplier": 2, "is_captain": True, "is_vice_captain": False, "is_sub": False},
        ],
        "transfers": {"bank": 15, "limit": 2, "value": 1000},
    }
    fake_session = make_fake_session(fake_my_team_response)

    with patch("requests.Session", return_value=fake_session):
        picks, transfer_status = my_team.fetch_my_team(entry_id="123")

    assert list(picks.index) == [101, 202]
    assert picks.loc[101, "selling_price"] == 4.5
    assert picks.loc[202, "purchase_price"] == 6.5
    assert picks.loc[202, "is_captain"] == True
    assert transfer_status == {"bank": 1.5, "free_transfers": 2}
    print("happy path OK")


def test_fetch_my_team_missing_credentials_raises(monkeypatch):
    from fpl.squad import my_team
    monkeypatch.setattr(my_team, "FPL_EMAIL", None)
    monkeypatch.setattr(my_team, "FPL_PASSWORD", None)

    with pytest.raises(ValueError, match="FPL_EMAIL"):
        my_team.fetch_my_team(entry_id="123")
    print("missing-credentials OK")


def test_fetch_my_team_failed_login_raises(monkeypatch):
    from fpl.squad import my_team
    monkeypatch.setattr(my_team, "FPL_EMAIL", "me@example.com")
    monkeypatch.setattr(my_team, "FPL_PASSWORD", "wrongpassword")

    fake_session = make_fake_session({}, login_cookies={})  # no cookies == failed login

    with patch("requests.Session", return_value=fake_session):
        with pytest.raises(RuntimeError, match="session cookie"):
            my_team.fetch_my_team(entry_id="123")
    print("failed-login OK")


def test_fetch_my_team_unexpected_shape_raises(monkeypatch):
    from fpl.squad import my_team
    monkeypatch.setattr(my_team, "FPL_EMAIL", "me@example.com")
    monkeypatch.setattr(my_team, "FPL_PASSWORD", "hunter2")

    fake_session = make_fake_session({"something_else": True})

    with patch("requests.Session", return_value=fake_session):
        with pytest.raises(RuntimeError, match="Unexpected my-team response shape"):
            my_team.fetch_my_team(entry_id="123")
    print("unexpected-shape OK")


def test_fetch_my_team_requires_entry_id(monkeypatch):
    from fpl.squad import my_team
    monkeypatch.setattr(my_team, "FPL_EMAIL", "me@example.com")
    monkeypatch.setattr(my_team, "FPL_PASSWORD", "hunter2")
    monkeypatch.setattr(my_team, "FPL_ENTRY_ID", None)

    with pytest.raises(ValueError, match="entry_id"):
        my_team.fetch_my_team()
    print("no-entry-id OK")
