"""Unit tests for CancellationService, using a mock database connection.

What this file does:
    Runs CancellationService.cancel against a fake connection with scripted
    answers, then checks the returned answer and the SQL the service ran.

How cancel() works, so the tests make sense:
    1. It fingerprints the request (transaction ID + reason) so a retry can be compared.
    2. It locks the request key, so two requests with the same key cannot run at once.
    3. It reads the transaction, but only if the client sent it. Otherwise it returns nothing.
    4. It looks for a saved answer under this key. If one exists, it returns that answer
       (or refuses with 409 if the fingerprint differs).
    5. It refuses cancellation unless the transaction is 'pending'.
    6. It records the reason, marks the transaction cancelled, and saves the answer.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from business.banking import CancellationService, ConflictError, NotFoundError, fingerprint
from fake_database import connection, cursor, sql_calls
from validation.schemas import CancellationCreate

# A fixed timestamp, so the fake database rows are the same on every run.
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)

# Matches the query that reads the transaction, but only when the client sent it.
# The fake connection returns the transaction row when this text appears in the SQL.
SENT_TRANSACTION = "AND from_account_id IN"

# Matches the query that looks for a saved answer under this cancel key.
SAVED_CANCEL = "WHERE operation = 'cancel'"

# Matches the query that marks the transaction cancelled and returns its new state.
CANCEL_UPDATE = "RETURNING transaction_id, status, version, updated_at"

# Matches the query that records the cancellation reason.
CANCEL_RECORD = "INSERT INTO cancellations"


# Cancelling a pending transaction marks it cancelled and records the reason.
def test_cancel_pending_marks_cancelled_and_records_reason():
    tid = uuid4()

    # Set up the fake database answers:
    # - the transaction exists, belongs to the client, and is pending
    # - the cancel update returns the new state: cancelled, version 2
    conn = connection({
        SENT_TRANSACTION: cursor(row={"transaction_id": tid, "status": "pending"}),
        CANCEL_UPDATE: cursor(row={"transaction_id": tid, "status": "cancelled", "version": 2, "updated_at": NOW}),
    })

    # Run the service with a new random key. The second uuid4() is the client's key.
    answer, created = CancellationService(conn, uuid4()).cancel(tid, uuid4(), CancellationCreate())

    # created is True because this was a new cancellation, not a retry.
    assert created is True
    # The answer shows the new state returned by the database.
    assert answer["status"] == "cancelled"
    # The version went from 1 to 2, because every change raises it by one.
    assert answer["version"] == 2
    # The reason is recorded. CancellationCreate() gives the default reason.
    # sql_calls returns (sql, params) pairs, so [0][1] is the params of the first match.
    assert sql_calls(conn, CANCEL_RECORD)[0][1] == (tid, "Cancelled by requester")


# A retry with the same key and reason returns the saved answer and records nothing new.
def test_retry_with_same_key_returns_saved_answer():
    tid = uuid4()

    # The fingerprint the first request would have saved: transaction ID plus reason.
    digest = fingerprint({"transaction_id": str(tid), "reason": "Cancelled by requester"})

    # The answer the first request returned, which the database saved.
    saved_body = {"transaction_id": str(tid), "status": "cancelled", "version": 2, "updated_at": NOW.isoformat()}

    # The transaction now shows as cancelled, because the first request already cancelled it.
    # The saved answer exists under this key, with the same fingerprint.
    conn = connection({
        SENT_TRANSACTION: cursor(row={"transaction_id": tid, "status": "cancelled"}),
        SAVED_CANCEL: cursor(row={"request_hash": digest, "response_body": saved_body}),
    })

    answer, created = CancellationService(conn, uuid4()).cancel(tid, uuid4(), CancellationCreate())

    # created is False, because the service returned the old answer instead of cancelling again.
    assert created is False
    # The returned answer is exactly the one saved earlier.
    assert answer == saved_body
    # Nothing was written to the cancellations table.
    assert sql_calls(conn, CANCEL_RECORD) == []


# The same key with a different reason is refused, because it is a different request.
def test_same_key_with_different_reason_is_refused():
    tid = uuid4()

    # The fingerprint of the first request, which used the reason "First reason".
    first_digest = fingerprint({"transaction_id": str(tid), "reason": "First reason"})

    # The saved answer exists under this key, but its fingerprint is for "First reason".
    conn = connection({
        SENT_TRANSACTION: cursor(row={"transaction_id": tid, "status": "pending"}),
        SAVED_CANCEL: cursor(row={"request_hash": first_digest, "response_body": {}}),
    })

    # The new request uses "Other reason", so its fingerprint differs. The service refuses with 409.
    with pytest.raises(ConflictError):
        CancellationService(conn, uuid4()).cancel(tid, uuid4(), CancellationCreate(reason="Other reason"))


# A completed transfer cannot be cancelled, and nothing is recorded.
def test_completed_transfer_cannot_be_cancelled():
    tid = uuid4()

    # The transaction exists and belongs to the client, but its status is 'completed'.
    # No saved answer exists under this key, so the service reaches the status check.
    conn = connection({SENT_TRANSACTION: cursor(row={"transaction_id": tid, "status": "completed"})})

    # Only pending transactions can be cancelled, so the service refuses with 409.
    with pytest.raises(ConflictError):
        CancellationService(conn, uuid4()).cancel(tid, uuid4(), CancellationCreate())

    # Nothing was written to the cancellations table.
    assert sql_calls(conn, CANCEL_RECORD) == []


# A transaction the client did not send, or one that does not exist, gives 404.
def test_transaction_the_client_did_not_send_is_not_found():
    # The fake query returns no row. This is what the real query does when the transaction
    # is missing or belongs to someone else. The two cases look the same to the client.
    conn = connection({SENT_TRANSACTION: cursor()})

    # The service turns the missing row into a 404 with the message "Transaction not found".
    with pytest.raises(NotFoundError):
        CancellationService(conn, uuid4()).cancel(uuid4(), uuid4(), CancellationCreate())
