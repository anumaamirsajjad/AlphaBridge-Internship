"""Unit tests for TransactionService, using a mock database connection.

What this file does:
    Runs the read, list, and edit methods against a fake connection with
    scripted answers. Checks the results and the SQL parameters, such as the
    client ID that limits what the client can see.

Syntax used in this file, in plain words:
    {"key": value}          a dictionary: named values, looked up with d["key"]
    [a, b]                  a list
    name=value              a keyword argument: passes a value by name
    None                    "no value"
    x is y                  True only if x and y are the same object in memory
    x == y                  True if x and y have the same value
    d["key"]                reads one value from a dictionary
    f(...)[0][1]            reads the first item, then its second item
    a, b = pair             splits a two-item pair into two names
    with pytest.raises(E):  passes only if the code inside raises error E
    match="text"            also checks that the error message contains "text"
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from business.banking import BadRequestError, NotFoundError, PreconditionFailedError, TransactionService
from fake_database import connection, cursor, sql_calls
from validation.schemas import TransactionStatus

# A fixed timestamp, so the fake rows are the same on every run.
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)

# Matches the query that reads one transaction. The SQL filters it to the client's transactions.
ONE_TRANSACTION = "OR to_account_id IN"

# Matches the query that lists transactions, newest first.
LIST = "ORDER BY created_at DESC"

# Matches the query that changes a description.
EDIT = "SET description"

# Matches the query that reads the current version after an edit does not apply.
CURRENT_VERSION = "SELECT version FROM transactions"


# The client's transaction is returned, and the query is limited to that client.
def test_get_returns_transaction_and_filters_by_client():
    # uuid4() makes a random ID for the client.
    client_id = uuid4()

    # A dictionary standing for one transaction row. The ID is random.
    row = {"transaction_id": uuid4(), "status": "completed"}

    # The fake database returns this row for any query containing ONE_TRANSACTION.
    # cursor(row=row) means "return this one row"; row= is a keyword argument.
    conn = connection({ONE_TRANSACTION: cursor(row=row)})

    # row["transaction_id"] reads the ID value out of the dictionary.
    # The service is created with the fake connection and the client ID, then .get() is called.
    result = TransactionService(conn, client_id).get(row["transaction_id"])

    # "is" checks that result is the exact same object the fake database gave back.
    assert result is row

    # sql_calls(...) gives a list of matching (sql, params) pairs.
    # [0] takes the first pair, and [1] takes its params.
    # ["client_id"] reads the client ID that was sent with the query.
    assert sql_calls(conn, ONE_TRANSACTION)[0][1]["client_id"] == client_id


# An ID that does not exist, or belongs to someone else, gives 404.
def test_get_unknown_transaction_is_not_found():
    # cursor() with no arguments is an empty result: the query found nothing.
    conn = connection({ONE_TRANSACTION: cursor()})

    # pytest.raises says "this block must raise NotFoundError" to pass.
    with pytest.raises(NotFoundError):
        # uuid4() gives a random ID that does not exist in the fake data.
        TransactionService(conn, uuid4()).get(uuid4())


# The list returns the rows the query found, with the paging values passed to SQL.
def test_list_returns_rows_with_paging():
    row = {"transaction_id": uuid4(), "status": "completed"}

    # rows=[row] is a list with one item, returned as the full query result.
    conn = connection({LIST: cursor(rows=[row])})

    # Positional arguments: the order matters.
    #   None, None, None = no status filter, no start date, no end date
    #   50 = page size, 0 = offset (start at the first row)
    items = TransactionService(conn, uuid4()).list_all(None, None, None, 50, 0)

    # == on lists checks the same items in the same order.
    assert items == [row]

    # Read the parameters from the list query, then check the paging values.
    params = sql_calls(conn, LIST)[0][1]
    assert params["limit"] == 50
    assert params["offset"] == 0


# A status filter adds a status condition to the query.
def test_list_filters_by_status():
    conn = connection({LIST: cursor(rows=[])})

    # TransactionStatus.COMPLETED is an enum value: a fixed named choice.
    # Its underlying text is "completed".
    TransactionService(conn, uuid4()).list_all(TransactionStatus.COMPLETED, None, None, 50, 0)

    # conn.execute.call_args is a record of the most recent call to execute.
    # .args holds the values that call received: the SQL text and the params.
    # The pair is split into two names.
    sql, params = conn.execute.call_args.args

    # "in" checks whether the text appears inside the SQL string.
    assert "AND status =" in sql
    assert params["status"] == "completed"


# A start date after the end date is refused before any query runs.
def test_list_rejects_from_date_after_to_date():
    # connection() with no answers: nothing is expected to run.
    conn = connection()

    # datetime(2026, 1, 2) is the start date (year, month, day).
    # datetime(2026, 1, 1) is the end date, which is earlier, so the request is invalid.
    with pytest.raises(BadRequestError):
        TransactionService(conn, uuid4()).list_all(None, datetime(2026, 1, 2), datetime(2026, 1, 1), 50, 0)

    # Checks that the fake database was never used.
    conn.execute.assert_not_called()


# An edit with the current version changes the description and returns the new version.
def test_update_description_with_current_version():
    # The UPDATE returns the changed row: the new description and version 2.
    conn = connection({EDIT: cursor(row={"description": "New text", "version": 2})})

    # The arguments are: transaction ID, new description, expected version (1).
    row = TransactionService(conn, uuid4()).update_description(uuid4(), "New text", 1)

    # Read values from the returned dictionary.
    assert row["description"] == "New text"
    assert row["version"] == 2

    # Check that the expected version sent with the UPDATE was 1.
    assert sql_calls(conn, EDIT)[0][1]["expected_version"] == 1


# An edit with an out-of-date version is refused with 412, and the current version is shown.
def test_update_with_wrong_version_is_refused():
    # row=None: the UPDATE matched nothing, because the version was wrong.
    # Then the follow-up query returns the real version, 3.
    conn = connection({EDIT: cursor(row=None), CURRENT_VERSION: cursor(row={"version": 3})})

    # match="Current version: 3" checks that the error message contains this text.
    with pytest.raises(PreconditionFailedError, match="Current version: 3"):
        TransactionService(conn, uuid4()).update_description(uuid4(), "Too late", 1)


# An edit to a transaction the client does not own, or one that does not exist, gives 404.
def test_update_of_transaction_the_client_does_not_own_is_not_found():
    # Both answers are None: the UPDATE matched nothing, and the follow-up found no transaction.
    # The service then decides the transaction is not the client's, and raises 404.
    conn = connection({EDIT: cursor(row=None), CURRENT_VERSION: cursor(row=None)})

    with pytest.raises(NotFoundError):
        TransactionService(conn, uuid4()).update_description(uuid4(), "Not mine", 1)


# A start date alone adds only the "from" condition to the query.
def test_list_filters_by_from_date_only():
    conn = connection({LIST: cursor(rows=[])})
    start = datetime(2026, 1, 1)

    TransactionService(conn, uuid4()).list_all(None, start, None, 50, 0)

    sql, params = conn.execute.call_args.args
    assert "created_at >=" in sql
    assert "created_at <=" not in sql
    assert params["from_date"] == start


# An end date alone adds only the "to" condition to the query.
def test_list_filters_by_to_date_only():
    conn = connection({LIST: cursor(rows=[])})
    end = datetime(2026, 1, 31)

    TransactionService(conn, uuid4()).list_all(None, None, end, 50, 0)

    sql, params = conn.execute.call_args.args
    assert "created_at <=" in sql
    assert "created_at >=" not in sql
    assert params["to_date"] == end
