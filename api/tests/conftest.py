"""Shared test setup: database, fixtures, and helpers used by every test file.

What this file does:
    - Uses a separate database, banking_test, so the real banking_db is never
      changed by a test run. It is rebuilt from the SQL files in init\\ once per run.
    - Before every test, it clears the tables and creates three accounts:
      Ali Ahmed (50,000 PKR), Maham (20,000 PKR) and Bilal (100 USD).
    - Creates two API clients: the test client owns Ali and Maham, and the
      other client owns only Bilal.

    A "fixture" is a function that prepares something for a test. A test asks
    for one by naming it as a parameter, for example "client" or "db".
"""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from banking import hash_api_key
from main import app

# The test database address. Uses TEST_DATABASE_URL if set, otherwise the default below.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://banking_user:local_dev_password@localhost:5432/banking_test",
)
TEST_DB_NAME = urlsplit(TEST_DATABASE_URL).path.lstrip("/")
# The init folder: tests -> api -> project, then "init".
INIT_DIR = Path(__file__).resolve().parents[2] / "init"

# Safety check: never run tests against the real database.
if TEST_DB_NAME == "banking_db":
    raise RuntimeError("TEST_DATABASE_URL must not point at the real banking_db.")

# The app reads DATABASE_URL on every request, so point it at the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# The keys for the two test clients. Only their hashes are stored in the database.
TEST_API_KEY = "test-key-owns-ali-and-maham"
OTHER_API_KEY = "other-key-owns-bilal"


def _admin_url() -> str:
    """Connection to the built-in 'postgres' database, used to create banking_test."""
    return urlunsplit(urlsplit(TEST_DATABASE_URL)._replace(path="/postgres"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Runs once per test run. Drops and recreates banking_test, then runs the init SQL files.
@pytest.fixture(scope="session", autouse=True)
def _build_test_database() -> Iterator[None]:
    # autocommit is required for CREATE DATABASE.
    with psycopg.connect(_admin_url(), autocommit=True) as conn:
        name = sql.Identifier(TEST_DB_NAME)
        # WITH (FORCE) disconnects anyone still using the old test database.
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(name))

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        for script in sorted(INIT_DIR.glob("*.sql")):
            conn.execute(script.read_text(encoding="utf-8"))
    yield


# A direct database connection, for setting up data and checking balances.
@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        yield conn


# Runs before EVERY test. Clears the data and creates the accounts and API clients.
# Returns {account holder name: account ID}.
@pytest.fixture(autouse=True)
def accounts(db: psycopg.Connection) -> dict[str, UUID]:
    db.execute(
        "TRUNCATE transactions, refunds, cancellations, idempotency_keys, "
        "operation_idempotency, client_accounts, api_clients, accounts CASCADE"
    )
    rows = db.execute(
        """
        INSERT INTO accounts (account_holder, currency, balance) VALUES
            ('Ali Ahmed', 'PKR', 50000.00),
            ('Maham',     'PKR', 20000.00),
            ('Bilal',     'USD',   100.00)
        RETURNING account_holder, account_id
        """
    ).fetchall()
    ids = {holder: account_id for holder, account_id in rows}

    _create_client(db, "Test client", TEST_API_KEY, [ids["Ali Ahmed"], ids["Maham"]])
    _create_client(db, "Other client", OTHER_API_KEY, [ids["Bilal"]])
    return ids


# The client for the test client: sends the key on every request.
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, headers={"X-API-Key": TEST_API_KEY}) as test_client:
        yield test_client


# The second client. It owns only Bilal's account.
@pytest.fixture
def other_client() -> Iterator[TestClient]:
    with TestClient(app, headers={"X-API-Key": OTHER_API_KEY}) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Helpers used by the test files
# ---------------------------------------------------------------------------

# Saves an API client with its key hash, and links it to the given accounts.
def _create_client(db: psycopg.Connection, name: str, api_key: str, account_ids: list[UUID]) -> None:
    client_id = db.execute(
        "INSERT INTO api_clients (name, key_hash) VALUES (%s, %s) RETURNING client_id",
        (name, hash_api_key(api_key)),
    ).fetchone()[0]
    for account_id in account_ids:
        db.execute(
            "INSERT INTO client_accounts (client_id, account_id) VALUES (%s, %s)",
            (client_id, account_id),
        )


# A valid transfer body: 1 PKR from Ali Ahmed to Maham. Named values replace defaults.
def transfer_body(**overrides) -> dict:
    body = {
        "amount": "1",
        "currency": "PKR",
        "source": "Ali Ahmed",
        "destination": "Maham",
        "description": "Test transfer",
    }
    body.update(overrides)
    return body


# The headers that carry an Idempotency-Key.
def with_key(key) -> dict:
    return {"Idempotency-Key": str(key)}


# Reads one account's balance by holder name.
def balance_of(db: psycopg.Connection, holder: str) -> Decimal:
    row = db.execute(
        "SELECT balance FROM accounts WHERE account_holder = %s", (holder,)
    ).fetchone()
    return row[0]


# Counts all rows in the transactions table.
def transaction_count(db: psycopg.Connection) -> int:
    return db.execute("SELECT count(*) FROM transactions").fetchone()[0]


# Inserts a pending transaction directly, because the API cannot create one.
# It goes from Ali Ahmed to Maham, so the test client owns it.
def insert_pending_transaction(db: psycopg.Connection, accounts: dict) -> str:
    row = db.execute(
        """
        INSERT INTO transactions
            (from_account_id, to_account_id, amount, currency, description, status)
        VALUES (%s, %s, 10.00, 'PKR', 'Seeded pending', 'pending')
        RETURNING transaction_id
        """,
        (accounts["Ali Ahmed"], accounts["Maham"]),
    ).fetchone()
    return str(row[0])
