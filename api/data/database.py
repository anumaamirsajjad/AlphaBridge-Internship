"""Database connection.

What this file does:
    Opens connections to PostgreSQL using the DATABASE_URL environment variable.
    Every database call in the app goes through connect().
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# Opens one connection for one unit of work.
# Commits when the "with" block finishes normally. Rolls back on any error.
@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    # Read the connection string. None if the variable is not set.
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")

    # dict_row: each row is a dictionary, e.g. row["balance"].
    with psycopg.connect(url, row_factory=dict_row) as conn:
        # Pause here while the caller's "with" block runs.
        yield conn


# Used by the health check. True if a simple query works.
def database_is_available() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except (psycopg.Error, RuntimeError):
        # Writes the real error to the logs. The caller only sees "unavailable".
        logger.exception("Database health check failed")
        return False
