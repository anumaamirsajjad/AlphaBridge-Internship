"""Authorization tests: who may see and change which transactions.

What this file does:
    Checks the API-key rules. Without a valid key nothing works. A client may
    only send from its own accounts, and may only see or change transactions it
    is part of. Anything else must fail WITHOUT moving money.
"""

from decimal import Decimal
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from banking import hash_api_key
from conftest import (
    OTHER_API_KEY,
    TEST_API_KEY,
    balance_of,
    insert_pending_transaction,
    transaction_count,
    transfer_body,
    with_key,
)

TRANSACTIONS = "/version1/transactions"
ALI_START = Decimal("50000.00")


# Adds a PKR account named "Outsider". By default the test client does not own it.
# Pass owner_key to link it to another client.
def add_outsider_account(db: psycopg.Connection, owner_key: str | None = None) -> None:
    account_id = db.execute(
        "INSERT INTO accounts (account_holder, currency, balance) VALUES ('Outsider', 'PKR', 0.00) RETURNING account_id"
    ).fetchone()[0]
    if owner_key is not None:
        db.execute(
            """
            INSERT INTO client_accounts (client_id, account_id)
            SELECT client_id, %s FROM api_clients WHERE key_hash = %s
            """,
            (account_id, hash_api_key(owner_key)),
        )


# --- The API key itself -------------------------------------------------------

# The health check needs no key, so Docker can check the service.
def test_health_is_open_without_key(client: TestClient):
    response = client.get("/version1/health", headers={"X-API-Key": ""})

    assert response.status_code == 200


# A request with no key is rejected with 401.
def test_request_without_key_is_rejected(client: TestClient):
    response = client.get(TRANSACTIONS, headers={"X-API-Key": ""})

    assert response.status_code == 401


# A key that does not belong to any client is rejected with 401.
def test_unknown_key_is_rejected(client: TestClient):
    response = client.get(TRANSACTIONS, headers={"X-API-Key": "not-a-real-key"})

    assert response.status_code == 401


# Without a key, a transfer is refused and moves no money.
def test_transfer_without_key_moves_no_money(client: TestClient, db: psycopg.Connection):
    response = client.post(TRANSACTIONS, json=transfer_body(), headers={"X-API-Key": "", **with_key(uuid4())})

    assert response.status_code == 401
    assert balance_of(db, "Ali Ahmed") == ALI_START
    assert transaction_count(db) == 0


# The database keeps only a hash of the key, never the key itself.
def test_api_key_is_stored_as_hash_only(db: psycopg.Connection):
    key_hash = db.execute(
        "SELECT key_hash FROM api_clients WHERE name = 'Test client'"
    ).fetchone()[0]

    assert key_hash == hash_api_key(TEST_API_KEY)
    assert TEST_API_KEY not in key_hash


# --- Sending money ------------------------------------------------------------

# A client cannot send money from an account it does not own.
def test_cannot_send_from_someone_elses_account(client: TestClient, db: psycopg.Connection):
    response = client.post(
        TRANSACTIONS,
        json=transfer_body(source="Bilal", destination="Maham"),
        headers=with_key(uuid4()),
    )

    assert response.status_code == 403
    assert transaction_count(db) == 0
    assert balance_of(db, "Ali Ahmed") == ALI_START


# A client may pay into an account it does not own (paying someone else is allowed).
def test_can_send_to_someone_elses_account(client: TestClient, db: psycopg.Connection):
    add_outsider_account(db)

    response = client.post(
        TRANSACTIONS,
        json=transfer_body(source="Ali Ahmed", destination="Outsider"),
        headers=with_key(uuid4()),
    )

    assert response.status_code == 201


# Replaying another client's transfer key must not reveal that transfer.
def test_replaying_someone_elses_key_is_rejected(
    client: TestClient, other_client: TestClient, db: psycopg.Connection
):
    key = uuid4()
    first = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(key))
    assert first.status_code == 201

    response = other_client.post(
        TRANSACTIONS,
        json=transfer_body(source="Ali Ahmed", destination="Maham"),
        headers=with_key(key),
    )

    assert response.status_code == 409
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("1")
    assert transaction_count(db) == 1


# --- Reading transactions -----------------------------------------------------

# A client cannot read a transaction it is not part of. The reply is 404, not 403,
# so it does not reveal that the transaction exists.
def test_other_client_cannot_read_transaction(client: TestClient, other_client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()

    response = other_client.get(f"{TRANSACTIONS}/{created['transaction_id']}")

    assert response.status_code == 404


# A receiver can read a transaction paid into one of its accounts.
def test_receiver_can_read_incoming_transaction(client: TestClient, other_client: TestClient, db: psycopg.Connection):
    add_outsider_account(db, owner_key=OTHER_API_KEY)
    created = client.post(
        TRANSACTIONS,
        json=transfer_body(source="Ali Ahmed", destination="Outsider"),
        headers=with_key(uuid4()),
    ).json()

    response = other_client.get(f"{TRANSACTIONS}/{created['transaction_id']}")

    assert response.status_code == 200
    assert response.json()["transaction_id"] == created["transaction_id"]


# A list shows only the client's own transactions.
def test_list_shows_only_own_transactions(client: TestClient, other_client: TestClient):
    client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4()))

    mine = client.get(TRANSACTIONS).json()
    theirs = other_client.get(TRANSACTIONS).json()

    assert len(mine["items"]) == 1
    assert theirs["items"] == []


# --- Changing transactions ----------------------------------------------------

# Only the sender's client may cancel. Another client gets 404 and the
# transaction stays pending. The sender can still cancel it.
def test_other_client_cannot_cancel(
    client: TestClient, other_client: TestClient, db: psycopg.Connection, accounts: dict
):
    transaction_id = insert_pending_transaction(db, accounts)

    blocked = other_client.post(f"{TRANSACTIONS}/{transaction_id}/cancellation", headers=with_key(uuid4()))
    allowed = client.post(f"{TRANSACTIONS}/{transaction_id}/cancellation", headers=with_key(uuid4()))

    assert blocked.status_code == 404
    assert allowed.status_code == 201


# Only the sender's client may refund.
def test_other_client_cannot_refund(client: TestClient, other_client: TestClient, db: psycopg.Connection):
    created = client.post(TRANSACTIONS, json=transfer_body(amount="100"), headers=with_key(uuid4())).json()

    response = other_client.post(
        f"{TRANSACTIONS}/{created['transaction_id']}/refunds",
        json={"amount": "100.00", "reason": "Not mine"},
        headers=with_key(uuid4()),
    )

    assert response.status_code == 404
    assert balance_of(db, "Ali Ahmed") == ALI_START - Decimal("100.00")


# Only the sender's client may edit the description.
def test_other_client_cannot_edit_description(client: TestClient, other_client: TestClient):
    created = client.post(TRANSACTIONS, json=transfer_body(), headers=with_key(uuid4())).json()
    url = f"{TRANSACTIONS}/{created['transaction_id']}"

    response = other_client.patch(url, json={"description": "Hijacked"}, headers={"If-Match": "1"})

    assert response.status_code == 404
    assert client.get(url).json()["description"] == "Test transfer"
