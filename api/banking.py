"""The banking rules and the database queries behind them.

There is one class for each kind of transaction:
    TransferService      sends money
    CancellationService  cancels a pending transaction
    RefundService        pays money back
    TransactionService   reads, lists and edits transactions

Each method is one database transaction. main.py opens the connection. When
the request finishes, everything is saved together. If an error is raised,
everything is undone.
"""

import hashlib
import json

from psycopg.types.json import Jsonb

from schemas import CancellationResponse, RefundResponse


# ---------------------------------------------------------------------------
# Errors. Each one knows which HTTP status code to send back.
# ---------------------------------------------------------------------------

class BankingError(Exception):
    status_code = 500

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


class BadRequestError(BankingError):
    status_code = 400


class AuthenticationError(BankingError):
    status_code = 401


class ForbiddenError(BankingError):
    status_code = 403


class NotFoundError(BankingError):
    status_code = 404


class ConflictError(BankingError):
    status_code = 409


class PreconditionFailedError(BankingError):
    status_code = 412


class PreconditionRequiredError(BankingError):
    status_code = 428


class ServiceUnavailableError(BankingError):
    status_code = 503


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

# The columns we return for a transaction.
COLUMNS = (
    "transaction_id, from_account_id, to_account_id, amount, currency, "
    "description, status, created_at, updated_at, version"
)

# The accounts that belong to the client. Used inside the queries below.
MY_ACCOUNTS = "SELECT account_id FROM client_accounts WHERE client_id = %(client_id)s"

# Only these statuses can be refunded.
REFUNDABLE = ("completed", "refunded")


def hash_api_key(api_key):
    # The database stores this hash, never the key itself.
    return hashlib.sha256(api_key.encode()).hexdigest()


def find_client_id(conn, api_key):
    row = conn.execute(
        "SELECT client_id FROM api_clients WHERE key_hash = %s",
        (hash_api_key(api_key),),
    ).fetchone()
    if row is None:
        return None
    return row["client_id"]


def fingerprint(data):
    # The same data always gives the same text, so it always gives the same hash.
    text = json.dumps(data, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def same_name(first, second):
    # "  Ali Ahmed " and "ali ahmed" count as the same name.
    return first.strip().lower() == second.strip().lower()


def lock_request_key(conn, operation, key):
    # Another request with the same key waits here until this one is finished.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (operation + ":" + str(key),),
    )


def owns_account(conn, client_id, account_id):
    row = conn.execute(
        "SELECT 1 FROM client_accounts WHERE client_id = %s AND account_id = %s",
        (client_id, account_id),
    ).fetchone()
    return row is not None


def read_transaction(conn, transaction_id):
    return conn.execute(
        f"SELECT {COLUMNS} FROM transactions WHERE transaction_id = %s",
        (transaction_id,),
    ).fetchone()


def read_sent_transaction_for_update(conn, client_id, transaction_id):
    # Reads a transaction the client SENT and locks its row.
    # If it is missing or belongs to someone else, the result is None.
    # Both cases give the same 404, so nobody can tell which one it is.
    return conn.execute(
        f"""
        SELECT {COLUMNS}
        FROM transactions
        WHERE transaction_id = %(transaction_id)s
          AND from_account_id IN ({MY_ACCOUNTS})
        FOR UPDATE
        """,
        {"transaction_id": transaction_id, "client_id": client_id},
    ).fetchone()


def pick_one_account(rows, role):
    # There must be exactly one account with this name.
    if len(rows) == 0:
        raise NotFoundError(role + " account not found.")
    if len(rows) > 1:
        raise ConflictError(role + " account name is ambiguous.")
    return rows[0]


# ---------------------------------------------------------------------------
# Transaction classes
# ---------------------------------------------------------------------------

class TransferService:
    """Sends money from one of the client's accounts to another account."""

    def __init__(self, conn, client_id):
        self.conn = conn
        self.client_id = client_id

    def create(self, key, data):
        # Returns (transaction, created). created is False for a retry.
        if same_name(data.source, data.destination):
            raise BadRequestError("Source and destination accounts must be different.")

        lock_request_key(self.conn, "transfer", key)

        # If this key already made a transfer, this request is a retry.
        old = self.conn.execute(
            """
            SELECT k.transaction_id, t.from_account_id, t.amount, t.currency, t.description,
                   a.account_holder AS source_name,
                   b.account_holder AS destination_name
            FROM idempotency_keys k
            JOIN transactions t ON t.transaction_id = k.transaction_id
            JOIN accounts a ON a.account_id = t.from_account_id
            JOIN accounts b ON b.account_id = t.to_account_id
            WHERE k.idempotency_key = %s
            """,
            (key,),
        ).fetchone()
        if old is not None:
            same = (
                same_name(old["source_name"], data.source)
                and same_name(old["destination_name"], data.destination)
                and old["amount"] == data.amount
                and old["currency"].strip() == data.currency
                and old["description"] == data.description
            )
            # A different request, or someone else's transfer, gets the same 409.
            if not same or not owns_account(self.conn, self.client_id, old["from_account_id"]):
                raise ConflictError("This Idempotency-Key belongs to a different request.")
            return read_transaction(self.conn, old["transaction_id"]), False

        # Lock both accounts in one query, in ID order. Two transfers that lock
        # in the same order cannot wait on each other forever.
        rows = self.conn.execute(
            """
            SELECT account_id, account_holder, currency, balance
            FROM accounts
            WHERE LOWER(TRIM(account_holder)) IN (LOWER(%s), LOWER(%s))
            ORDER BY account_id
            FOR UPDATE
            """,
            (data.source, data.destination),
        ).fetchall()
        source = pick_one_account([r for r in rows if same_name(r["account_holder"], data.source)], "Source")
        destination = pick_one_account([r for r in rows if same_name(r["account_holder"], data.destination)], "Destination")

        # The client may only send from an account it owns.
        if not owns_account(self.conn, self.client_id, source["account_id"]):
            raise ForbiddenError("You can only send money from your own accounts.")

        if source["currency"].strip() != data.currency or destination["currency"].strip() != data.currency:
            raise BadRequestError("Currency must match both accounts.")
        if source["balance"] < data.amount:
            raise BadRequestError("Insufficient funds.")

        # Take the money from the sender and give it to the receiver.
        self.conn.execute(
            "UPDATE accounts SET balance = balance - %s WHERE account_id = %s",
            (data.amount, source["account_id"]),
        )
        self.conn.execute(
            "UPDATE accounts SET balance = balance + %s WHERE account_id = %s",
            (data.amount, destination["account_id"]),
        )

        new = self.conn.execute(
            f"""
            INSERT INTO transactions
                (from_account_id, to_account_id, amount, currency, description, status)
            VALUES (%s, %s, %s, %s, %s, 'completed')
            RETURNING {COLUMNS}
            """,
            (source["account_id"], destination["account_id"], data.amount, data.currency, data.description),
        ).fetchone()

        # Remember which transaction this key made, so a retry can find it.
        self.conn.execute(
            "INSERT INTO idempotency_keys (idempotency_key, transaction_id) VALUES (%s, %s)",
            (key, new["transaction_id"]),
        )
        return new, True


class CancellationService:
    """Cancels a pending transaction that the client sent."""

    def __init__(self, conn, client_id):
        self.conn = conn
        self.client_id = client_id

    def cancel(self, transaction_id, key, data):
        # Returns (answer, created). created is False for a retry.
        digest = fingerprint({"transaction_id": str(transaction_id), "reason": data.reason})
        lock_request_key(self.conn, "cancel", key)

        transaction = read_sent_transaction_for_update(self.conn, self.client_id, transaction_id)
        if transaction is None:
            raise NotFoundError("Transaction not found")

        # A retry with the same key gets the saved answer again.
        saved = self.conn.execute(
            """
            SELECT request_hash, response_body
            FROM operation_idempotency
            WHERE operation = 'cancel' AND idempotency_key = %s
            """,
            (key,),
        ).fetchone()
        if saved is not None:
            if saved["request_hash"] != digest:
                raise ConflictError("This Idempotency-Key was used with a different request.")
            return saved["response_body"], False

        if transaction["status"] != "pending":
            raise ConflictError("Only pending transactions can be cancelled.")

        self.conn.execute(
            "INSERT INTO cancellations (transaction_id, reason, status) VALUES (%s, %s, 'completed')",
            (transaction_id, data.reason),
        )
        row = self.conn.execute(
            """
            UPDATE transactions
            SET status = 'cancelled', version = version + 1, updated_at = NOW()
            WHERE transaction_id = %s
            RETURNING transaction_id, status, version, updated_at
            """,
            (transaction_id,),
        ).fetchone()

        body = CancellationResponse.model_validate(row).model_dump(mode="json")
        self.conn.execute(
            """
            INSERT INTO operation_idempotency
                (operation, idempotency_key, request_hash, response_body)
            VALUES ('cancel', %s, %s, %s)
            """,
            (key, digest, Jsonb(body)),
        )
        return body, True


class RefundService:
    """Pays back all or part of a transaction that the client sent."""

    def __init__(self, conn, client_id):
        self.conn = conn
        self.client_id = client_id

    def refund(self, transaction_id, key, data):
        # Returns (answer, created). created is False for a retry.
        digest = fingerprint(dict(data.model_dump(mode="json"), transaction_id=str(transaction_id)))
        lock_request_key(self.conn, "refund", key)

        transaction = read_sent_transaction_for_update(self.conn, self.client_id, transaction_id)
        if transaction is None:
            raise NotFoundError("Transaction not found")

        saved = self.conn.execute(
            """
            SELECT request_hash, response_body
            FROM operation_idempotency
            WHERE operation = 'refund' AND idempotency_key = %s
            """,
            (key,),
        ).fetchone()
        if saved is not None:
            if saved["request_hash"] != digest:
                raise ConflictError("This Idempotency-Key was used with a different request.")
            return saved["response_body"], False

        if transaction["status"] not in REFUNDABLE:
            raise ConflictError("Only completed transactions can be refunded.")

        from_id = transaction["from_account_id"]
        to_id = transaction["to_account_id"]

        # Lock both accounts, in ID order.
        rows = self.conn.execute(
            "SELECT account_id, balance FROM accounts WHERE account_id IN (%s, %s) ORDER BY account_id FOR UPDATE",
            (from_id, to_id),
        ).fetchall()
        balances = {row["account_id"]: row["balance"] for row in rows}

        # How much is left to refund = the original amount minus what was already refunded.
        already_refunded = self.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM refunds
            WHERE transaction_id = %s AND status = 'processed'
            """,
            (transaction_id,),
        ).fetchone()["total"]
        remaining = transaction["amount"] - already_refunded

        if data.amount > remaining:
            raise BadRequestError(f"Refund exceeds the remaining amount: {remaining}.")
        if balances[to_id] < data.amount:
            raise BadRequestError("Receiving account has insufficient funds for this refund.")

        # The money goes back: from the receiver to the original sender.
        self.conn.execute(
            "UPDATE accounts SET balance = balance - %s WHERE account_id = %s",
            (data.amount, to_id),
        )
        self.conn.execute(
            "UPDATE accounts SET balance = balance + %s WHERE account_id = %s",
            (data.amount, from_id),
        )

        row = self.conn.execute(
            """
            INSERT INTO refunds (transaction_id, amount, reason, status)
            VALUES (%s, %s, %s, 'processed')
            RETURNING refund_id, transaction_id, amount, reason, status, created_at
            """,
            (transaction_id, data.amount, data.reason),
        ).fetchone()

        # Only mark the transaction as refunded when everything has been paid back.
        if data.amount == remaining:
            self.conn.execute(
                """
                UPDATE transactions
                SET status = 'refunded', version = version + 1, updated_at = NOW()
                WHERE transaction_id = %s
                """,
                (transaction_id,),
            )

        body = RefundResponse.model_validate(row).model_dump(mode="json")
        self.conn.execute(
            """
            INSERT INTO operation_idempotency
                (operation, idempotency_key, request_hash, response_body)
            VALUES ('refund', %s, %s, %s)
            """,
            (key, digest, Jsonb(body)),
        )
        return body, True


class TransactionService:
    """Reads, lists and edits the client's transactions."""

    def __init__(self, conn, client_id):
        self.conn = conn
        self.client_id = client_id

    def get(self, transaction_id):
        # Only transactions the client is part of (sender or receiver).
        row = self.conn.execute(
            f"""
            SELECT {COLUMNS}
            FROM transactions
            WHERE transaction_id = %(transaction_id)s
              AND (from_account_id IN ({MY_ACCOUNTS}) OR to_account_id IN ({MY_ACCOUNTS}))
            """,
            {"transaction_id": transaction_id, "client_id": self.client_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Transaction not found")
        return row

    def list_all(self, status, from_date, to_date, limit, offset):
        if from_date and to_date and from_date > to_date:
            raise BadRequestError("from_date must precede to_date.")

        # Start with the client's transactions, then add each filter that was given.
        sql = (
            f"SELECT {COLUMNS} FROM transactions "
            f"WHERE (from_account_id IN ({MY_ACCOUNTS}) OR to_account_id IN ({MY_ACCOUNTS}))"
        )
        params = {"client_id": self.client_id, "limit": limit, "offset": offset}
        if status is not None:
            sql += " AND status = %(status)s"
            params["status"] = status.value
        if from_date is not None:
            sql += " AND created_at >= %(from_date)s"
            params["from_date"] = from_date
        if to_date is not None:
            sql += " AND created_at <= %(to_date)s"
            params["to_date"] = to_date

        # Newest first. LIMIT and OFFSET cut out one page.
        sql += " ORDER BY created_at DESC, transaction_id LIMIT %(limit)s OFFSET %(offset)s"
        return self.conn.execute(sql, params).fetchall()

    def update_description(self, transaction_id, description, expected_version):
        # The change only happens if the version still matches (optimistic locking).
        row = self.conn.execute(
            f"""
            UPDATE transactions
            SET description = %(description)s, version = version + 1, updated_at = NOW()
            WHERE transaction_id = %(transaction_id)s
              AND version = %(expected_version)s
              AND from_account_id IN ({MY_ACCOUNTS})
            RETURNING {COLUMNS}
            """,
            {
                "description": description,
                "transaction_id": transaction_id,
                "expected_version": expected_version,
                "client_id": self.client_id,
            },
        ).fetchone()
        if row is not None:
            return row

        # Nothing changed. Either the transaction is not the client's (404),
        # or the version is out of date (412).
        current = self.conn.execute(
            f"""
            SELECT version FROM transactions
            WHERE transaction_id = %(transaction_id)s
              AND from_account_id IN ({MY_ACCOUNTS})
            """,
            {"transaction_id": transaction_id, "client_id": self.client_id},
        ).fetchone()
        if current is None:
            raise NotFoundError("Transaction not found")
        raise PreconditionFailedError(f"Version mismatch. Current version: {current['version']}.")
