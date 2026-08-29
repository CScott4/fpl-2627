"""Database access for the FPL project.

SQLite is the storage backend. This module is the only place that should
know about connection details — everything else works with pandas
DataFrames in and out.

Two access patterns are provided:
- `get_connection()`: a raw sqlite3 connection, for schema setup and any
  hand-written SQL.
- `get_engine()`: a SQLAlchemy engine, for `pandas.read_sql` /
  `DataFrame.to_sql`, which is how most of the pipeline will read/write.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from fpl.config import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_engine: Engine | None = None  # lazily created, reused across calls


def get_db_path() -> Path:
    """Return the configured database path, ensuring its parent dir exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine for the SQLite database."""
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{get_db_path()}")
    return _engine


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a raw sqlite3 connection as a context manager.

    Commits on success, rolls back on exception:

        with get_connection() as conn:
            conn.execute("DELETE FROM gsxg")
    """
    conn = sqlite3.connect(get_db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables and indices if they don't already exist.

    Safe to call on every startup — every statement in schema.sql is
    written with IF NOT EXISTS.
    """
    schema_sql = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(schema_sql)


def read_table(table_name: str, where: str | None = None) -> pd.DataFrame:
    """Read a full table (optionally filtered) into a DataFrame.

    `where`, if given, is appended verbatim after WHERE — keep it to
    trusted, hardcoded filters (e.g. "date >= '2025-08-01'"), not
    unsanitised user input.
    """
    query = f"SELECT * FROM {table_name}"
    if where:
        query += f" WHERE {where}"
    return pd.read_sql(text(query), get_engine())


def replace_table(df: pd.DataFrame, table_name: str) -> None:
    """Overwrite a table's full contents with `df`.

    Use for tables that are entirely recalculated each run, mirroring the
    old `delete_many({}); insert_many(...)` pattern (e.g. gsxg,
    understat_player_stats, teams_reference, player_reference).
    """
    df.to_sql(table_name, get_engine(), if_exists="replace", index=False)


def append_rows(df: pd.DataFrame, table_name: str) -> None:
    """Append rows to a table that accumulates over time.

    Use for tables that only ever grow (e.g. understat_fixtures,
    understat_shots, understat_rosters) — callers are responsible for
    filtering out already-scraped rows first (see fpl.scrape.understat).
    """
    df.to_sql(table_name, get_engine(), if_exists="append", index=False)


def existing_ids(table_name: str, id_column: str) -> set:
    """Return the set of distinct values already present in a column.

    Used to figure out which fixtures/matches are new before scraping,
    replacing Mongo's `.distinct(...)`.
    """
    with get_connection() as conn:
        cursor = conn.execute(f"SELECT DISTINCT {id_column} FROM {table_name}")
        return {row[0] for row in cursor.fetchall()}


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {get_db_path()}")
