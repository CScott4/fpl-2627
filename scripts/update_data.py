#!/usr/bin/env python
"""Run the weekly data-update pipeline: scrape, refresh references, recompute stats.

Usage:
    python scripts/update_data.py
"""
from __future__ import annotations

from fpl import db
from fpl.reference import refresh as refresh_references
from fpl.scrape import understat
from fpl.stats import player_stats, team_gsxg


def main() -> None:
    db.init_db()

    print("Scraping new Understat fixtures/shots/rosters...")
    understat.run()

    print("Refreshing FPL <-> Understat reference tables...")
    refresh_references.run()

    print("Recalculating player stats...")
    player_stats.run()

    print("Recalculating team GSxG factors...")
    team_gsxg.run()

    print("Done.")


if __name__ == "__main__":
    main()
