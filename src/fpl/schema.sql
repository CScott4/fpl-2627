-- Schema for the FPL SQLite database.
-- Mirrors the old MongoDB collections but with fixed columns/types and
-- explicit indices. Run via `fpl.db.init_db()` — every statement is
-- idempotent (IF NOT EXISTS) so it's safe to call on every startup.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Raw Understat data
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS understat_fixtures (
    match_id    INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,          -- ISO datetime string
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    h_id        INTEGER NOT NULL,
    a_id        INTEGER NOT NULL,
    home_goals  INTEGER,
    away_goals  INTEGER,
    home_xg     REAL,
    away_xg     REAL
);

CREATE INDEX IF NOT EXISTS idx_fixtures_date ON understat_fixtures(date);

-- One row per shot. action_team/opp_team + *_gamestate are computed at
-- scrape time (see fpl.scrape.understat) from the running score, exactly
-- as in the original scripts.
CREATE TABLE IF NOT EXISTS understat_shots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id                INTEGER NOT NULL REFERENCES understat_fixtures(match_id),
    minute                  INTEGER NOT NULL,
    result                  TEXT NOT NULL,       -- Goal / MissedShots / SavedShot / ...
    xg                      REAL NOT NULL,
    h_a                     TEXT NOT NULL,       -- 'h' or 'a'
    h_team                  TEXT NOT NULL,
    a_team                  TEXT NOT NULL,
    player                  TEXT,
    player_id               INTEGER,
    h_score                 INTEGER NOT NULL,    -- running score before this shot
    a_score                 INTEGER NOT NULL,
    mins_passed             INTEGER NOT NULL,    -- minutes since previous shot
    h_gamestate             TEXT NOT NULL,       -- Winning / Draw / Losing (home team's view)
    a_gamestate             TEXT NOT NULL,       -- ... (away team's view)
    action_team             TEXT NOT NULL,       -- team that took the shot
    action_team_gamestate   TEXT NOT NULL,
    opp_team                TEXT NOT NULL,
    opp_team_gamestate      TEXT NOT NULL,
    shot_num                INTEGER NOT NULL DEFAULT 1,
    shotontarget_num        INTEGER NOT NULL DEFAULT 0,
    goal                    INTEGER NOT NULL DEFAULT 0,
    competition              TEXT
);

CREATE INDEX IF NOT EXISTS idx_shots_match_id ON understat_shots(match_id);
CREATE INDEX IF NOT EXISTS idx_shots_action_team ON understat_shots(action_team);
CREATE INDEX IF NOT EXISTS idx_shots_opp_team ON understat_shots(opp_team);

CREATE TABLE IF NOT EXISTS understat_rosters (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id     INTEGER NOT NULL REFERENCES understat_fixtures(match_id),
    player_id    INTEGER NOT NULL,
    player       TEXT NOT NULL,
    team_id      INTEGER NOT NULL,
    position     TEXT,                 -- includes 'Sub' for substitutes
    time         INTEGER NOT NULL DEFAULT 0,
    goals        INTEGER NOT NULL DEFAULT 0,
    own_goals    INTEGER NOT NULL DEFAULT 0,
    assists      INTEGER NOT NULL DEFAULT 0,
    shots        INTEGER NOT NULL DEFAULT 0,
    xg           REAL NOT NULL DEFAULT 0,
    xa           REAL NOT NULL DEFAULT 0,
    xg_chain     REAL NOT NULL DEFAULT 0,
    xg_buildup   REAL NOT NULL DEFAULT 0,
    yellow_card  INTEGER NOT NULL DEFAULT 0,
    red_card     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rosters_match_id ON understat_rosters(match_id);
CREATE INDEX IF NOT EXISTS idx_rosters_player_id ON understat_rosters(player_id);

-- ---------------------------------------------------------------------
-- Derived stats (fully recalculated and replaced on every run)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS understat_player_stats (
    player_id       INTEGER PRIMARY KEY,
    player          TEXT NOT NULL,
    team_id         INTEGER NOT NULL,
    app             REAL,
    start           REAL,
    sixty           REAL,
    time_avg_start  REAL,
    time_avg_sub    REAL,
    time            REAL,
    goals           REAL,
    assists         REAL,
    own_goals       REAL,
    xg              REAL,
    xa              REAL,
    yellow_card     REAL,
    red_card        REAL,
    xg_p90          REAL,
    xa_p90          REAL,
    yellows_p90     REAL,
    reds_p90        REAL,
    team_xg_p90     REAL,
    team_xa_p90     REAL,
    app_prob        REAL,
    start_prob      REAL,
    sixty_prob      REAL,
    pct_team_xg     REAL,
    pct_team_xa     REAL,
    new_player      INTEGER
);

-- Team xG/xGC factors by home/away and gamestate.
CREATE TABLE IF NOT EXISTS gsxg (
    team        TEXT NOT NULL,
    h_a         TEXT NOT NULL,          -- 'h' or 'a'
    gamestate   TEXT NOT NULL,          -- Winning / Draw / Losing
    xg_factor   REAL NOT NULL,
    xgc_factor  REAL NOT NULL,
    PRIMARY KEY (team, h_a, gamestate)
);

CREATE TABLE IF NOT EXISTS gsxg_avg (
    h_a          TEXT NOT NULL,
    gamestate    TEXT NOT NULL,
    avg_xg_min   REAL NOT NULL,
    avg_xgc_min  REAL NOT NULL,
    PRIMARY KEY (h_a, gamestate)
);

-- ---------------------------------------------------------------------
-- FPL <-> Understat reference tables
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS teams_reference (
    fpl_id         INTEGER PRIMARY KEY,
    fpl_id_24_25   INTEGER,             -- legacy id column name kept for continuity; see README
    fpl_name       TEXT NOT NULL,
    fpl_short      TEXT,
    fpl_code       INTEGER,
    us_id          INTEGER,
    us_name        TEXT
);

CREATE TABLE IF NOT EXISTS player_reference (
    fpl_code     INTEGER PRIMARY KEY,
    fpl_id       INTEGER NOT NULL,
    fpl_name     TEXT NOT NULL,
    us_id        INTEGER,
    us_team_id   INTEGER,
    team         TEXT,
    us_name      TEXT
);

-- ---------------------------------------------------------------------
-- Simulation output
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS squads_and_predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gw          INTEGER NOT NULL,
    created_at  TEXT NOT NULL,          -- ISO timestamp
    squad_json  TEXT NOT NULL,          -- list of fpl_code, JSON-encoded
    lineup_json TEXT,                   -- starting XI + captain, JSON-encoded
    x_points    REAL
);

CREATE INDEX IF NOT EXISTS idx_squads_gw ON squads_and_predictions(gw);
