"""Unit tests for the request shapes in validation/schemas.py.

What this file does:
    Builds request objects directly with good and bad values, and checks
    that bad values are refused. No database, no HTTP requests.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from validation.schemas import CancellationCreate, RefundCreate, TransactionCreate, TransactionUpdate


# A transfer amount of zero is refused, because it must be greater than 0.
def test_transfer_amount_must_be_positive():
    with pytest.raises(ValidationError):
        TransactionCreate(amount=Decimal("0"), currency="PKR", source="A", destination="B", description="x")


# Currency must be exactly three capital letters, so "pk" is refused.
def test_transfer_currency_must_be_three_capital_letters():
    with pytest.raises(ValidationError):
        TransactionCreate(amount=Decimal("1"), currency="pk", source="A", destination="B", description="x")


# Fields the schema does not list are refused.
def test_transfer_rejects_extra_fields():
    with pytest.raises(ValidationError):
        TransactionCreate(
            amount=Decimal("1"), currency="PKR", source="A", destination="B", description="x", extra="y"
        )


# Spaces at the start and end of names are removed before the check.
def test_transfer_strips_spaces_from_account_names():
    body = TransactionCreate(amount=Decimal("1"), currency="PKR", source="  Ali Ahmed ", destination="Maham", description="x")
    assert body.source == "Ali Ahmed"


# A complete, valid transfer is accepted and keeps its currency.
def test_valid_transfer_is_accepted():
    body = TransactionCreate(amount=Decimal("1.00"), currency="PKR", source="A", destination="B", description="x")
    assert body.currency == "PKR"


# An empty description is refused.
def test_transaction_update_description_cannot_be_empty():
    with pytest.raises(ValidationError):
        TransactionUpdate(description="")


# A cancellation with no reason gets the default reason.
def test_cancellation_reason_has_a_default():
    assert CancellationCreate().reason == "Cancelled by requester"


# A refund of zero is refused, because the amount must be greater than 0.
def test_refund_amount_must_be_positive():
    with pytest.raises(ValidationError):
        RefundCreate(amount=Decimal("0"), reason="Test")


# An empty refund reason is refused.
def test_refund_reason_cannot_be_empty():
    with pytest.raises(ValidationError):
        RefundCreate(amount=Decimal("1.00"), reason="")


# Fields the refund schema does not list are refused.
def test_refund_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RefundCreate(amount=Decimal("1.00"), reason="Test", extra="x")
