"""Unit tests for the small helper functions in business/banking.py.

What this file does:
    Calls each helper directly with chosen inputs and checks the output.
    No database, no HTTP requests.
"""

import hashlib
from unittest.mock import MagicMock

from business.banking import find_client_id, fingerprint, hash_api_key, same_name


# Names match when they differ only in case and surrounding spaces.
def test_same_name_ignores_case_and_spaces():
    assert same_name("  Ali Ahmed ", "ali ahmed")


# Names that differ in more than case or spacing do not match.
def test_same_name_rejects_different_names():
    assert not same_name("Ali", "Alia")


# The stored hash is the SHA-256 of the key, written as hex text.
def test_hash_api_key_is_sha256_hex():
    assert hash_api_key("abc") == hashlib.sha256(b"abc").hexdigest()


# Key order in a dictionary must not change the fingerprint.
# A request body arrives as a dictionary, and the order of its 
# fields isn't guaranteed. If the order changed the fingerprint,
# a genuine retry would look like a different request, and the 
# API would wrongly refuse it with 409.
def test_fingerprint_ignores_key_order():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


# A different value must produce a different fingerprint.
# This is the opposite check. If the fingerprint ignored the
# amount, a reused key with a different amount would look like
# the same request, and the API would wrongly return the old
# answer.
def test_fingerprint_changes_when_value_changes():
    assert fingerprint({"amount": "1.00"}) != fingerprint({"amount": "2.00"})


# The lookup returns the client ID of the key's owner.
def test_find_client_id_returns_the_owner():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"client_id": 7}

    assert find_client_id(conn, "my-key") == 7


# The lookup searches by the key's hash, never by the key itself.
def test_find_client_id_searches_by_hash():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    find_client_id(conn, "my-key")

    assert conn.execute.call_args.args[1] == (hash_api_key("my-key"),)


# An unknown key gives no client.
def test_find_client_id_returns_none_for_unknown_key():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None

    assert find_client_id(conn, "bad-key") is None
