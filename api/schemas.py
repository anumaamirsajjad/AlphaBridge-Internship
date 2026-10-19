"""The shape of every request and reply.

Pydantic checks each request against these classes before any banking code
runs. A wrong value (for example a negative amount) gets a 422 reply.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# The statuses a transaction can have.
class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# Base class for request bodies.
# strip_whitespace: spaces at the ends are removed.
# extra="forbid": an unknown field is an error, not silently ignored.
class RequestBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class TransactionCreate(RequestBody):
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")  # three capital letters, e.g. PKR
    source: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=255)


class TransactionUpdate(RequestBody):
    description: str = Field(min_length=1, max_length=255)


class CancellationCreate(RequestBody):
    reason: str = Field(default="Cancelled by requester", min_length=1, max_length=255)


class RefundCreate(RequestBody):
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    reason: str = Field(min_length=1, max_length=255)


# What a transaction looks like in a reply.
class TransactionResponse(BaseModel):
    transaction_id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount: Decimal  # sent as text such as "1.00", so the cents stay exact
    currency: str
    description: str
    status: TransactionStatus
    created_at: datetime
    updated_at: datetime
    version: int  # goes up by 1 on every change


class TransactionPage(BaseModel):
    items: list[TransactionResponse]
    limit: int
    offset: int


class CancellationResponse(BaseModel):
    transaction_id: UUID
    status: TransactionStatus
    version: int
    updated_at: datetime


class RefundResponse(BaseModel):
    refund_id: UUID
    transaction_id: UUID
    amount: Decimal
    reason: str
    status: str
    created_at: datetime
