"""Unit tests for RefundService, using a mock database connection.

What this file does:
    Runs RefundService.refund against a fake connection with scripted answers.
    The original transfer in every test is 10.00 PKR from Ali to Maham.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from business.banking import BadRequestError, ConflictError, NotFoundError, RefundService, fingerprint
from fake_database import connection, cursor, sql_calls
from validation.schemas import RefundCreate

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
# Reads a transaction the client sent. Returns nothing if it is not the client's.
SENT_TRANSACTION = "AND from_account_id IN"
# Finds a saved answer for this refund key.
SAVED_REFUND = "WHERE operation = 'refund'"
# Reads the sender and receiver balances.
BALANCES = "FROM accounts WHERE account_id IN"
# Adds up what has already been refunded.
REFUNDED_SO_FAR = "COALESCE(SUM(amount)"
# Saves the refund row.
REFUND_RECORD = "INSERT INTO refunds"
# Marks the whole transfer as refunded.
FULL_REFUND_STATUS = "SET status = 'refunded'"


# Answers for a refund on a 10.00 PKR transfer. Each test changes only what it needs.
def refund_answers(tid, from_id, to_id, *, amount, status="completed", refunded=Decimal("0"),
                   to_balance=Decimal("20010.00"), saved=None):
    return {
        SENT_TRANSACTION: cursor(row={
            "transaction_id": tid,
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": Decimal("10.00"),
            "status": status,
        }),
        SAVED_REFUND: cursor(row=saved),
        BALANCES: cursor(rows=[
            {"account_id": from_id, "balance": Decimal("49990.00")},
            {"account_id": to_id, "balance": to_balance},
        ]),
        REFUNDED_SO_FAR: cursor(row={"total": refunded}),
        REFUND_RECORD: cursor(row={
            "refund_id": uuid4(),
            "transaction_id": tid,
            "amount": amount,
            "reason": "Test refund",
            "status": "processed",
            "created_at": NOW,
        }),
    }


# A partial refund is saved, and the transfer stays completed.
def test_partial_refund_keeps_transaction_completed():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    conn = connection(refund_answers(tid, from_id, to_id, amount=Decimal("4.00")))

    answer, created = RefundService(conn, uuid4()).refund(
        tid, uuid4(), RefundCreate(amount=Decimal("4.00"), reason="Test refund")
    )

    assert created is True
    assert answer["amount"] == "4.00"
    assert sql_calls(conn, FULL_REFUND_STATUS) == []


# Refunding the whole amount marks the transfer as refunded.
def test_full_refund_marks_transaction_refunded():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    conn = connection(refund_answers(tid, from_id, to_id, amount=Decimal("10.00")))

    RefundService(conn, uuid4()).refund(tid, uuid4(), RefundCreate(amount=Decimal("10.00"), reason="Full"))

    assert len(sql_calls(conn, FULL_REFUND_STATUS)) == 1


# A refund above what is left to refund is refused, and nothing is saved.
def test_refund_above_remaining_amount_is_refused():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    conn = connection(refund_answers(tid, from_id, to_id, amount=Decimal("7.00"), refunded=Decimal("4.00")))

    with pytest.raises(BadRequestError):
        RefundService(conn, uuid4()).refund(tid, uuid4(), RefundCreate(amount=Decimal("7.00"), reason="Too much"))
    assert sql_calls(conn, REFUND_RECORD) == []


# A retry with the same key and body returns the saved refund and records nothing new.
def test_retry_with_same_key_returns_saved_refund():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    body = RefundCreate(amount=Decimal("4.00"), reason="Test refund")
    digest = fingerprint(dict(body.model_dump(mode="json"), transaction_id=str(tid)))
    saved_body = {"refund_id": str(uuid4()), "transaction_id": str(tid), "amount": "4.00"}
    conn = connection(refund_answers(
        tid, from_id, to_id, amount=Decimal("4.00"),
        saved={"request_hash": digest, "response_body": saved_body},
    ))

    answer, created = RefundService(conn, uuid4()).refund(tid, uuid4(), body)

    assert created is False
    assert answer == saved_body
    assert sql_calls(conn, REFUND_RECORD) == []


# The same key with a different body is refused, because it is a different request.
def test_same_key_with_different_body_is_refused():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    other_body = RefundCreate(amount=Decimal("2.00"), reason="Other")
    other_digest = fingerprint(dict(other_body.model_dump(mode="json"), transaction_id=str(tid)))
    conn = connection(refund_answers(
        tid, from_id, to_id, amount=Decimal("4.00"),
        saved={"request_hash": other_digest, "response_body": {}},
    ))

    with pytest.raises(ConflictError):
        RefundService(conn, uuid4()).refund(tid, uuid4(), RefundCreate(amount=Decimal("4.00"), reason="Test refund"))


# A pending transfer cannot be refunded, and nothing is saved.
def test_pending_transaction_cannot_be_refunded():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    conn = connection(refund_answers(tid, from_id, to_id, amount=Decimal("1.00"), status="pending"))

    with pytest.raises(ConflictError):
        RefundService(conn, uuid4()).refund(tid, uuid4(), RefundCreate(amount=Decimal("1.00"), reason="Early"))
    assert sql_calls(conn, REFUND_RECORD) == []


# The receiver must have enough money to pay the refund back.
def test_receiver_must_have_enough_for_the_refund():
    tid, from_id, to_id = uuid4(), uuid4(), uuid4()
    conn = connection(refund_answers(tid, from_id, to_id, amount=Decimal("4.00"), to_balance=Decimal("0")))

    with pytest.raises(BadRequestError):
        RefundService(conn, uuid4()).refund(tid, uuid4(), RefundCreate(amount=Decimal("4.00"), reason="No funds"))
    assert sql_calls(conn, REFUND_RECORD) == []


# A transaction the client did not send, or one that does not exist, gives 404.
def test_transaction_the_client_did_not_send_is_not_found():
    conn = connection({SENT_TRANSACTION: cursor()})

    with pytest.raises(NotFoundError):
        RefundService(conn, uuid4()).refund(uuid4(), uuid4(), RefundCreate(amount=Decimal("1.00"), reason="Not mine"))
