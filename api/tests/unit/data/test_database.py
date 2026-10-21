"""Unit tests for the connection helpers in data/database.py.

What this file does:
    Checks how connect() and database_is_available() behave when the
    DATABASE_URL setting is missing or points to nothing. No real database
    is used, because every address below is deliberately unreachable.
"""

import pytest
from unittest.mock import MagicMock

from data import database
from data.database import connect, database_is_available

# A port nothing listens on, with a short timeout, so the attempt fails fast.
UNREACHABLE_URL = "postgresql://user:pass@127.0.0.1:1/none?connect_timeout=1"


# Without DATABASE_URL, connect() refuses to run.
def test_connect_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError):
        with connect():
            pass


# Without DATABASE_URL, the health check reports the database as unavailable.
def test_availability_is_false_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database_is_available() is False


# When the database cannot be reached, the health check reports unavailable.
def test_availability_is_false_when_database_is_unreachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)

    assert database_is_available() is False


# With a URL set, connect() opens a connection using that URL and hands it to the caller.
# monkeypatch.setattr replaces psycopg.connect with a stand-in for this test only.
def test_connect_opens_connection_from_database_url(monkeypatch):
    fake_conn = MagicMock(name="connection")
    fake_connect = MagicMock()
    fake_connect.return_value.__enter__.return_value = fake_conn
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(database.psycopg, "connect", fake_connect)

    with connect() as conn:
        assert conn is fake_conn

    assert fake_connect.call_args.args[0] == "postgresql://example"


# When a simple query succeeds, the health check reports the database as available.
def test_availability_is_true_when_query_works(monkeypatch):
    fake_conn = MagicMock(name="connection")
    fake_connect = MagicMock()
    fake_connect.return_value.__enter__.return_value = fake_conn
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(database.psycopg, "connect", fake_connect)

    assert database_is_available() is True
    fake_conn.execute.assert_called_once_with("SELECT 1")
