"""Fill the database with fake bank data for testing.

What this file does:
    Creates the tables if they are missing, then adds fake accounts, transfers,
    pending and cancelled transfers, and refunds. Balances follow the same rules
    as the API, so no account goes negative. It also creates one demo API client
    that can use the first 20 accounts, and prints its API key once.

    It refuses to run if the accounts table already has rows.

Run it inside the VPC, because the database is private. Use the seed image
(see api/Dockerfile.seed). Locally, from the api folder:
    SCHEMA_DIR=../init DATABASE_URL="..." python -m seed.seed_faker
"""

import os
import random
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker

from business.banking import hash_api_key
from data.database import connect

ACCOUNT_COUNT = 200
COMPLETED_COUNT = 5000
PENDING_COUNT = 300
CANCELLED_COUNT = 100
REFUND_COUNT = 150
DEMO_CLIENT_ACCOUNTS = 20
CURRENCIES = ["USD", "PKR"]
HISTORY_DAYS = 90

# Where the schema files are. The seed image copies them to /init.
SCHEMA_DIR = Path(os.getenv("SCHEMA_DIR", "/init"))


# Creates the tables from init/*.sql, in order, but only if they are missing.
def apply_schema(conn):
    if conn.execute("SELECT to_regclass('public.accounts') AS t").fetchone()["t"] is not None:
        return
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
    print(f"Created tables from {SCHEMA_DIR}")


# A random amount with two decimal places, between low and high.
def random_amount(low, high):
    return Decimal(str(round(random.uniform(low, high), 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Two different accounts in the same currency, so the transfer is valid.
def pick_pair(by_currency):
    currency = random.choice(list(by_currency))
    source, destination = random.sample(by_currency[currency], 2)
    return source, destination


def make_accounts(fake, now):
    accounts = []
    for _ in range(ACCOUNT_COUNT):
        accounts.append({
            "id": uuid.uuid4(),
            "holder": fake.unique.name()[:100],
            "currency": random.choice(CURRENCIES),
            "balance": random_amount(1000, 50000),
            # Accounts are opened before the history starts, so no transfer predates its account.
            "created_at": now - timedelta(days=HISTORY_DAYS + random.uniform(1, 30)),
        })
    return accounts


# Completed transfers move money now, in time order, so balances never go negative.
def make_completed(by_currency, now):
    start = now - timedelta(days=HISTORY_DAYS)
    seconds = sorted(random.uniform(0, (now - start).total_seconds()) for _ in range(COMPLETED_COUNT))
    rows = []
    for offset in seconds:
        source, destination = pick_pair(by_currency)
        if source["balance"] <= 0:
            continue
        amount = min(random_amount(1, 500), source["balance"])
        source["balance"] -= amount
        destination["balance"] += amount
        created = start + timedelta(seconds=offset)
        rows.append({
            "id": uuid.uuid4(),
            "from": source["id"],
            "to": destination["id"],
            "amount": amount,
            "currency": source["currency"],
            "status": "completed",
            "created_at": created,
            "updated_at": created,
        })
    return rows


# Pending and cancelled transfers never move money, matching the API.
def make_open_transfers(by_currency, now, count, status):
    rows = []
    for _ in range(count):
        source, destination = pick_pair(by_currency)
        created = now - timedelta(seconds=random.uniform(0, 7 * 24 * 3600))
        rows.append({
            "id": uuid.uuid4(),
            "from": source["id"],
            "to": destination["id"],
            "amount": random_amount(1, 500),
            "currency": source["currency"],
            "status": status,
            "created_at": created,
            "updated_at": created,
        })
    return rows


# Refunds move money back from the receiver to the sender, and mark the transfer refunded.
def make_refunds(fake, completed, accounts_by_id, now):
    refunds = []
    for tx in random.sample(completed, min(REFUND_COUNT, len(completed))):
        receiver = accounts_by_id[tx["to"]]
        sender = accounts_by_id[tx["from"]]
        if receiver["balance"] < tx["amount"]:
            continue
        receiver["balance"] -= tx["amount"]
        sender["balance"] += tx["amount"]
        refunded_at = min(tx["created_at"] + timedelta(hours=random.uniform(1, 48)), now)
        tx["status"] = "refunded"
        tx["updated_at"] = refunded_at
        refunds.append({
            "id": uuid.uuid4(),
            "transaction_id": tx["id"],
            "amount": tx["amount"],
            "reason": fake.sentence(nb_words=5)[:255],
            "created_at": refunded_at,
        })
    return refunds


def make_cancellations(cancelled, now):
    rows = []
    for tx in cancelled:
        rows.append({
            "id": uuid.uuid4(),
            "transaction_id": tx["id"],
            "reason": "Cancelled by requester",
            "created_at": min(tx["created_at"] + timedelta(hours=random.uniform(1, 24)), now),
        })
    return rows


# COPY is the fastest way to load many rows into PostgreSQL.
def copy_rows(conn, table, columns, rows):
    if not rows:
        return
    with conn.cursor().copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def main():
    fake = Faker()
    now = datetime.now(timezone.utc)

    with connect() as conn:
        apply_schema(conn)
        if conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] > 0:
            raise SystemExit("Accounts already exist. Nothing was added.")

        accounts = make_accounts(fake, now)
        accounts_by_id = {a["id"]: a for a in accounts}
        by_currency = {}
        for account in accounts:
            by_currency.setdefault(account["currency"], []).append(account)

        completed = make_completed(by_currency, now)
        pending = make_open_transfers(by_currency, now, PENDING_COUNT, "pending")
        cancelled = make_open_transfers(by_currency, now, CANCELLED_COUNT, "cancelled")
        refunds = make_refunds(fake, completed, accounts_by_id, now)
        cancellations = make_cancellations(cancelled, now)

        copy_rows(
            conn, "accounts",
            ["account_id", "account_holder", "currency", "balance", "created_at"],
            [(a["id"], a["holder"], a["currency"], a["balance"], a["created_at"]) for a in accounts],
        )

        transfer_rows = []
        for tx in completed + pending + cancelled:
            transfer_rows.append((
                tx["id"], tx["from"], tx["to"], tx["amount"], tx["currency"],
                fake.sentence(nb_words=4)[:255], tx["status"], tx["created_at"], tx["updated_at"], 1,
            ))
        copy_rows(
            conn, "transactions",
            ["transaction_id", "from_account_id", "to_account_id", "amount", "currency",
             "description", "status", "created_at", "updated_at", "version"],
            transfer_rows,
        )
        copy_rows(
            conn, "refunds",
            ["refund_id", "transaction_id", "amount", "reason", "status", "created_at"],
            [(r["id"], r["transaction_id"], r["amount"], r["reason"], "processed", r["created_at"]) for r in refunds],
        )
        copy_rows(
            conn, "cancellations",
            ["cancellation_id", "transaction_id", "reason", "status", "created_at"],
            [(c["id"], c["transaction_id"], c["reason"], "completed", c["created_at"]) for c in cancellations],
        )

        # One demo client that can send money from the first accounts.
        api_key = secrets.token_urlsafe(32)
        client_id = conn.execute(
            "INSERT INTO api_clients (name, key_hash) VALUES (%s, %s) RETURNING client_id",
            ("Demo client", hash_api_key(api_key)),
        ).fetchone()["client_id"]
        for account in accounts[:DEMO_CLIENT_ACCOUNTS]:
            conn.execute(
                "INSERT INTO client_accounts (client_id, account_id) VALUES (%s, %s)",
                (client_id, account["id"]),
            )

    print(f"Accounts: {len(accounts)}")
    print(f"Transactions: {len(completed) + len(pending) + len(cancelled)} "
          f"(completed {len(completed)}, pending {len(pending)}, cancelled {len(cancelled)})")
    print(f"Refunds: {len(refunds)}")
    print(f"Demo API key (shown once, copy it now): {api_key}")


if __name__ == "__main__":
    main()
