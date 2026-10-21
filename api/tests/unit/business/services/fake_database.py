"""Helpers for building a fake database connection in the service tests.

What this file does:
    Creates mock query results and a mock connection. A test lists which
    piece of SQL should return which result, runs the service, and then
    checks the SQL the service ran.
"""

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from validation.schemas import TransactionCreate


#fetchone() returns one row, fetchall() returns a list.
def cursor(row=None, rows=None):
    result = MagicMock()
    result.fetchone.return_value = row
    result.fetchall.return_value = rows if rows is not None else []
    return result


# A fake connection. The answers dictionary maps SQL text to the cursor returned when a
# query contains that text. Any query that matches nothing returns an empty cursor.
def connection(answers=None):
    answers = answers or {}
    conn = MagicMock(name="connection")

    def execute(sql, params=None):
        for fragment, result in answers.items():
            if fragment in sql:
                return result
        return cursor()

    conn.execute.side_effect = execute
    return conn


# The (sql, params) pairs run on a fake connection whose SQL contains the fragment.
def sql_calls(conn, fragment):
    return [call.args for call in conn.execute.call_args_list if fragment in call.args[0]]


# A bank account row shaped like the rows the services read from the database.
def account(holder, balance, currency="PKR"):
    return {
        "account_id": uuid4(),
        "account_holder": holder,
        "currency": currency,
        "balance": Decimal(balance),
    }


# A valid transfer request: 1.00 PKR from Ali Ahmed to Maham. Pass named values to change any field.
def make_transfer(**overrides):
    values = {
        "amount": Decimal("1.00"),
        "currency": "PKR",
        "source": "Ali Ahmed",
        "destination": "Maham",
        "description": "Test transfer",
    }
    values.update(overrides)
    return TransactionCreate(**values)
