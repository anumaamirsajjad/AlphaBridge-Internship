"""Unit tests for the header readers and error reply in presentation/main.py.

What this file does:
    Calls the header helpers and the error handler directly, with chosen
    inputs. No database, no HTTP requests.
"""

import json
from uuid import UUID

import pytest

from business.banking import BadRequestError, ConflictError, PreconditionRequiredError
from presentation.main import banking_error_handler, read_idempotency_key, read_version

VALID_UUID = "6f1c2a3e-8b7d-4c5e-9a10-2b3c4d5e6f70"


# A valid UUID in the Idempotency-Key header is read as a UUID object.
def test_idempotency_key_accepts_a_valid_uuid():
    assert read_idempotency_key(VALID_UUID) == UUID(VALID_UUID)


# A missing Idempotency-Key header is refused.
def test_idempotency_key_is_required():
    with pytest.raises(BadRequestError):
        read_idempotency_key(None)


# A value that is not a UUID is refused.
def test_idempotency_key_must_be_a_uuid():
    with pytest.raises(BadRequestError):
        read_idempotency_key("not-a-uuid")


# The If-Match version is read as a number, with or without quotes.
def test_version_reads_quoted_and_plain_numbers():
    assert read_version('"3"') == 3
    assert read_version("3") == 3


# A missing If-Match header is refused with 428.
def test_version_is_required():
    with pytest.raises(PreconditionRequiredError):
        read_version(None)


# Zero is not a valid version.
def test_version_must_be_positive():
    with pytest.raises(BadRequestError):
        read_version('"0"')


# Text that is not a number is refused.
def test_version_must_be_a_number():
    with pytest.raises(BadRequestError):
        read_version('"abc"')


# A banking error becomes a reply with its own status code and detail message.
def test_error_handler_uses_the_error_status_and_detail():
    response = banking_error_handler(None, ConflictError("Already used."))

    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "Already used."}
