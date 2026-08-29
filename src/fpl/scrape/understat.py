"""Scrape new fixtures/shots/rosters from Understat into SQLite.

Ports the logic from the old `ScrapeUnderstatNew.py` (the version actually
called from the pipeline — `FixingUnderstatScrape.py` and
`Full_Understat_Scrape.ipynb` were earlier, superseded attempts and are
not being carried forward).

Behaviour to preserve from the original:
- Pull the season's fixture list from Understat's `getLeagueData` endpoint,
  keep only results (`isResult`), and skip match_ids already in the DB
  (`fpl.db.existing_ids`) instead of always re-scraping everything.
- For each new match, hit `getMatchData/{match_id}` for shots + rosters.
- Compute running score and gamestate (Winning/Draw/Losing) per shot from
  the chronological shot list, for both the acting team and the opponent.

TODO: port `fixture_record`, `process_shots`, `process_match`, and `main`
from ScrapeUnderstatNew.py, swapping the Mongo insert_many calls for
`fpl.db.append_rows`.
"""
from __future__ import annotations

import pandas as pd


def scrape_new_fixtures() -> pd.DataFrame:
    """Fetch and store any Understat fixtures not already in the database."""
    raise NotImplementedError("Port from ScrapeUnderstatNew.py")


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    scrape_new_fixtures()


if __name__ == "__main__":
    run()
