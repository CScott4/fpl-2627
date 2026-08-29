# FPL 26/27

Personal Fantasy Premier League prediction and squad-optimisation project.

Scrapes Understat + the FPL API, stores everything in SQLite, derives
team/player statistics, runs a minute-by-minute Monte Carlo simulation of
upcoming fixtures, and optimises squad selection against simulated points.

This is a rebuild of an earlier MongoDB-based prototype, restructured into
an installable package (`src/fpl`) with a thin notebook for weekly use.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e .                  # installs the `fpl` package in editable mode
cp .env.example .env              # then fill in your FPL entry ID etc.
python -m fpl.db                  # creates data/fpl.db with the schema below
```

Run `pytest` to check everything is wired up correctly.

## Repo layout

```
src/fpl/
    config.py          # env vars / constants (entry id, season, URLs)
    db.py               # SQLite engine + schema creation + read/write helpers
    schema.sql           # table definitions and indices
    scrape/
        understat.py     # pulls fixtures/shots/rosters from Understat
    reference/
        build.py         # one-off season-start FPL<->Understat id matching
        refresh.py        # ongoing refresh against the live FPL API
    stats/
        player_stats.py  # per-90 rates, start/appearance probabilities
        team_gsxg.py      # team xG/xGC factors by home/away and gamestate
    simulate/
        scoring.py        # FPL points rules, isolated so rule changes are one edit
        engine.py          # minute-by-minute match simulation
    squad/
        optimize.py        # MILP-based squad selection (see below)
        evaluate.py          # squad scoring / lineup selection given predictions
notebooks/
    weekly_analysis.ipynb  # thin notebook: import fpl, run the pipeline, inspect results
scripts/
    update_data.py          # CLI: scrape + recompute stats
    run_gameweek.py           # CLI: simulate + optimise squad for the next N gameweeks
tests/
data/
    fpl.db                    # SQLite database (gitignored)
```

## Data flow

1. `fpl.scrape.understat` — scrape new fixtures/shots/rosters into SQLite.
2. `fpl.reference.build` (once per season) / `fpl.reference.refresh` (ongoing)
   — match Understat player/team ids to current FPL ids.
3. `fpl.stats.player_stats` — aggregate rosters into per-player rates.
4. `fpl.stats.team_gsxg` — aggregate shots into team-level xG/xGC factors
   by home/away and gamestate (winning/drawing/losing).
5. `fpl.simulate.engine` — merge FPL bootstrap data with the derived stats
   and simulate upcoming fixtures minute-by-minute.
6. `fpl.squad.optimize` — pick the squad that maximises expected points
   under FPL's budget/position/club constraints.

## Notes / open questions

- Squad selection is intended to move from the old heuristic
  random-search + greedy-transfer approach to a MILP solve (PuLP), which
  should be both faster and provably optimal given the simulated points.
- Defensive contribution points (new FPL rule) aren't modelled yet —
  Understat doesn't carry tackles/interceptions/clearances, so this needs
  another data source before `simulate.scoring` can include it.
- Manual start-probability overrides (previously hardcoded in the
  notebook) should move to a small editable CSV/YAML rather than inline
  `.loc[]` calls — not yet built.
