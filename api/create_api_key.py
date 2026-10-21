"""Create an API client: a new API key linked to the accounts it may use.

What this file does:
    Makes one API key for one client (an app or a person), links the key to the
    accounts it may use, and prints the key ONCE. Only a SHA-256 hash of the key
    is saved, so the key cannot be recovered later. If it is lost, make a new one.

    If any account name does not match exactly one account, nothing is saved.

Usage (run from the api folder, with DATABASE_URL set):
    python create_api_key.py "Ali's mobile app" "Ali Ahmed" "Maham"
    The first argument is the client name. Every later argument is an account holder name.
"""

import secrets
import sys

from business.banking import hash_api_key
from data.database import connect

USAGE = 'Usage: python create_api_key.py "<client name>" "<account holder>" ["<account holder>" ...]'


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(USAGE)

    client_name, *holders = sys.argv[1:]
    api_key = secrets.token_urlsafe(32)

    with connect() as conn:
        # Find each account first. Stop before saving anything if a name is wrong.
        account_ids = []
        for holder in holders:
            rows = conn.execute(
                "SELECT account_id FROM accounts WHERE account_holder = %s",
                (holder,),
            ).fetchall()
            if len(rows) != 1:
                raise SystemExit(f"Expected exactly one account named '{holder}', found {len(rows)}. Nothing was saved.")
            account_ids.append(rows[0]["account_id"])

        client_id = conn.execute(
            "INSERT INTO api_clients (name, key_hash) VALUES (%s, %s) RETURNING client_id",
            (client_name, hash_api_key(api_key)),
        ).fetchone()["client_id"]
        for account_id in account_ids:
            conn.execute(
                "INSERT INTO client_accounts (client_id, account_id) VALUES (%s, %s)",
                (client_id, account_id),
            )

    print(f"Created client '{client_name}' with access to: {', '.join(holders)}")
    print(f"API key (shown once, copy it now): {api_key}")


if __name__ == "__main__":
    main()
