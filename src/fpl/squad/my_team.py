"""Authenticated access to your own FPL squad."""

from __future__ import annotations

import pandas as pd
import requests

from fpl.auth import get_access_token
from fpl.config import (
    FPL_ENTRY_ID,
    FPL_MY_TEAM_URL_TEMPLATE,
)


def _get_authenticated_session() -> requests.Session:
    """Create a requests session with a valid FPL OAuth token."""

    access_token = get_access_token()

    session = requests.Session()

    session.headers.update(
        {
            "X-Api-Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
    )

    return session


def fetch_my_team(
    entry_id: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Return (picks, transfer_status) for the authenticated FPL entry.

    `picks` contains:

        fpl_id
        selling_price
        purchase_price
        is_captain
        is_vice_captain

    Prices are returned in millions rather than the raw FPL
    tenths-of-a-million representation.

    `transfer_status` contains:

        bank
        free_transfers
    """

    entry_id = entry_id or FPL_ENTRY_ID

    if not entry_id:
        raise ValueError(
            "Pass entry_id or set FPL_ENTRY_ID in .env"
        )

    session = _get_authenticated_session()

    url = FPL_MY_TEAM_URL_TEMPLATE.format(
        entry_id=entry_id
    )

    response = session.get(
        url,
        timeout=30,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "FPL authentication failed (401). "
            "Your access token may have expired or been revoked."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "FPL rejected the authenticated request (403). "
            "The token may be invalid or the API may have changed."
        )

    response.raise_for_status()

    data = response.json()

    if "picks" not in data:
        raise RuntimeError(
            "Unexpected FPL my-team response: "
            f"missing 'picks'. Keys returned: {sorted(data.keys())}"
        )

    picks = (
        pd.DataFrame(data["picks"])
        .rename(columns={"element": "fpl_id"})
    )

    required_columns = {
        "fpl_id",
        "selling_price",
        "purchase_price",
        "is_captain",
        "is_vice_captain",
    }

    missing = required_columns - set(picks.columns)

    if missing:
        raise RuntimeError(
            "FPL my-team response is missing expected columns: "
            f"{sorted(missing)}"
        )

    picks["selling_price"] = (
        picks["selling_price"] / 10
    )

    picks["purchase_price"] = (
        picks["purchase_price"] / 10
    )

    picks = picks.set_index("fpl_id")[
        [
            "selling_price",
            "purchase_price",
            "is_captain",
            "is_vice_captain",
        ]
    ]

    transfers = data.get("transfers", {})

    transfer_status = {
        "bank": transfers.get("bank", 0) / 10,
        "free_transfers": transfers.get("limit"),
    }

    return picks, transfer_status