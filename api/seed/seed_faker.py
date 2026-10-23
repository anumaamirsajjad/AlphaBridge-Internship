"""Fill the database with fake bank data for testing.

What this file does:
    First run: creates the tables if they are missing, creates fake accounts and
    one demo API client, then adds transfers until the transactions table reaches
    TRANSACTION_TARGET rows.

    Later runs: reads the accounts that already exist and adds transfers until the
    target is reached again. Nothing is added if the target is already reached.

    Balances follow the same rules as the API, so no account goes negative. The
    balances are saved after every batch, so a stopped run can be started again.

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

TRANSACTION_TARGET = int(os.getenv("TRANSACTION_TARGET", "1000000"))
BATCH_SIZE = 50_000
ACCOUNT_COUNT = 200
DEMO_CLIENT_ACCOUNTS = 20
CURRENCIES = ["USD", "PKR"]
HISTORY_DAYS = 90
PENDING_SHARE = 0.05
CANCELLED_SHARE = 0.02
REFUND_SHARE = 0.03  # share of the completed transfers in each batch that are refunded

DESCRIPTIONS = [
    "Rent payment", "Grocery shopping", "Salary transfer", "Utility bill", "School fees",
    "Medical bill", "Loan repayment", "Gift", "Fuel", "Restaurant bill",
    "Mobile top-up", "Insurance premium", "Savings transfer", "Online order", "Tuition",
]
REFUND_REASONS = ["Item returned", "Duplicate payment", "Service not delivered", "Wrong amount", "Customer request"]
CANCEL_REASON = "Cancelled by requester"

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


def random_time(start, end):
    return start + timedelta(seconds=random.uniform(0, (end - start).total_seconds()))


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


def load_accounts(conn):
    rows = conn.execute("SELECT account_id, currency, balance FROM accounts").fetchall()
    return [
        {"id": r["account_id"], "currency": r["currency"].strip(), "balance": r["balance"]}
        for r in rows
    ]


# Builds one batch of transfers. Completed transfers move money now, in the order they are made,
# so no balance goes negative. Pending and cancelled transfers never move money, matching the API.
def make_batch(by_currency, accounts_by_id, now, count):
    start = now - timedelta(days=HISTORY_DAYS)
    pending_n = int(count * PENDING_SHARE)
    cancelled_n = int(count * CANCELLED_SHARE)
    completed_n = count - pending_n - cancelled_n

    transactions = []
    for _ in range(completed_n):
        source, destination = pick_pair(by_currency)
        if source["balance"] <= 0:
            continue
        amount = min(random_amount(1, 500), source["balance"])
        source["balance"] -= amount
        destination["balance"] += amount
        created = random_time(start, now)
        transactions.append({
            "id": uuid.uuid4(), "from": source["id"], "to": destination["id"], "amount": amount,
            "currency": source["currency"], "status": "completed", "created_at": created, "updated_at": created,
        })

    for status, number in (("pending", pending_n), ("cancelled", cancelled_n)):
        for _ in range(number):
            source, destination = pick_pair(by_currency)
            created = random_time(start, now)
            transactions.append({
                "id": uuid.uuid4(), "from": source["id"], "to": destination["id"],
                "amount": random_amount(1, 500), "currency": source["currency"], "status": status,
                "created_at": created, "updated_at": created,
            })

    # Refunds move the money back from the receiver to the sender, and mark the transfer refunded.
    completed = [t for t in transactions if t["status"] == "completed"]
    refunds = []
    for tx in random.sample(completed, int(len(completed) * REFUND_SHARE)):
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
            "id": uuid.uuid4(), "transaction_id": tx["id"], "amount": tx["amount"],
            "reason": random.choice(REFUND_REASONS), "created_at": refunded_at,
        })

    cancellations = []
    for tx in transactions:
        if tx["status"] == "cancelled":
            cancellations.append({
                "id": uuid.uuid4(), "transaction_id": tx["id"], "reason": CANCEL_REASON,
                "created_at": min(tx["created_at"] + timedelta(hours=random.uniform(1, 24)), now),
            })
    return transactions, refunds, cancellations


# COPY is the fastest way to load many rows into PostgreSQL.
def copy_rows(conn, table, columns, rows):
    if not rows:
        return
    with conn.cursor().copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


# Saves every account's balance, so the database matches the transfers just added.
def save_balances(conn, accounts):
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE accounts SET balance = %s WHERE account_id = %s",
            [(a["balance"], a["id"]) for a in accounts],
        )


def create_demo_client(conn, accounts):
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
    print(f"Demo API key (shown once, copy it now): {api_key}")


def main():
    fake = Faker()
    now = datetime.now(timezone.utc)

    with connect() as conn:
        apply_schema(conn)
        first_run = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] == 0
        if first_run:
            accounts = make_accounts(fake, now)
            copy_rows(
                conn, "accounts",
                ["account_id", "account_holder", "currency", "balance", "created_at"],
                [(a["id"], a["holder"], a["currency"], a["balance"], a["created_at"]) for a in accounts],
            )
            create_demo_client(conn, accounts)
        else:
            accounts = load_accounts(conn)
            print(f"Using {len(accounts)} existing accounts.")

    by_currency = {}
    for account in accounts:
        by_currency.setdefault(account["currency"], []).append(account)
    accounts_by_id = {a["id"]: a for a in accounts}

    with connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    remaining = TRANSACTION_TARGET - existing
    print(f"Transactions now: {existing}. Target: {TRANSACTION_TARGET}. To add: {max(remaining, 0)}.")

    batch_number = 0
    while remaining > 0:
        count = min(BATCH_SIZE, remaining)
        transactions, refunds, cancellations = make_batch(by_currency, accounts_by_id, now, count)
        batch_number += 1

        with connect() as conn:
            copy_rows(
                conn, "transactions",
                ["transaction_id", "from_account_id", "to_account_id", "amount", "currency",
                 "description", "status", "created_at", "updated_at", "version"],
                [
                    (t["id"], t["from"], t["to"], t["amount"], t["currency"],
                     random.choice(DESCRIPTIONS), t["status"], t["created_at"], t["updated_at"], 1)
                    for t in transactions
                ],
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
            save_balances(conn, accounts)

        remaining -= count
        print(f"Batch {batch_number}: added {len(transactions)} transactions, {len(refunds)} refunds, "
              f"{len(cancellations)} cancellations. Still to add: {max(remaining, 0)}.")

    print("Done.")


if __name__ == "__main__":
    main()
