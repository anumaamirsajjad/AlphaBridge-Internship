"""Behaviour tests for the transaction endpoints (with the test client's key).

What this file does:
    Tests the API the way a client would use it. Each test sends HTTP requests
    and checks the response. For anything that moves money, it also checks the
    account balances and the transactions table in the database.
    Authorization rules (who may do what) are tested in test_auth.py.
"""

from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from conftest import balance_of, insert_pending_transaction, transaction_count, transfer_body, with_key

TRANSACTIONS = "/version1/transactions"
ALI_START = Decimal("50000.00")
MAHAM_START = Decimal("20000.00")


# --- Health and reads ---------------------------------------------------------

# The health endpoint says the database is connected.
def test_health_reports_database_connected(client: TestClient):
    response = client.get("/version1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}


# Asking for a transaction that does not exist gives 404.
def test_unknown_transaction_returns_404(client: TestClient):
    response = client.get(f"{TRANSACTIONS}/{uuid4()}")

    assert response.status_code == 404


# The status filter returns only matching transactions.
def test_list_filters_by_status(client: TestClient):
    client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4()))

    completed = client.get(TRANSACTIONS, params={"status": "completed"}).json()
    cancelled = client.get(TRANSACTIONS, params={"status": "cancelled"}).json()

    assert len(completed["items"]) == 1
    assert cancelled["items"] == []


# --- Transfers: success -------------------------------------------------------

# A valid transfer changes balances and saves a row.
def test_transfer_moves_money_and_records_transaction(client: TestClient, db: psycopg.Connection):
    response = client.post(TRANSACTIONS, json=transfer_body(amount="25.50"), headers=with_key(uuid4()))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert Decimal(body["amount"]) == Decimal("25.50")
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("25.50")
    assert balance_of(db, "Maham") == MAHAM_START + Decimal("25.50")
    assert transaction_count(db) == 1


# Sending the same request twice moves money only once.
def test_identical_retry_returns_original_without_moving_money(client: TestClient, db: psycopg.Connection):
    key = uuid4()

    first = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(key))
    retry = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(key))

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["transaction_id"] == first.json()["transaction_id"]
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("1")
    assert balance_of(db, "Maham") == MAHAM_START + Decimal("1")
    assert transaction_count(db) == 1


# Same key but a different description gives 409.
def test_same_key_with_changed_description_is_rejected(client: TestClient, db: psycopg.Connection):
    key = uuid4()
    client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(key))

    response = client.post(
        TRANSACTIONS, json=transfer_body(description="Different text"), headers=with_key(key)
    )

    assert response.status_code == 409
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("1")
    assert transaction_count(db) == 1


# Same key but a different amount gives 409.
def test_same_key_with_changed_amount_is_rejected(client: TestClient, db: psycopg.Connection):
    key = uuid4()
    client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(key))

    response = client.post(TRANSACTIONS, json=transfer_body(amount="2"), headers=with_key(key))

    assert response.status_code == 409
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("1")
    assert transaction_count(db) == 1


# --- Transfers: rejected requests leave balances unchanged --------------------

# No key header gives 400.
def test_missing_idempotency_key_is_rejected(client: TestClient, db: psycopg.Connection):
    response = client.post(TRANSACTIONS, json=transfer_body())

    assert response.status_code == 400
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# A key that is not a UUID gives 400.
def test_malformed_idempotency_key_is_rejected(client: TestClient, db: psycopg.Connection):
    response = client.post(TRANSACTIONS, json=transfer_body(), headers={"Idempotency-Key": "not-a-uuid"})

    assert response.status_code == 400
    assert transaction_count(db) == 0


# Each invalid body must give 422 and change nothing.
@pytest.mark.parametrize(
    "bad_body",
    [
        # Zero is not allowed.
        {"amount": "0"},
        # Negative is not allowed.
        {"amount": "-5"},
        # More than 2 decimal places.
        {"amount": "1.001"},
        # Not a number.
        {"amount": "abc"},
        # Lowercase currency.
        {"currency": "pkr"},
        # Four letters instead of three.
        {"currency": "PKRS"},
        # Only spaces, which become empty.
        {"source": "   "},
        # Empty description.
        {"description": ""},
        # A field that is not in the model.
        {"unknown_field": "x"},
    ],
    ids=[
        "zero-amount", "negative-amount", "too-many-decimals", "non-numeric-amount",
        "lowercase-currency", "four-letter-currency", "blank-source", "empty-description",
        "unknown-field",
    ],
)
def test_invalid_payload_is_rejected_without_moving_money(
    client: TestClient, db: psycopg.Connection, bad_body: dict
):
    response = client.post(TRANSACTIONS, json=transfer_body(**bad_body), headers=with_key(uuid4()))

    assert response.status_code == 422
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# Leaving out a required field gives 422.
def test_missing_field_is_rejected(client: TestClient, db: psycopg.Connection):
    body = transfer_body()
    del body["destination"]

    response = client.post(TRANSACTIONS, json=body, headers=with_key(uuid4()))

    assert response.status_code == 422
    assert transaction_count(db) == 0


# Same account on both sides gives 400, even with different spacing and case.
def test_same_source_and_destination_is_rejected(client: TestClient, db: psycopg.Connection):
    response = client.post(
        TRANSACTIONS, json=transfer_body(destination="  ali AHMED "), headers=with_key(uuid4())
    )

    assert response.status_code == 400
    assert transaction_count(db) == 0


# A name with no account gives 404.
def test_unknown_account_returns_404(client: TestClient, db: psycopg.Connection):
    response = client.post(TRANSACTIONS, json=transfer_body(destination="Nobody"), headers=with_key(uuid4()))

    assert response.status_code == 404
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# Sending more than the balance gives 400.
def test_insufficient_funds_is_rejected(client: TestClient, db: psycopg.Connection):
    response = client.post(
        TRANSACTIONS, json=transfer_body(amount="50000.01"), headers=with_key(uuid4())
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient funds."
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert balance_of(db, "Maham") == MAHAM_START
    assert transaction_count(db) == 0


# Sending exactly the whole balance is allowed.
def test_transfer_of_exact_balance_succeeds(client: TestClient, db: psycopg.Connection):
    response = client.post(
        TRANSACTIONS, json=transfer_body(amount="50000.00"), headers=with_key(uuid4())
    )

    assert response.status_code == 201
    assert balance_of(db, "Ali Ahmed") == Decimal("0.00")


# Sending PKR to a USD account gives 400.
def test_currency_mismatch_is_rejected(client: TestClient, db: psycopg.Connection):
    response = client.post(
        TRANSACTIONS, json=transfer_body(destination="Bilal"), headers=with_key(uuid4())
    )

    assert response.status_code == 400
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# Two accounts with the same name gives 409.
def test_ambiguous_account_name_returns_409(client: TestClient, db: psycopg.Connection):
    db.execute("INSERT INTO accounts (account_holder, currency, balance) VALUES ('Maham', 'PKR', 5.00)")

    response = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4()))

    assert response.status_code == 409
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# --- Cancellation -------------------------------------------------------------

# Cancel a pending transaction, then retry with the same key.
def test_cancel_pending_transaction_then_replay(client: TestClient, db: psycopg.Connection, accounts: dict):
    transaction_id = insert_pending_transaction(db, accounts)
    key = uuid4()

    first = client.post(f"{TRANSACTIONS}/{transaction_id}/cancellation", headers=with_key(key))
    retry = client.post(f"{TRANSACTIONS}/{transaction_id}/cancellation", headers=with_key(key))

    assert first.status_code == 201
    assert first.json()["status"] == "cancelled"
    assert first.json()["version"] == 2
    assert retry.status_code == 200
    assert retry.json() == first.json()


# Only pending transactions can be cancelled. A completed one gives 409.
def test_completed_transaction_cannot_be_cancelled(client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()

    response = client.post(
        f"{TRANSACTIONS}/{created['transaction_id']}/cancellation", headers=with_key(uuid4())
    )

    assert response.status_code == 409


# Cancelling a missing transaction gives 404.
def test_cancel_unknown_transaction_returns_404(client: TestClient):
    response = client.post(f"{TRANSACTIONS}/{uuid4()}/cancellation", headers=with_key(uuid4()))

    assert response.status_code == 404


# --- Refunds ------------------------------------------------------------------

# Refunding everything puts the money back and sets status to refunded.
def test_full_refund_restores_balances_and_marks_refunded(client: TestClient, db: psycopg.Connection):
    created = client.post(TRANSACTIONS, json=transfer_body(amount="100"), headers=with_key(uuid4())).json()
    refund_body = {"amount": "100.00", "reason": "Customer request"}

    response = client.post(
        f"{TRANSACTIONS}/{created['transaction_id']}/refunds", json=refund_body, headers=with_key(uuid4())
    )

    assert response.status_code == 201
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert balance_of(db, "Maham") == MAHAM_START
    status = client.get(f"{TRANSACTIONS}/{created['transaction_id']}").json()["status"]
    assert status == "refunded"


# Retrying a partial refund returns the same answer without refunding twice.
def test_refund_retry_with_same_key_returns_original(client: TestClient, db: psycopg.Connection):
    created = client.post(TRANSACTIONS, json=transfer_body(amount="100"), headers=with_key(uuid4())).json()
    key = uuid4()
    url = f"{TRANSACTIONS}/{created['transaction_id']}/refunds"
    body = {"amount": "40.00", "reason": "Partial refund"}

    first = client.post(url, json=body, headers=with_key(key))
    retry = client.post(url, json=body, headers=with_key(key))

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == first.json()
    # 100 sent, 40 back = 60 lost. Only one refund happened.
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("60.00")


# Refunding more than was sent gives 400.
def test_refund_exceeding_remaining_amount_is_rejected(client: TestClient, db: psycopg.Connection):
    created = client.post(TRANSACTIONS, json=transfer_body(amount="100"), headers=with_key(uuid4())).json()

    response = client.post(
        f"{TRANSACTIONS}/{created['transaction_id']}/refunds",
        json={"amount": "150.00", "reason": "Too much"},
        headers=with_key(uuid4()),
    )

    assert response.status_code == 400
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("100.00")


# --- Optimistic locking (PATCH) -----------------------------------------------

# PATCH without the If-Match header gives 428.
def test_patch_without_if_match_returns_428(client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()

    response = client.patch(
        f"{TRANSACTIONS}/{created['transaction_id']}", json={"description": "Edited"}
    )

    assert response.status_code == 428


# PATCH with the right version works and bumps the version.
def test_patch_with_current_version_updates_description(client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()

    response = client.patch(
        f"{TRANSACTIONS}/{created['transaction_id']}",
        json={"description": "Edited"},
        headers={"If-Match": '"1"'},
    )

    assert response.status_code == 200
    assert response.json()["description"] == "Edited"
    assert response.json()["version"] == 2


# Using an old version after a change gives 412.
def test_patch_with_stale_version_returns_412(client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()
    url = f"{TRANSACTIONS}/{created['transaction_id']}"
    client.patch(url, json={"description": "First edit"}, headers={"If-Match": "1"})

    response = client.patch(url, json={"description": "Stale edit"}, headers={"If-Match": "1"})

    assert response.status_code == 412


# An If-Match value that is not a number gives 400.
def test_patch_with_non_numeric_if_match_returns_400(client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()

    response = client.patch(
        f"{TRANSACTIONS}/{created['transaction_id']}",
        json={"description": "Edited"},
        headers={"If-Match": "abc"},
    )

    assert response.status_code == 400
