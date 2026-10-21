"""Unit tests for TransferService, using a mock database connection.

What this file does:
    Runs TransferService.create against a fake connection with scripted
    answers, then checks the returned transaction and the SQL the service ran.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from business.banking import BadRequestError, ConflictError, ForbiddenError, NotFoundError, TransferService
from fake_database import account, connection, cursor, make_transfer, sql_calls

# Reads an earlier transfer made with the same Idempotency-Key.
KEY_LOOKUP = "FROM idempotency_keys k"
# Reads an existing transaction by ID, used when a retry is found.
TRANSACTION_BY_ID = "FROM transactions WHERE transaction_id"
# Locks the sender and receiver accounts, matched by name.
ACCOUNT_LOOKUP = "LOWER(TRIM(account_holder))"
# Checks whether the client owns an account.
OWNERSHIP = "SELECT 1 FROM client_accounts"
# Saves a new transfer.
NEW_TRANSFER = "INSERT INTO transactions"
# Changes a balance.
BALANCE_CHANGE = "UPDATE accounts"


# A valid transfer moves the money, and the saved row is returned as completed.
def test_create_moves_money_and_saves_completed():
    ali = account("Ali Ahmed", "50000.00")
    maham = account("Maham", "20000.00")
    saved = {"transaction_id": uuid4(), "status": "completed"}
    conn = connection({
        KEY_LOOKUP: cursor(),
        ACCOUNT_LOOKUP: cursor(rows=[ali, maham]),
        OWNERSHIP: cursor(row={"?": 1}),
        NEW_TRANSFER: cursor(row=saved),
    })

    transaction, created = TransferService(conn, uuid4()).create(uuid4(), make_transfer())

    assert created is True
    assert transaction is saved
    # The sender loses the amount first, then the receiver gains it.
    assert sql_calls(conn, BALANCE_CHANGE)[0][1] == (Decimal("1.00"), ali["account_id"])
    assert sql_calls(conn, BALANCE_CHANGE)[1][1] == (Decimal("1.00"), maham["account_id"])
    assert "'completed'" in sql_calls(conn, NEW_TRANSFER)[0][0]


# A retry with a key that already made a transfer returns that transfer and moves no money.
def test_retry_with_same_key_returns_existing_transaction():
    ali = account("Ali Ahmed", "49999.00")
    stored = {"transaction_id": uuid4(), "status": "completed"}
    earlier = {
        "transaction_id": stored["transaction_id"],
        "from_account_id": ali["account_id"],
        "amount": Decimal("1.00"),
        "currency": "PKR",
        "description": "Test transfer",
        "source_name": "Ali Ahmed",
        "destination_name": "Maham",
    }
    conn = connection({
        KEY_LOOKUP: cursor(row=earlier),
        TRANSACTION_BY_ID: cursor(row=stored),
        OWNERSHIP: cursor(row={"?": 1}),
    })

    transaction, created = TransferService(conn, uuid4()).create(uuid4(), make_transfer())

    assert created is False
    assert transaction is stored
    assert sql_calls(conn, BALANCE_CHANGE) == []


# The same key with a different amount is refused, because it is a different request.
def test_same_key_with_different_body_is_refused():
    ali = account("Ali Ahmed", "49999.00")
    earlier = {
        "transaction_id": uuid4(),
        "from_account_id": ali["account_id"],
        "amount": Decimal("1.00"),
        "currency": "PKR",
        "description": "Test transfer",
        "source_name": "Ali Ahmed",
        "destination_name": "Maham",
    }
    conn = connection({KEY_LOOKUP: cursor(row=earlier), OWNERSHIP: cursor(row={"?": 1})})

    with pytest.raises(ConflictError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(amount=Decimal("2.00")))
    assert sql_calls(conn, BALANCE_CHANGE) == []


# Sending to the same account, ignoring case and spaces, is refused before any query runs.
def test_same_source_and_destination_is_refused():
    conn = connection()

    with pytest.raises(BadRequestError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(source="Maham", destination=" maham "))
    conn.execute.assert_not_called()


# A name with no matching account is refused with 404.
def test_unknown_source_account_is_refused():
    maham = account("Maham", "20000.00")
    conn = connection({KEY_LOOKUP: cursor(), ACCOUNT_LOOKUP: cursor(rows=[maham])})

    with pytest.raises(NotFoundError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(source="Nobody"))
    assert sql_calls(conn, BALANCE_CHANGE) == []


# A client cannot send from an account it does not own, so the service refuses with 403.
def test_cannot_send_from_another_clients_account():
    bilal = account("Bilal", "100.00", currency="USD")
    maham = account("Maham", "20000.00")
    conn = connection({
        KEY_LOOKUP: cursor(),
        ACCOUNT_LOOKUP: cursor(rows=[bilal, maham]),
        OWNERSHIP: cursor(),
    })

    with pytest.raises(ForbiddenError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(source="Bilal", currency="USD"))
    assert sql_calls(conn, BALANCE_CHANGE) == []


# A transfer larger than the balance is refused, and no balance changes.
def test_insufficient_funds_is_refused():
    ali = account("Ali Ahmed", "50000.00")
    maham = account("Maham", "20000.00")
    conn = connection({
        KEY_LOOKUP: cursor(),
        ACCOUNT_LOOKUP: cursor(rows=[ali, maham]),
        OWNERSHIP: cursor(row={"?": 1}),
    })

    with pytest.raises(BadRequestError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(amount=Decimal("999999.00")))
    assert sql_calls(conn, BALANCE_CHANGE) == []


# The transfer currency must match both accounts, or nothing moves.
def test_currency_must_match_both_accounts():
    ali = account("Ali Ahmed", "50000.00")
    maham = account("Maham", "20000.00")
    conn = connection({
        KEY_LOOKUP: cursor(),
        ACCOUNT_LOOKUP: cursor(rows=[ali, maham]),
        OWNERSHIP: cursor(row={"?": 1}),
    })

    with pytest.raises(BadRequestError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer(currency="USD"))
    assert sql_calls(conn, BALANCE_CHANGE) == []


# Two accounts with the same name make the sender ambiguous, so the transfer is refused.
def test_ambiguous_source_account_name_is_refused():
    ali = account("Ali Ahmed", "50000.00")
    ali_copy = account("Ali Ahmed", "100.00")
    maham = account("Maham", "20000.00")
    conn = connection({
        KEY_LOOKUP: cursor(),
        ACCOUNT_LOOKUP: cursor(rows=[ali, ali_copy, maham]),
        OWNERSHIP: cursor(row={"?": 1}),
    })

    with pytest.raises(ConflictError):
        TransferService(conn, uuid4()).create(uuid4(), make_transfer())
    assert sql_calls(conn, BALANCE_CHANGE) == []
